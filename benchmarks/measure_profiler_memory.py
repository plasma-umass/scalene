"""Measure Scalene's peak RSS while profiling a torch-heavy workload.

Usage
-----
    # On the current branch (should be the fix branch):
    python benchmarks/measure_profiler_memory.py

    # Compare against master:
    python benchmarks/measure_profiler_memory.py --compare-master

The ``--compare-master`` flag will:
  1. Run the benchmark on the *current* branch and record peak RSS.
  2. Check out ``master``, run the benchmark again, then restore the
     original branch.
  3. Print a side-by-side comparison.

Without the flag it simply profiles and reports peak RSS for the
current checkout.

Requirements: torch (``pip install torch``).
"""

from __future__ import annotations

import argparse
import os
import platform
import resource
import shutil
import subprocess
import sys
import tempfile
import threading
import time

BENCH_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_torch_memory.py")
SAMPLE_INTERVAL = 0.5  # seconds between RSS samples


# --- RSS monitoring ----------------------------------------------------------

def _get_rss_mb(pid: int) -> float | None:
    """Return the RSS of *pid* in MiB, or None if unavailable."""
    try:
        if platform.system() == "Darwin":
            # macOS: use ps (reading /proc is not available)
            out = subprocess.check_output(
                ["ps", "-o", "rss=", "-p", str(pid)],
                stderr=subprocess.DEVNULL,
            )
            return int(out.strip()) / 1024  # ps reports KiB on macOS
        else:
            # Linux: read from /proc
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) / 1024  # KiB -> MiB
    except (subprocess.CalledProcessError, FileNotFoundError, ProcessLookupError,
            ValueError, OSError):
        pass
    return None


class RSSMonitor:
    """Sample RSS of a subprocess at regular intervals in a background thread."""

    def __init__(self, pid: int, interval: float = SAMPLE_INTERVAL) -> None:
        self.pid = pid
        self.interval = interval
        self.samples: list[float] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            rss = _get_rss_mb(self.pid)
            if rss is not None:
                self.samples.append(rss)
            self._stop.wait(self.interval)

    @property
    def peak_mb(self) -> float:
        return max(self.samples) if self.samples else 0.0

    @property
    def final_mb(self) -> float:
        return self.samples[-1] if self.samples else 0.0


# --- Run benchmark under Scalene --------------------------------------------

def run_scalene_benchmark(bench_script: str) -> tuple[float, float, float]:
    """Profile the workload with Scalene and return (peak_rss_mb, final_rss_mb, elapsed_s)."""
    # Run in a temp dir so scalene-profile.json doesn't pollute the repo
    work_dir = tempfile.mkdtemp(prefix="scalene-bench-")
    cmd = [
        sys.executable, "-m", "scalene", "run",
        bench_script,
    ]
    print(f"  Command: {' '.join(cmd)}")
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=work_dir,
    )
    monitor = RSSMonitor(proc.pid)
    monitor.start()
    stdout, _ = proc.communicate()
    monitor.stop()
    elapsed = time.perf_counter() - t0

    # Print the workload output (indented)
    for line in stdout.decode(errors="replace").splitlines():
        print(f"    {line}")

    # Also grab rusage as a cross-check
    rusage = resource.getrusage(resource.RUSAGE_CHILDREN)
    rusage_bytes = rusage.ru_maxrss
    if platform.system() != "Darwin":
        # Linux reports KiB; convert to bytes
        rusage_bytes *= 1024
    rusage_mib = rusage_bytes / (1024 * 1024)

    print(f"  RSS samples collected: {len(monitor.samples)}")
    print(f"  Peak RSS (sampled):  {monitor.peak_mb:,.1f} MiB")
    print(f"  Final RSS (sampled): {monitor.final_mb:,.1f} MiB")
    print(f"  Peak RSS (rusage):   {rusage_mib:,.1f} MiB")
    print(f"  Wall time:           {elapsed:.1f}s")

    # Clean up temp dir
    shutil.rmtree(work_dir, ignore_errors=True)

    return monitor.peak_mb, monitor.final_mb, elapsed


# --- Git helpers for --compare-master ----------------------------------------

def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], stderr=subprocess.STDOUT,
    ).decode().strip()


def compare_master() -> None:
    original_branch = git("rev-parse", "--abbrev-ref", "HEAD")
    print(f"Current branch: {original_branch}\n")

    # Copy the benchmark script to a temp file so it's available on both branches
    tmp_fd, tmp_bench_name = tempfile.mkstemp(prefix="bench_torch_memory_", suffix=".py")
    os.close(tmp_fd)
    try:
        shutil.copy2(BENCH_SCRIPT, tmp_bench_name)

        # --- Run on current branch -------------------------------------------
        print(f"=== Benchmarking on {original_branch} ===")
        fix_peak, fix_final, fix_elapsed = run_scalene_benchmark(tmp_bench_name)

        # --- Switch to master ------------------------------------------------
        print()
        print("=== Benchmarking on master ===")
        git("checkout", "master")
        try:
            master_peak, master_final, master_elapsed = run_scalene_benchmark(tmp_bench_name)
        finally:
            # Always restore original branch
            print(f"\nRestoring branch {original_branch} ...")
            git("checkout", original_branch)
    finally:
        os.unlink(tmp_bench_name)

    # --- Report --------------------------------------------------------------
    print()
    print("=" * 60)
    print(f"{'':30s} {'master':>12s}  {'fix':>12s}")
    print("-" * 60)
    print(f"{'Peak RSS (MiB)':30s} {master_peak:12,.1f}  {fix_peak:12,.1f}")
    print(f"{'Final RSS (MiB)':30s} {master_final:12,.1f}  {fix_final:12,.1f}")
    print(f"{'Wall time (s)':30s} {master_elapsed:12.1f}  {fix_elapsed:12.1f}")
    if master_peak > 0:
        reduction = (1 - fix_peak / master_peak) * 100
        print(f"{'Peak RSS reduction':30s} {reduction:11.1f}%")
    print("=" * 60)


# --- Main --------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--compare-master", action="store_true",
        help="Run on both the current branch and master, then compare.",
    )
    args = parser.parse_args()

    if args.compare_master:
        compare_master()
    else:
        print("=== Benchmarking on current checkout ===")
        run_scalene_benchmark(BENCH_SCRIPT)


if __name__ == "__main__":
    main()
