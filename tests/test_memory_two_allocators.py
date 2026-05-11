"""End-to-end test: two allocator functions with different byte sizes.

Asserts proportional per-line byte attribution. The synchronous
``whereInPythonWithStack`` capture in the C++ interposer stamps each
sample's ``(filename, lineno)`` before the async signal fires, so
``n_malloc_mb`` on each allocator line should track the allocator's
true per-call size regardless of signal-handler timing.

We assert on ``n_malloc_mb`` only — never ``n_mallocs``, which is
driven by the async handler's (potentially stale) view of
``__last_profiled`` and is known unreliable across platforms (see the
FIXME at ``src/source/pywhere.cpp:911-912``).
"""

from __future__ import annotations

from pathlib import Path

from _scalene_subprocess import fixture_lines, run_scalene_memory_profile


FIXTURE = (
    Path(__file__).parent.parent
    / "test"
    / "line_attribution_tests"
    / "st_two_allocators.py"
)

SMALL_LINE = 28  # `return array.array("d", [0]) * 150_000` in small_alloc
BIG_LINE = 32    # `return array.array("d", [0]) * 600_000` in big_alloc


def test_both_allocators_have_nonzero_bytes(tmp_path: Path) -> None:
    """Neither allocator line may come back with zero byte attribution."""
    profile = run_scalene_memory_profile(tmp_path, FIXTURE)
    lines = fixture_lines(profile, FIXTURE.name)
    by_lineno = {ln["lineno"]: ln for ln in lines}

    small = by_lineno.get(SMALL_LINE)
    big = by_lineno.get(BIG_LINE)
    assert small is not None, (
        f"Small allocator line {SMALL_LINE} missing. Lines present: {sorted(by_lineno)}"
    )
    assert big is not None, (
        f"Big allocator line {BIG_LINE} missing. Lines present: {sorted(by_lineno)}"
    )
    assert small["n_malloc_mb"] > 0.0, (
        f"Small allocator line {SMALL_LINE} got zero bytes: {small!r}"
    )
    assert big["n_malloc_mb"] > 0.0, (
        f"Big allocator line {BIG_LINE} got zero bytes: {big!r}"
    )


def test_big_dominates_small(tmp_path: Path) -> None:
    """BIG_LINE allocates ~4x more per call than SMALL_LINE. Assert at
    least 2x, loose enough to absorb sampling noise on a 1 MB window.
    """
    profile = run_scalene_memory_profile(tmp_path, FIXTURE)
    lines = fixture_lines(profile, FIXTURE.name)
    by_lineno = {ln["lineno"]: ln for ln in lines}

    small_mb = by_lineno[SMALL_LINE]["n_malloc_mb"]
    big_mb = by_lineno[BIG_LINE]["n_malloc_mb"]
    assert big_mb >= 2.0 * small_mb, (
        f"BIG line {BIG_LINE} got {big_mb} MB; SMALL line {SMALL_LINE} "
        f"got {small_mb} MB. Expected BIG >= 2 * SMALL (true ratio ~4x)."
    )


def test_no_other_line_outweighs_big(tmp_path: Path) -> None:
    """Nothing in the fixture should outweigh the biggest allocator.

    If some caller line (the loop body, ``run()``) ends up with more
    bytes than ``big_alloc()``, the synchronous stamp is leaking into
    the caller frame — the regression mode this whole family guards
    against.
    """
    profile = run_scalene_memory_profile(tmp_path, FIXTURE)
    lines = fixture_lines(profile, FIXTURE.name)
    by_lineno = {ln["lineno"]: ln for ln in lines}
    big_mb = by_lineno[BIG_LINE]["n_malloc_mb"]

    for ln in lines:
        if ln["lineno"] == BIG_LINE:
            continue
        other = ln["n_malloc_mb"]
        assert other <= big_mb, (
            f"Line {ln['lineno']} got {other} MB — more than the BIG "
            f"allocator's {big_mb} MB on line {BIG_LINE}. Attribution "
            f"has smeared onto a non-allocator line."
        )
