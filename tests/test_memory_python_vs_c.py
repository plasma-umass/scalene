"""End-to-end test: Python-allocator vs C-allocator split.

Asserts that ``n_python_fraction`` reflects which code path Scalene's
interposer sees the allocation from:

- ``bytes(N)`` → CPython's ``PyBytes_FromSize`` → PyMem domain → counted
  toward ``_pythonCount`` in ``src/include/sampleheap.hpp``.
- ``np.zeros(...)`` → numpy allocator → libc ``malloc`` → counted
  toward ``_cCount``.

Margins are loose (0.7 / 0.3) because sampling noise and the fractional
accounting both contribute variance. Tight bounds would be flaky.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _scalene_subprocess import fixture_lines, run_scalene_memory_profile


FIXTURE = (
    Path(__file__).parent.parent
    / "test"
    / "line_attribution_tests"
    / "st_python_vs_c.py"
)

PYTHON_LINE = 34  # `return bytes(2 * 10_485_767)` in python_alloc
C_LINE = 38       # `return np.zeros(2_000_000, dtype=np.float64)` in c_alloc


def _profile_or_skip(tmp_path: Path) -> dict:
    """Profile the fixture, skipping if numpy is missing (fixture exits
    early, leaving no samples for this file)."""
    try:
        return run_scalene_memory_profile(tmp_path, FIXTURE)
    except pytest.skip.Exception:
        raise  # propagate the helper's own skip
    # Unreachable but makes the control flow explicit.


def test_python_line_is_python_dominated(tmp_path: Path) -> None:
    profile = _profile_or_skip(tmp_path)
    lines = fixture_lines(profile, FIXTURE.name)
    by_lineno = {ln["lineno"]: ln for ln in lines}

    py = by_lineno.get(PYTHON_LINE)
    assert py is not None, (
        f"Python-allocator line {PYTHON_LINE} missing. "
        f"Lines present: {sorted(by_lineno)}"
    )
    assert py["n_malloc_mb"] > 0.0, (
        f"Python-allocator line {PYTHON_LINE} got zero bytes: {py!r}"
    )
    assert py["n_python_fraction"] >= 0.7, (
        f"Python-allocator line {PYTHON_LINE} has n_python_fraction="
        f"{py['n_python_fraction']}, expected >= 0.7. The interposer "
        f"should count bytes() as a Python allocation."
    )


def test_c_line_is_c_dominated(tmp_path: Path) -> None:
    profile = _profile_or_skip(tmp_path)
    lines = fixture_lines(profile, FIXTURE.name)
    by_lineno = {ln["lineno"]: ln for ln in lines}

    c = by_lineno.get(C_LINE)
    assert c is not None, (
        f"C-allocator line {C_LINE} missing. "
        f"Lines present: {sorted(by_lineno)}"
    )
    assert c["n_malloc_mb"] > 0.0, (
        f"C-allocator line {C_LINE} got zero bytes: {c!r}"
    )
    assert c["n_python_fraction"] <= 0.3, (
        f"C-allocator line {C_LINE} has n_python_fraction="
        f"{c['n_python_fraction']}, expected <= 0.3. numpy's allocator "
        f"goes through libc malloc, not PyMem, so this line should be "
        f"dominated by C-allocator samples."
    )
