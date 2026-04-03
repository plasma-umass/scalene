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

def run_scalene(script_path, output_path, extra_args=None, env=None):
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

    run_env = None
    if env:
        run_env = {**os.environ, **env}
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                          env=run_env)
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


CONCURRENCY_WORKLOAD = """\
import os
import threading
import numpy as np

N_THREADS = int(os.environ["SCALENE_TEST_NTHREADS"])
# Each thread allocates ALLOC_MB of native memory via numpy.
ALLOC_MB = 50

def allocator_thread(tid):
    n_floats = (ALLOC_MB * 1024 * 1024) // 8  # float64 = 8 bytes
    arrays = []
    # Do several rounds to give the sampler more chances to observe.
    for _ in range(3):
        arrays.append(np.random.rand(n_floats))
    # Touch the data so it's not optimised away.
    return sum(a.sum() for a in arrays)

results = [None] * N_THREADS

def target(tid):
    results[tid] = allocator_thread(tid)

threads = [threading.Thread(target=target, args=(i,)) for i in range(N_THREADS)]
for t in threads:
    t.start()
for t in threads:
    t.join()

print(f"threads={N_THREADS} results={len([r for r in results if r is not None])}")
"""


def run_concurrency_test(tmpdir):
    """Phase 3: verify that concurrent native allocations scale.

    Run the same per-thread workload at 1, 2, 4, and 8 threads.  Each
    thread allocates ~150 MB of numpy arrays (native malloc).  If the
    profiler's size tracking is correct, total attributed memory should
    scale roughly with thread count.  A failure here means the
    ShardedSizeMap (free-threaded) or ScaleneHeader (regular) is losing
    allocations under contention.
    """
    script = os.path.join(tmpdir, "concurrency_workload.py")
    with open(script, "w") as f:
        f.write(CONCURRENCY_WORKLOAD)

    thread_counts = [1, 2, 4, 8]
    results = {}  # n_threads -> total_malloc_mb

    print("\nPhase 3: concurrency scaling (native memory)...")
    for n in thread_counts:
        out = os.path.join(tmpdir, f"profile_conc_{n}.json")
        profile, rc, stderr = run_scalene(
            script, out, env={"SCALENE_TEST_NTHREADS": str(n)}
        )

        if rc != 0:
            print(f"  {n} threads: Scalene exited with code {rc}")
            print(f"  STDERR:\n{stderr}")
            sys.exit(1)

        check(profile is not None, f"No JSON profile for {n} threads")
        fname = find_file(profile, "concurrency_workload.py")
        check(fname is not None,
              f"concurrency_workload.py not found for {n} threads. "
              f"Files: {list(profile['files'].keys())}")

        m = extract_metrics(profile, fname)
        results[n] = m["total_malloc_mb"]
        print(f"  {n:2d} thread(s): {m['total_malloc_mb']:8.1f} MB malloc, "
              f"{m['lines_with_memory']} lines, "
              f"footprint {m['max_footprint_mb']:.1f} MB")

    # ---- Validate scaling ----
    # Each thread allocates ~150 MB (3 rounds × 50 MB).  With N threads
    # the nominal total is N × 150 MB.  Sampling is probabilistic so we
    # can't expect exact numbers, but we can check:
    #
    # 1. Every thread count reports *some* memory (> 1 MB).
    for n in thread_counts:
        check(results[n] > 1,
              f"No memory attributed at {n} threads ({results[n]:.1f} MB)")

    # 2. More threads should report more total memory.  We check that
    #    8 threads attributes at least 2× what 1 thread does.  This is
    #    generous — nominal ratio is 8× — to tolerate sampling variance.
    ratio_8_to_1 = results[8] / max(results[1], 0.01)
    print(f"\n  Scaling ratio (8 threads / 1 thread): {ratio_8_to_1:.2f}x "
          f"(nominal 8x)")
    check(ratio_8_to_1 >= 2.0,
          f"Memory attribution did not scale with threads: "
          f"8-thread={results[8]:.1f} MB vs 1-thread={results[1]:.1f} MB "
          f"(ratio {ratio_8_to_1:.2f}x, expected >= 2x)")

    # 3. The 8-thread run should attribute a substantial fraction of
    #    the nominal 1200 MB (8 × 150 MB).  Require at least 20% to be
    #    visible — very conservative, but catches total tracking failure.
    nominal_8 = 8 * 150
    fraction = results[8] / nominal_8
    print(f"  8-thread coverage: {results[8]:.1f} / {nominal_8} MB "
          f"= {fraction:.0%}")
    check(fraction >= 0.20,
          f"8-thread memory too low: {results[8]:.1f} MB, "
          f"expected >= 20% of {nominal_8} MB")

    return results


# ── Main ────────────────────────────────────────────────────────────

def main():
    is_free_threaded = hasattr(sys, "_is_gil_enabled") or bool(
        __import__("sysconfig").get_config_var("Py_GIL_DISABLED")
    )
    build_label = "free-threaded" if is_free_threaded else "regular"
    print(f"Python {sys.version} ({build_label})")

    tmpdir = tempfile.mkdtemp(prefix="scalene_parity_")

    run_base_test(tmpdir)

    if has_numpy():
        run_numpy_test(tmpdir)
        run_concurrency_test(tmpdir)
    else:
        print("\nPhase 2: SKIPPED (numpy not available)")
        print("Phase 3: SKIPPED (numpy not available)")

    print("\nPASS: All checks passed.")


if __name__ == "__main__":
    main()
