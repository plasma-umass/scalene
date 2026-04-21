#!/usr/bin/env python3
"""
Regression test for https://github.com/plasma-umass/scalene/discussions/659.

Bug: in a program where a threading.Thread worker did a loop of numpy
allocations while the main thread was in time.sleep(), scalene attributed
all the numpy bytes to the sleep line. The fix ensures per-thread
attribution (see pywhere.cpp + the <native> sentinel introduced for #857).

This driver runs test/issue_659_workload.py under `scalene run --memory`,
then fails if:
  - the profiler did not run to completion, or
  - the JSON is invalid / missing the workload file, or
  - (when memory samples were actually collected) the main-thread
    time.sleep line has implausibly large malloc attribution (the bug
    symptom), or the worker's numpy allocation line has almost none
    despite sampling having fired on other lines.

The thresholds are intentionally loose so the test does not flake on
platforms / CI runners where sampling timing is noisy; the bug attributes
_hundreds_ of MB to the wrong line, so a 100 MB cap is still ample
headroom over normal noise (~3 MB in our runs).
"""
import json
import pathlib
import subprocess
import sys
import tempfile


SLEEP_MAX_MB = 100.0   # bug symptom was hundreds of MB; normal noise << 10 MB
WORKER_MIN_MB = 10.0   # sanity floor for worker attribution when sampling fires


def find_line(lines, needle):
    for line in lines:
        if needle in line["line"]:
            return line
    return None


def run() -> int:
    here = pathlib.Path(__file__).resolve().parent
    workload = here / "issue_659_workload.py"
    if not workload.exists():
        print(f"missing workload file: {workload}")
        return 1

    outdir = pathlib.Path(tempfile.mkdtemp(prefix="scalene"))
    outfile = outdir / "smoketest_659.json"

    cmd = [
        sys.executable,
        "-m",
        "scalene",
        "run",
        "--memory",
        # --profile-all is required on CI runners: without it, the allocator
        # interposer's attribution filter excludes allocations whose nearest
        # Python frame is inside numpy/stdlib, so max_footprint_mb stays 0
        # even though bytes are allocated. test_freethreaded_parity.py on
        # master uses --profile-all for the same reason.
        "--profile-all",
        "-o",
        str(outfile),
        str(workload),
    ]
    print("COMMAND", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, timeout=180)
    stdout = proc.stdout.decode(errors="replace")
    stderr = proc.stderr.decode(errors="replace")
    if proc.returncode != 0:
        print("scalene exited non-zero:", proc.returncode)
        print("STDOUT:", stdout)
        print("STDERR:", stderr)
        return proc.returncode

    try:
        data = json.loads(outfile.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print("failed to read/parse JSON:", exc)
        print("STDOUT:", stdout)
        print("STDERR:", stderr)
        return 1

    files = data.get("files", {})
    alloc_samples = data.get("alloc_samples", 0)
    native_mb = data.get("native_allocations_mb", 0) or 0
    max_footprint_mb = data.get("max_footprint_mb", 0) or 0

    # Per-file roll-up across every memory field. On CI we saw runs where
    # alloc_samples was non-zero but n_malloc_mb was zero on every line of
    # every file — a signal to widen the diagnostic, not just fail.
    def line_totals(lines):
        return {
            "n_malloc_mb": sum((l.get("n_malloc_mb", 0) or 0) for l in lines),
            "n_peak_mb": sum((l.get("n_peak_mb", 0) or 0) for l in lines),
            "n_avg_mb": sum((l.get("n_avg_mb", 0) or 0) for l in lines),
            "n_mallocs": sum((l.get("n_mallocs", 0) or 0) for l in lines),
        }

    print(f"alloc_samples            = {alloc_samples}")
    print(f"native_allocations_mb    = {native_mb:.2f}")
    print(f"max_footprint_mb         = {max_footprint_mb:.2f}")
    print("per-file totals:")
    for fname, info in files.items():
        t = line_totals(info.get("lines", []))
        print(
            f"  {fname}: malloc_mb={t['n_malloc_mb']:.2f} "
            f"peak_mb={t['n_peak_mb']:.2f} avg_mb={t['n_avg_mb']:.2f} "
            f"n_mallocs={t['n_mallocs']}"
        )

    target = None
    for fname, info in files.items():
        if pathlib.PurePath(fname).name == workload.name:
            target = info
            break
    if target is None:
        print("workload file missing from profile; files present:", list(files.keys()))
        return 1

    sleep_line = find_line(target["lines"], "time.sleep(")
    worker_line = find_line(target["lines"], "np.zeros")
    if sleep_line is None or worker_line is None:
        print("could not locate sleep / np.zeros lines in profile")
        print("lines present:", [l["lineno"] for l in target["lines"]])
        return 1

    sleep_mb = sleep_line.get("n_malloc_mb", 0) or 0
    worker_mb = worker_line.get("n_malloc_mb", 0) or 0
    sleep_peak = sleep_line.get("n_peak_mb", 0) or 0
    worker_peak = worker_line.get("n_peak_mb", 0) or 0
    print(
        f"worker np.zeros (line {worker_line['lineno']}) "
        f"malloc_mb={worker_mb:.2f} peak_mb={worker_peak:.2f}"
    )
    print(
        f"main  time.sleep (line {sleep_line['lineno']}) "
        f"malloc_mb={sleep_mb:.2f} peak_mb={sleep_peak:.2f}"
    )

    workload_total_mb = line_totals(target["lines"])["n_malloc_mb"]

    # The regression check for sleep_mb > SLEEP_MAX_MB is unconditional:
    # the bug symptom was hundreds of MB on time.sleep, so if we see that,
    # fail regardless of anything else.
    ok = True
    if sleep_mb > SLEEP_MAX_MB:
        print(
            f"FAIL: main-thread time.sleep attributed {sleep_mb:.2f} MB "
            f"(> {SLEEP_MAX_MB:.0f} MB). Regression of issue #659."
        )
        ok = False

    # If the profiler saw real memory activity (max_footprint_mb reflects
    # actual peak RSS attributable to sampled allocations), then the workload
    # file MUST receive the bulk of the attribution. A previous regression
    # (fixed alongside this test) accidentally excluded the workload via a
    # too-broad "scalene/scalene" path-substring filter in TraceConfig, and
    # all ~1280 MB of worker allocations ended up on threading.py with
    # max_footprint_mb still showing ~272 MB. Catch that shape: footprint
    # grew, but the workload file got nothing.
    if max_footprint_mb >= WORKER_MIN_MB and workload_total_mb < WORKER_MIN_MB:
        print(
            f"FAIL: max_footprint_mb={max_footprint_mb:.2f} MB indicates the "
            f"allocator sampler fired, but the workload file received only "
            f"{workload_total_mb:.2f} MB of attribution. Allocations are "
            f"being charged to the wrong file (e.g., threading.py)."
        )
        ok = False

    # The "worker got its share" check only makes sense when the workload
    # file itself received non-trivial attribution. On some runners (seen
    # on Windows) only ~1 sample fires and it lands on a stdlib file like
    # threading.py — meaning the workload code wasn't sampled at all, and
    # there's nothing to validate about intra-file attribution.
    if workload_total_mb >= WORKER_MIN_MB and worker_mb < WORKER_MIN_MB:
        print(
            f"FAIL: workload file saw {workload_total_mb:.2f} MB attributed "
            f"but worker np.zeros got only {worker_mb:.2f} MB — attribution "
            f"appears wrong within the workload."
        )
        ok = False
    elif workload_total_mb < WORKER_MIN_MB:
        print(
            f"NOTE: workload file received only {workload_total_mb:.2f} MB "
            f"of attribution; skipping intra-file attribution check "
            f"(rely on other matrix cells)."
        )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
