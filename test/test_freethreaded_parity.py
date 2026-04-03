#!/usr/bin/env python3
"""Test that free-threaded Python profiling produces results comparable to
regular (GIL-enabled) Python.

This test exercises CPU time attribution, memory allocation tracking
(both Python and native/C via numpy), and native code profiling across
multiple threads.  It is designed to run on *any* Python version: on
non-free-threaded builds it validates that the profiler works correctly
with the workload; on free-threaded builds it does the same.  CI runs it
on both, so regressions in either path are caught.

The test is intentionally written as a standalone script (not pytest) so
it can be invoked directly from the CI workflow on every matrix entry.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile

# ── Workload scripts ────────────────────────────────────────────────
# Written to temp files and profiled by Scalene as subprocesses.

WORKLOAD_BASE = """\
import threading

# --------------- CPU-intensive work (Python) ---------------
def python_cpu_work():
    total = 0
    for i in range(2_000_000):
        total += i * i
    return total

# --------------- Native / C work ---------------
def native_cpu_work():
    data = list(range(1_000_000, 0, -1))
    for _ in range(3):
        data = sorted(data, reverse=True)
    return data[0]

# --------------- Python memory allocation ---------------
def memory_work():
    buffers = []
    for _ in range(5):
        buffers.append([0] * 4_000_000)  # ~160 MB total
    return sum(len(b) for b in buffers)

# --------------- Threaded workload ---------------
results = {}

def thread_target(name, func):
    results[name] = func()

def main():
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

    # Also run on main thread to test main-thread attribution.
    results["main_python"] = python_cpu_work()
    results["main_memory"] = memory_work()

    for k, v in sorted(results.items()):
        print(f"{k}: {v}")

if __name__ == "__main__":
    main()
"""

WORKLOAD_NUMPY = """\
import threading
import numpy as np

# --------------- CPU-intensive work (Python) ---------------
def python_cpu_work():
    total = 0
    for i in range(2_000_000):
        total += i * i
    return total

# --------------- Native / C work ---------------
def native_cpu_work():
    data = list(range(1_000_000, 0, -1))
    for _ in range(3):
        data = sorted(data, reverse=True)
    return data[0]

# --------------- Python memory allocation ---------------
def memory_work():
    buffers = []
    for _ in range(5):
        buffers.append([0] * 4_000_000)  # ~160 MB total
    return sum(len(b) for b in buffers)

# --------------- Native memory allocation (numpy) ---------------
def numpy_memory_work():
    arrays = []
    for _ in range(5):
        # float64: 5M * 8 bytes = 40 MB each, 200 MB total
        arrays.append(np.random.rand(5_000_000))
    return sum(a.sum() for a in arrays)

# --------------- Native CPU work (numpy BLAS) ---------------
def numpy_cpu_work():
    a = np.random.rand(800, 800)
    for _ in range(5):
        _ = a @ a.T  # matrix multiply
    return a[0, 0]

# --------------- Threaded workload ---------------
results = {}

def thread_target(name, func):
    results[name] = func()

def main():
    threads = []
    for name, func in [
        ("python_cpu", python_cpu_work),
        ("native_cpu", native_cpu_work),
        ("memory", memory_work),
        ("numpy_mem", numpy_memory_work),
        ("numpy_cpu", numpy_cpu_work),
    ]:
        t = threading.Thread(target=thread_target, args=(name, func))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Also run on main thread.
    results["main_python"] = python_cpu_work()
    results["main_memory"] = memory_work()
    results["main_numpy_mem"] = numpy_memory_work()

    for k, v in sorted(results.items()):
        print(f"{k}: {v}")

if __name__ == "__main__":
    main()
"""


# ── Helpers ─────────────────────────────────────────────────────────

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


def find_file(profile, basename):
    """Locate *basename* inside the profile's 'files' dict."""
    target_parts = pathlib.PurePath(basename).parts
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
    total_copy_mb_s = 0.0
    lines_with_cpu = 0
    lines_with_memory = 0

    for line in lines:
        cpu_py = line.get("n_cpu_percent_python", 0.0)
        cpu_c = line.get("n_cpu_percent_c", 0.0)
        cpu_sys = line.get("n_sys_percent", 0.0)
        malloc_mb = line.get("n_malloc_mb", 0.0)
        copy_mb_s = line.get("n_copy_mb_s", 0.0)

        total_cpu_python += cpu_py
        total_cpu_c += cpu_c
        total_cpu_sys += cpu_sys
        total_malloc_mb += malloc_mb
        total_copy_mb_s += copy_mb_s

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
        "total_copy_mb_s": total_copy_mb_s,
        "lines_with_cpu": lines_with_cpu,
        "lines_with_memory": lines_with_memory,
        "max_footprint_mb": profile.get("max_footprint_mb", 0.0),
    }


def check(condition, msg):
    """Assert-like helper that prints diagnostics and exits on failure."""
    if not condition:
        print(f"FAIL: {msg}", file=sys.stderr)
        sys.exit(1)


def print_metrics(m, label=""):
    if label:
        print(f"  [{label}]")
    print(f"  CPU (Python): {m['total_cpu_python']:.1f}%")
    print(f"  CPU (C/native): {m['total_cpu_c']:.1f}%")
    print(f"  CPU (system): {m['total_cpu_sys']:.1f}%")
    print(f"  CPU (total): {m['total_cpu']:.1f}%")
    print(f"  Malloc total: {m['total_malloc_mb']:.1f} MB")
    print(f"  Max footprint: {m['max_footprint_mb']:.1f} MB")
    print(f"  Memcpy rate: {m['total_copy_mb_s']:.1f} MB/s")
    print(f"  Lines with CPU: {m['lines_with_cpu']}")
    print(f"  Lines with memory: {m['lines_with_memory']}")


def has_numpy():
    """Check whether numpy is importable with the current interpreter."""
    proc = subprocess.run(
        [sys.executable, "-c", "import numpy"],
        capture_output=True, timeout=30,
    )
    return proc.returncode == 0


# ── Test phases ─────────────────────────────────────────────────────

def run_base_test(tmpdir):
    """Phase 1: base workload (Python CPU + native CPU + Python memory)."""
    script = os.path.join(tmpdir, "workload.py")
    with open(script, "w") as f:
        f.write(WORKLOAD_BASE)

    # ---- Full profiling (CPU + memory) ----
    out = os.path.join(tmpdir, "profile_full.json")
    print("Phase 1: base workload (full profiling)...")
    profile, rc, stderr = run_scalene(script, out)

    if rc != 0:
        print(f"Scalene exited with code {rc}\nSTDERR:\n{stderr}")
        sys.exit(1)

    check(profile is not None, "No JSON profile produced")
    check(len(profile.get("files", {})) > 0, "No files in profile output")

    fname = find_file(profile, "workload.py")
    check(fname is not None,
          f"workload.py not found in profile. Files: {list(profile['files'].keys())}")

    m = extract_metrics(profile, fname)
    print_metrics(m)

    # CPU
    check(m["total_cpu"] > 0, "No CPU time attributed at all")
    check(m["lines_with_cpu"] >= 2,
          f"Expected CPU on >=2 lines, got {m['lines_with_cpu']}")
    check(m["total_cpu_python"] > 0,
          "No Python CPU time detected (python_cpu_work should register)")

    # Memory
    check(m["lines_with_memory"] >= 1,
          f"Expected memory on >=1 line, got {m['lines_with_memory']}")
    check(m["total_malloc_mb"] > 1,
          f"Expected >1 MB malloc attributed, got {m['total_malloc_mb']:.1f} MB")

    if m["total_cpu_c"] == 0:
        print("  WARNING: No C/native CPU time detected (sampling may have missed it)")

    # ---- CPU-only mode ----
    out_cpu = os.path.join(tmpdir, "profile_cpu.json")
    print("\nPhase 1b: base workload (cpu-only)...")
    profile_cpu, rc_cpu, stderr_cpu = run_scalene(script, out_cpu, ["--cpu-only"])

    if rc_cpu != 0:
        print(f"CPU-only Scalene exited with code {rc_cpu}\nSTDERR:\n{stderr_cpu}")
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

    return m


def run_numpy_test(tmpdir):
    """Phase 2: numpy workload (native memory allocation + BLAS CPU)."""
    script = os.path.join(tmpdir, "workload_numpy.py")
    with open(script, "w") as f:
        f.write(WORKLOAD_NUMPY)

    out = os.path.join(tmpdir, "profile_numpy.json")
    print("\nPhase 2: numpy workload (full profiling)...")
    profile, rc, stderr = run_scalene(script, out)

    if rc != 0:
        print(f"Scalene exited with code {rc}\nSTDERR:\n{stderr}")
        sys.exit(1)

    check(profile is not None, "No JSON profile produced (numpy workload)")
    check(len(profile.get("files", {})) > 0, "No files in numpy profile")

    fname = find_file(profile, "workload_numpy.py")
    check(fname is not None,
          f"workload_numpy.py not found. Files: {list(profile['files'].keys())}")

    m = extract_metrics(profile, fname)
    print_metrics(m, label="numpy")

    # CPU — should still see Python CPU from python_cpu_work
    check(m["total_cpu"] > 0, "No CPU time attributed (numpy workload)")
    check(m["total_cpu_python"] > 0,
          "No Python CPU time detected in numpy workload")

    # Memory — numpy allocates ~200 MB via native malloc (not pymalloc),
    # plus the base workload's ~320 MB via Python lists.
    # We should see *at least* the Python-side allocations.
    check(m["lines_with_memory"] >= 1,
          f"Expected memory on >=1 line (numpy), got {m['lines_with_memory']}")
    check(m["total_malloc_mb"] > 1,
          f"Expected >1 MB malloc (numpy), got {m['total_malloc_mb']:.1f} MB")

    # Native memory — numpy arrays go through the system allocator (malloc),
    # which Scalene intercepts via libscalene.  The ~200 MB from
    # np.random.rand should be visible.  Because sampling is probabilistic,
    # we use a generous threshold: at least 10 MB attributed.
    # On free-threaded builds this specifically exercises the ShardedSizeMap
    # path (no ScaleneHeader), so a failure here means size tracking broke.
    check(m["total_malloc_mb"] > 10,
          f"Expected >10 MB malloc with numpy native allocs, "
          f"got {m['total_malloc_mb']:.1f} MB")

    # The total should be substantially higher than the base workload alone
    # because numpy adds ~200 MB of native allocations on top of the ~320 MB
    # Python lists.  We don't compare directly (sampling variance), but we
    # log it for manual inspection.
    print(f"  Total memory attributed: {m['total_malloc_mb']:.1f} MB "
          f"(expect ~520 MB nominal)")

    # Memcpy — numpy operations often trigger large memcpy calls that
    # Scalene intercepts.  This is informational, not a hard requirement.
    if m["total_copy_mb_s"] > 0:
        print(f"  Memcpy activity detected: {m['total_copy_mb_s']:.1f} MB/s")
    else:
        print("  WARNING: No memcpy activity detected (sampling may have missed it)")

    return m


# ── Main ────────────────────────────────────────────────────────────

def main():
    is_free_threaded = hasattr(sys, "_is_gil_enabled") or bool(
        __import__("sysconfig").get_config_var("Py_GIL_DISABLED")
    )
    build_label = "free-threaded" if is_free_threaded else "regular"
    print(f"Python {sys.version} ({build_label})")

    tmpdir = tempfile.mkdtemp(prefix="scalene_parity_")

    m_base = run_base_test(tmpdir)

    if has_numpy():
        m_numpy = run_numpy_test(tmpdir)
    else:
        print("\nPhase 2: SKIPPED (numpy not available)")

    print("\nPASS: All checks passed.")


if __name__ == "__main__":
    main()
