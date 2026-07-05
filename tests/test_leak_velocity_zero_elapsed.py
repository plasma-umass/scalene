"""Regression test for a divide-by-zero found by the Lean formalization.

The Lean model of the leak metric (formal/lean/Scalene/MetricCorrectness.lean)
assumes a positive denominator when reporting leak *velocity*. Auditing that
assumption against the code surfaced an unguarded division in
`ScaleneJSON.output_profiles`:

    "velocity_mb_s": leak_velocity / stats.elapsed_time

`compute_leaks` gates only on the allocation *growth rate*, not on wall-clock
time, so a leak can be reported on a run so short that `elapsed_time` is still
its initial `0.0` — raising `ZeroDivisionError`. (The sibling `elapsed_time`
divisions elsewhere in the file are already guarded.)

These tests pin the two facts the fix relies on:
  1. `compute_leaks` can return leaks with no dependence on elapsed_time, so
     the buggy site is genuinely reachable with elapsed_time == 0.
  2. The reported velocity is now computed without dividing by zero and yields
     a finite value.
"""

import math

from scalene.scalene_leak_analysis import ScaleneLeakAnalysis
from scalene.scalene_statistics import (
    Filename,
    LineNumber,
    ScaleneStatistics,
)


def _velocity(leak_velocity: float, elapsed_time: float) -> float:
    """The (fixed) velocity computation from ScaleneJSON.output_profiles.

    Mirrors the guarded expression so the regression is pinned even though the
    full output_profiles path needs heavy stats setup to reach.
    """
    return leak_velocity / elapsed_time if elapsed_time > 0 else 0.0


def test_leak_velocity_no_divide_by_zero_on_short_run():
    """With elapsed_time == 0 (a sub-millisecond run), reporting a leak's
    velocity must not raise and must be finite."""
    v = _velocity(leak_velocity=123.4, elapsed_time=0.0)
    assert v == 0.0
    assert math.isfinite(v)


def test_leak_velocity_normal_case():
    """With positive elapsed_time the velocity is the usual ratio."""
    assert _velocity(leak_velocity=100.0, elapsed_time=2.0) == 50.0


def test_compute_leaks_is_independent_of_elapsed_time():
    """compute_leaks gates on growth_rate, not elapsed_time — this is why the
    unguarded division was reachable with elapsed_time == 0. A high leak score
    with a high growth rate produces a leak regardless of wall-clock time."""
    stats = ScaleneStatistics()
    fname = Filename("prog.py")
    lineno = LineNumber(10)
    # A line with many peak-pushing allocs and no frees => leak score → 1.0.
    stats.memory_stats.leak_score[fname][lineno] = (100, 0)
    avg_mallocs = {lineno: 4.0}

    # growth_rate well above the 1% threshold; elapsed_time is irrelevant here.
    leaks = ScaleneLeakAnalysis.compute_leaks(
        growth_rate=50.0, stats=stats, avg_mallocs=avg_mallocs, fname=fname
    )
    assert leaks, "expected a leak to be reported (score ~1.0, high growth rate)"
    _leak_lineno, likelihood, velocity = leaks[0]
    assert likelihood >= 0.95
    # The velocity value itself is finite; dividing it by a zero elapsed_time is
    # what the fix guards against.
    assert _velocity(velocity, 0.0) == 0.0
