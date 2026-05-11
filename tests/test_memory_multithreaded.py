"""End-to-end test: pure-Python multithreaded memory attribution.

Two worker threads run distinct allocator functions under the GIL.
Per-line byte attribution must:

1. Credit BOTH worker lines (neither thread silently loses samples).
2. Stay roughly balanced (within 10x — true allocation-size ratio is 4x).
3. NOT smear onto the main thread's idle ``sleep``/``join`` lines, which
   is the issue-#857 regression mode in pure-Python form (no GIL
   release — that is covered separately in
   ``test_memory_multithreaded_gil_release.py``).

We assert only on ``n_malloc_mb`` (the synchronous byte-attribution
signal). ``n_mallocs`` is driven by the async handler's ``__last_profiled``
view of a Python frame and is known unreliable across platforms.

Bumped timeout to 180s (same as ``test_memory_stacks_bigmem.py``) because
this fixture launches threads and runs ~3s of allocations.
"""

from __future__ import annotations

from pathlib import Path

from _scalene_subprocess import fixture_lines, run_scalene_memory_profile


FIXTURE = (
    Path(__file__).parent.parent
    / "test"
    / "line_attribution_tests"
    / "mt_two_workers.py"
)

WORKER_A_ALLOC_LINE = 34
WORKER_B_ALLOC_LINE = 42
MAIN_SLEEP_LINE = 52
MAIN_JOIN_LINE = 53


def test_both_worker_allocators_credited(tmp_path: Path) -> None:
    """Both worker allocator lines receive nonzero byte attribution.

    If one thread's samples all land on the other thread's line (or on
    the main thread's line), the stack-walk path is picking the wrong
    ``PyThreadState`` when a sample fires.
    """
    profile = run_scalene_memory_profile(tmp_path, FIXTURE, timeout=180)
    lines = fixture_lines(profile, FIXTURE.name)
    by_lineno = {ln["lineno"]: ln for ln in lines}

    a = by_lineno.get(WORKER_A_ALLOC_LINE)
    b = by_lineno.get(WORKER_B_ALLOC_LINE)
    assert a is not None, (
        f"Worker A allocator line {WORKER_A_ALLOC_LINE} missing. "
        f"Lines present: {sorted(by_lineno)}"
    )
    assert b is not None, (
        f"Worker B allocator line {WORKER_B_ALLOC_LINE} missing. "
        f"Lines present: {sorted(by_lineno)}"
    )
    assert a["n_malloc_mb"] > 0.0, (
        f"Worker A ({WORKER_A_ALLOC_LINE}) got zero bytes: {a!r}"
    )
    assert b["n_malloc_mb"] > 0.0, (
        f"Worker B ({WORKER_B_ALLOC_LINE}) got zero bytes: {b!r}"
    )


def test_workers_balanced_within_10x(tmp_path: Path) -> None:
    """Neither worker should dominate the other by more than 10x.

    True per-call ratio is 4x (Worker B allocates 4x bigger blocks).
    10x is intentionally loose: one thread getting *no* samples at all
    is the regression we want to catch, not a 2x ratio drift.
    """
    profile = run_scalene_memory_profile(tmp_path, FIXTURE, timeout=180)
    lines = fixture_lines(profile, FIXTURE.name)
    by_lineno = {ln["lineno"]: ln for ln in lines}

    a_mb = by_lineno[WORKER_A_ALLOC_LINE]["n_malloc_mb"]
    b_mb = by_lineno[WORKER_B_ALLOC_LINE]["n_malloc_mb"]
    hi, lo = max(a_mb, b_mb), min(a_mb, b_mb)
    # Floor the denominator so a near-zero worker trips the assertion
    # rather than silently passing on a division-by-zero escape hatch.
    assert hi <= 10.0 * max(lo, 0.1), (
        f"Workers unbalanced: A={a_mb} MB, B={b_mb} MB. Ratio {hi/max(lo, 1e-9):.1f}x "
        f"exceeds 10x tolerance. One thread's samples may be getting "
        f"funneled into the other thread's line."
    )


def test_main_thread_not_charged_with_worker_bytes(tmp_path: Path) -> None:
    """``time.sleep`` and ``t.join()`` on the main thread must not be
    charged with worker allocations.

    This is the pure-Python form of issue #857: the main thread is
    blocked in a C function (sleep/join) holding no allocating frames,
    so the synchronous stack capture firing from inside a worker must
    walk the worker's ``PyThreadState``, not the main thread's.
    """
    profile = run_scalene_memory_profile(tmp_path, FIXTURE, timeout=180)
    lines = fixture_lines(profile, FIXTURE.name)
    by_lineno = {ln["lineno"]: ln for ln in lines}

    a_mb = by_lineno[WORKER_A_ALLOC_LINE]["n_malloc_mb"]
    b_mb = by_lineno[WORKER_B_ALLOC_LINE]["n_malloc_mb"]
    min_worker = min(a_mb, b_mb)

    main_sleep_mb = by_lineno.get(MAIN_SLEEP_LINE, {}).get("n_malloc_mb", 0.0)
    main_join_mb = by_lineno.get(MAIN_JOIN_LINE, {}).get("n_malloc_mb", 0.0)
    main_idle_mb = main_sleep_mb + main_join_mb

    assert main_idle_mb <= 0.1 * min_worker, (
        f"Main-thread idle lines got {main_idle_mb} MB (sleep="
        f"{main_sleep_mb}, join={main_join_mb}); worker minimum is "
        f"{min_worker} MB. Worker allocations appear to be smearing "
        f"onto the main thread's idle frames."
    )
