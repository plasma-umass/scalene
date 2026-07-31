"""Regression test for a divide-by-zero found by the Lean formalization.

Same bug class as `test_leak_velocity_zero_elapsed.py` (see
formal/README.md "Bugs the formalization found"): an unguarded denominator
whose zero-ness the surrounding invariants don't rule out.

The stacks-normalization loop in `ScaleneJSON.output_profiles` divided each
recorded stack's timings by `stats.cpu_stats.total_cpu_samples`:

    for stk in list(stats.stacks):
        stats.stacks[stk] = StackStats(
            stack_stats.count,
            stack_stats.python_time / stats.cpu_stats.total_cpu_samples,
            ...

with no guard. `total_cpu_samples` can be 0 while `stats.stacks` is non-empty:
a **memory-only run with `--stacks`** records stack entries (from the CPU
sampler's stack collection) while memory activity — not CPU activity — is what
passes the "nothing to output" gate at the top of `output_profiles`. With no
CPU sample ever recorded, `total_cpu_samples` stays at its initial `0.0`, and
the loop raises `ZeroDivisionError`. The sibling per-file / per-line
normalizations (guarded by `if stats.cpu_stats.total_cpu_samples:` and a
try/except) already handled this; this site was missed.

This test drives the *full* `output_profiles` path (it reaches the buggy loop),
so it genuinely crashes on the pre-fix code and passes after the guard.
"""

from pathlib import Path

from scalene.scalene_json import ScaleneJSON
from scalene.scalene_statistics import (
    Filename,
    LineNumber,
    ScaleneStatistics,
    StackStats,
)


def _memory_only_stats_with_stacks() -> ScaleneStatistics:
    """A stats object as produced by a memory-only run with --stacks: memory
    samples recorded, a stack recorded, but no CPU sample (total_cpu_samples
    still 0.0)."""
    stats = ScaleneStatistics()
    fname = Filename("prog.py")
    lineno = LineNumber(10)
    # Memory activity: passes the "nothing to output" gate in output_profiles.
    stats.memory_stats.total_memory_malloc_samples = 5.0
    stats.memory_stats.memory_malloc_samples[fname][lineno] = 5.0
    stats.memory_stats.memory_malloc_count[fname][lineno] = 1
    # A stack was recorded by the CPU sampler's --stacks collection...
    stats.stacks[((fname, "func", lineno),)] = StackStats(1, 0.5, 0.5, 1.0)
    # ...but no CPU sample fired, so the normalization denominator is 0.
    assert stats.cpu_stats.total_cpu_samples == 0.0
    assert stats.stacks
    return stats


def test_output_profiles_no_divide_by_zero_with_stacks_and_zero_cpu():
    """output_profiles must not raise ZeroDivisionError when stacks are present
    but total_cpu_samples is 0 (memory-only run with --stacks)."""
    stats = _memory_only_stats_with_stacks()
    j = ScaleneJSON()
    # Would raise ZeroDivisionError at scalene_json.py:779 before the fix.
    result = j.output_profiles(
        Filename("prog.py"),
        stats,
        1234,
        lambda f, l: True,
        Path("/tmp"),
        Filename("prog.py"),
        Filename("prog.py"),
        [],
        profile_memory=True,
        reduced_profile=False,
    )
    assert isinstance(result, dict)
    assert result  # non-empty: memory activity produces output


def test_stacks_left_unnormalized_when_no_cpu_samples():
    """When total_cpu_samples is 0 the raw stack entry is preserved rather than
    normalized (the correct fallback: you can't normalize by zero total)."""
    stats = _memory_only_stats_with_stacks()
    key = ((Filename("prog.py"), "func", LineNumber(10)),)
    before = stats.stacks[key]
    j = ScaleneJSON()
    j.output_profiles(
        Filename("prog.py"),
        stats,
        1234,
        lambda f, l: True,
        Path("/tmp"),
        Filename("prog.py"),
        Filename("prog.py"),
        [],
        profile_memory=True,
        reduced_profile=False,
    )
    after = stats.stacks[key]
    # Unchanged: timings not divided by zero, count preserved.
    assert after.count == before.count
    assert after.python_time == before.python_time
    assert after.c_time == before.c_time


def test_output_profiles_normalizes_stacks_when_cpu_samples_present():
    """Sanity: with CPU samples present the loop still runs and normalizes."""
    stats = _memory_only_stats_with_stacks()
    stats.cpu_stats.total_cpu_samples = 2.0
    key = ((Filename("prog.py"), "func", LineNumber(10)),)
    j = ScaleneJSON()
    j.output_profiles(
        Filename("prog.py"),
        stats,
        1234,
        lambda f, l: True,
        Path("/tmp"),
        Filename("prog.py"),
        Filename("prog.py"),
        [],
        profile_memory=True,
        reduced_profile=False,
    )
    after = stats.stacks[key]
    # 0.5 python_time / 2.0 total = 0.25, etc.
    assert after.python_time == 0.25
    assert after.c_time == 0.25
    assert after.cpu_samples == 0.5
