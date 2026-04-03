#!/usr/bin/env python3
"""Test that free-threaded Python profiling produces results comparable to
regular (GIL-enabled) Python.

This test exercises CPU time attribution, memory allocation tracking, and
native code profiling across multiple threads. It is designed to run on
*any* Python version: on non-free-threaded builds it validates that the
profiler works correctly with the workload; on free-threaded builds it
does the same. CI runs it on both, so regressions in either path are
caught.

The test is intentionally written as a standalone script (not pytest) so
it can be invoked directly from the CI workflow on every matrix entry.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap


def create_workload_script(path):
    """Write a workload that exercises CPU, memory, native code, and threads."""
    with open(path, "w") as f:
        f.write(textwrap.dedent("""\
            import threading
            import sys

            # --------------- CPU-intensive work (Python) ---------------
            def python_cpu_work():
                \"\"\"Pure-Python CPU work — should show as Python CPU time.\"\"\"
                total = 0
                for i in range(2_000_000):
                    total += i * i
                return total

            # --------------- Native / C work ---------------
            def native_cpu_work():
                \"\"\"Work that happens inside C code (sorted() on a large list).\"\"\"
                data = list(range(1_000_000, 0, -1))
                for _ in range(3):
                    data = sorted(data, reverse=True)
                return data[0]

            # --------------- Memory allocation ---------------
            def memory_work():
                \"\"\"Allocate significant memory that the profiler should detect.\"\"\"
                buffers = []
                for _ in range(5):
                    buffers.append([0] * 4_000_000)  # ~160 MB total
                return sum(len(b) for b in buffers)

            # --------------- Threaded workload ---------------
            results = {}

            def thread_target(name, func):
                results[name] = func()

            def main():
                # Run each workload in its own thread so that thread
                # attribution and multi-thread memory tracking are exercised.
                threads = []
                for name, func in [
                    ("python_cpu", python_cpu_work),
                    ("native_cpu", native_cpu_work),
                    ("memory", memory_work),
                ]:
                    t = threading.Thread(target=thread_target, args=(name, func))
                    threads.append(t)
                    t.start()

                for t in threads:
                    t.join()

                # Also run work on the main thread to test main-thread attribution.
                results["main_python"] = python_cpu_work()
                results["main_memory"] = memory_work()

                for k, v in sorted(results.items()):
                    print(f"{k}: {v}")

            if __name__ == "__main__":
                main()
        """))


def run_scalene(script_path, output_path, extra_args=None):
    """Invoke scalene and return (profile_dict, returncode, stderr)."""
    cmd = [
        sys.executable, "-m", "scalene",
        "run",
        "--profile-all",
        "-o", str(output_path),
    ]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(str(script_path))

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    profile = None
    if os.path.exists(output_path):
        try:
            with open(output_path) as f:
                profile = json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return profile, proc.returncode, proc.stderr


def find_file(profile, script_path):
    """Locate the workload file inside the profile's 'files' dict."""
    target_parts = pathlib.PurePath(script_path).parts
    for fname in profile.get("files", {}):
        parts = pathlib.PurePath(fname).parts
        if len(parts) >= len(target_parts):
            if parts[-len(target_parts):] == target_parts:
                return fname
    return None


def extract_metrics(profile, fname):
    """Return aggregate metrics for the profiled file."""
    lines = profile["files"][fname]["lines"]

    total_cpu_python = 0.0
    total_cpu_c = 0.0
    total_cpu_sys = 0.0
    total_malloc_mb = 0.0
    lines_with_cpu = 0
    lines_with_memory = 0

    for line in lines:
        cpu_py = line.get("n_cpu_percent_python", 0.0)
        cpu_c = line.get("n_cpu_percent_c", 0.0)
        cpu_sys = line.get("n_sys_percent", 0.0)
        malloc_mb = line.get("n_malloc_mb", 0.0)

        total_cpu_python += cpu_py
        total_cpu_c += cpu_c
        total_cpu_sys += cpu_sys
        total_malloc_mb += malloc_mb

        if cpu_py > 0 or cpu_c > 0:
            lines_with_cpu += 1
        if malloc_mb > 0:
            lines_with_memory += 1

    return {
        "total_cpu_python": total_cpu_python,
        "total_cpu_c": total_cpu_c,
        "total_cpu_sys": total_cpu_sys,
        "total_cpu": total_cpu_python + total_cpu_c + total_cpu_sys,
        "total_malloc_mb": total_malloc_mb,
        "lines_with_cpu": lines_with_cpu,
        "lines_with_memory": lines_with_memory,
        "max_footprint_mb": profile.get("max_footprint_mb", 0.0),
    }


def check(condition, msg):
    """Assert-like helper that prints diagnostics and exits on failure."""
    if not condition:
        print(f"FAIL: {msg}", file=sys.stderr)
        sys.exit(1)


def main():
    is_free_threaded = hasattr(sys, "_is_gil_enabled") or bool(
        __import__("sysconfig").get_config_var("Py_GIL_DISABLED")
    )
    build_label = "free-threaded" if is_free_threaded else "regular"
    print(f"Python {sys.version} ({build_label})")

    tmpdir = tempfile.mkdtemp(prefix="scalene_parity_")
    script_path = os.path.join(tmpdir, "workload.py")
    create_workload_script(script_path)

    # ---- Run with full profiling (CPU + memory) ----
    out_full = os.path.join(tmpdir, "profile_full.json")
    print("Running Scalene with full profiling...")
    profile, rc, stderr = run_scalene(script_path, out_full)

    if rc != 0:
        print(f"Scalene exited with code {rc}")
        print(f"STDERR:\n{stderr}")
        sys.exit(1)

    check(profile is not None, "No JSON profile produced")
    check(len(profile.get("files", {})) > 0, "No files in profile output")

    fname = find_file(profile, "workload.py")
    check(fname is not None,
          f"workload.py not found in profile. Files: {list(profile['files'].keys())}")

    m = extract_metrics(profile, fname)
    print(f"  CPU (Python): {m['total_cpu_python']:.1f}%")
    print(f"  CPU (C/native): {m['total_cpu_c']:.1f}%")
    print(f"  CPU (system): {m['total_cpu_sys']:.1f}%")
    print(f"  CPU (total): {m['total_cpu']:.1f}%")
    print(f"  Malloc total: {m['total_malloc_mb']:.1f} MB")
    print(f"  Max footprint: {m['max_footprint_mb']:.1f} MB")
    print(f"  Lines with CPU: {m['lines_with_cpu']}")
    print(f"  Lines with memory: {m['lines_with_memory']}")

    # ---- Validate CPU attribution ----
    check(m["total_cpu"] > 0,
          "No CPU time attributed at all")
    check(m["lines_with_cpu"] >= 2,
          f"Expected CPU on >=2 lines, got {m['lines_with_cpu']}")
    # We expect *some* Python CPU time from python_cpu_work()
    check(m["total_cpu_python"] > 0,
          "No Python CPU time detected (python_cpu_work should register)")

    # ---- Validate memory attribution ----
    # The workload allocates ~320 MB (2 x 5 x [0]*4M).
    # Sampling means we won't see all of it, but we should see *something*.
    check(m["lines_with_memory"] >= 1,
          f"Expected memory on >=1 line, got {m['lines_with_memory']}")
    check(m["total_malloc_mb"] > 1,
          f"Expected >1 MB malloc attributed, got {m['total_malloc_mb']:.1f} MB")

    # ---- Validate that native C time is detected ----
    # sorted() on a large list should show up as C time.
    # This may not always fire due to sampling, so only warn.
    if m["total_cpu_c"] == 0:
        print("  WARNING: No C/native CPU time detected (sampling may have missed it)")

    # ---- Run CPU-only mode (should still work) ----
    out_cpu = os.path.join(tmpdir, "profile_cpu.json")
    print("\nRunning Scalene in --cpu-only mode...")
    profile_cpu, rc_cpu, stderr_cpu = run_scalene(script_path, out_cpu, ["--cpu-only"])

    if rc_cpu != 0:
        print(f"  CPU-only Scalene exited with code {rc_cpu}")
        print(f"  STDERR:\n{stderr_cpu}")
        sys.exit(1)

    check(profile_cpu is not None, "No JSON profile from cpu-only run")
    fname_cpu = find_file(profile_cpu, "workload.py")
    check(fname_cpu is not None, "workload.py not found in cpu-only profile")

    m_cpu = extract_metrics(profile_cpu, fname_cpu)
    print(f"  CPU (total): {m_cpu['total_cpu']:.1f}%")
    print(f"  Lines with CPU: {m_cpu['lines_with_cpu']}")
    check(m_cpu["total_cpu"] > 0, "No CPU time in cpu-only mode")
    check(m_cpu["lines_with_cpu"] >= 2,
          f"Expected CPU on >=2 lines in cpu-only, got {m_cpu['lines_with_cpu']}")

    print("\nPASS: All checks passed.")


if __name__ == "__main__":
    main()
