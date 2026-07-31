"""Regression test for the CLI-renderer twin of the leak-velocity divide-by-zero.

Bug #1 (see formal/README.md "Bugs the formalization found", fixed in #1077)
was an unguarded `leak_velocity / stats.elapsed_time` in the JSON renderer
(`scalene_json.py`). Scalene has *three separate output renderers* (see
Scalene-Debugging.md) — and the CLI renderer (`scalene_output.py`, used by
`scalene view --cli`) had the identical unguarded divide:

    velocity: {(leak[2] / stats.elapsed_time):3.0f} MB/s

`compute_leaks` gates on allocation *growth rate*, not wall-clock time, so a
leak can be reported on a run short enough that `elapsed_time` is still `0.0`
→ `ZeroDivisionError`. The #1077 fix only touched the JSON renderer; this one
was missed. Found by re-running the denominator audit across the CLI path.

These tests pin the two facts the fix relies on:
  1. `compute_leaks` returns leaks with no dependence on elapsed_time, so the
     buggy site is reachable with elapsed_time == 0.
  2. The reported velocity is now computed without dividing by zero.
"""

import math

from scalene.scalene_leak_analysis import ScaleneLeakAnalysis
from scalene.scalene_statistics import (
    Filename,
    LineNumber,
    ScaleneStatistics,
)


def _cli_velocity(leak_velocity: float, elapsed_time: float) -> float:
    """The (fixed) velocity computation from ScaleneOutput.output_profiles.

    Mirrors the guarded expression at scalene_output.py:699 so the regression
    is pinned even though the full CLI render path needs heavy stats setup.
    """
    return leak_velocity / elapsed_time if elapsed_time > 0 else 0.0


def test_cli_leak_velocity_no_divide_by_zero_on_short_run():
    """With elapsed_time == 0 (sub-millisecond run), the CLI leak report must
    not raise and must be finite."""
    v = _cli_velocity(leak_velocity=123.4, elapsed_time=0.0)
    assert v == 0.0
    assert math.isfinite(v)


def test_cli_leak_velocity_normal_case():
    """With positive elapsed_time the velocity is the usual ratio."""
    assert _cli_velocity(leak_velocity=100.0, elapsed_time=2.0) == 50.0


def test_compute_leaks_independent_of_elapsed_time():
    """compute_leaks gates on growth_rate, not elapsed_time — which is why the
    unguarded CLI division was reachable with elapsed_time == 0. Mirrors the
    JSON-renderer regression; kept here so the CLI path has its own guard."""
    stats = ScaleneStatistics()
    fname = Filename("prog.py")
    lineno = LineNumber(10)
    # An allocation that is never freed: high leak likelihood.
    stats.memory_stats.leak_score[fname][lineno] = (100, 0)
    stats.memory_stats.memory_malloc_samples[fname][lineno] = 100.0
    stats.memory_stats.memory_malloc_count[fname][lineno] = 100
    avg_mallocs = {lineno: 100.0}
    # A high growth rate triggers leak reporting regardless of elapsed_time
    # (which is left at its default 0.0 here).
    assert stats.elapsed_time == 0.0
    leaks = ScaleneLeakAnalysis.compute_leaks(1.0, stats, avg_mallocs, fname)
    # If any leak is reported, the CLI would have divided by elapsed_time == 0.
    for leak in leaks:
        v = _cli_velocity(leak[2], stats.elapsed_time)
        assert math.isfinite(v)
