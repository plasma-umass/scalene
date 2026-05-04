"""End-to-end test: memory_stacks leaves match the allocator lines (single-threaded).

Runs ``st_two_allocators.py`` with ``--stacks`` and inspects the
``memory_stacks`` wire output (``List[[frames, mb]]`` — see
``scalene/scalene_json.py:376``). The *synchronous* stack capture in
``whereInPythonWithStack`` (``src/source/pywhere.cpp:279-298``) writes
the leaf frame while still inside the allocator function, so the
dominant stack entry grouped by leaf line must land on the allocator
whose bytes it represents.

Skipped on Windows: the Windows build of libscalene is loaded via
Detours + DLL injection (``src/source/libscalene_windows.cpp``) and
supports byte attribution, but does not implement
``whereInPythonWithStack`` — only the leaf frame is captured. As a
result ``scalene_profiler.py:839`` gates ``install_native_stack_unwinder``
on ``sys.platform != "win32"`` and ``memory_stacks`` is always empty
on Windows. Same gate rationale as ``tests/test_line_attribution_nested.py:168-171``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

import pytest

from _scalene_subprocess import leaf_line, run_scalene_memory_profile


FIXTURE = (
    Path(__file__).parent.parent
    / "test"
    / "line_attribution_tests"
    / "st_two_allocators.py"
)

SMALL_LINE = 28
BIG_LINE = 32


pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows libscalene.dll doesn't implement whereInPythonWithStack; memory_stacks is always empty (scalene_profiler.py:839)",
)


def _totals_by_leaf(memory_stacks: List) -> Dict[int, float]:
    """Group memory_stacks entries by leaf line number, summing MB."""
    totals: Dict[int, float] = {}
    for frames, mb in memory_stacks:
        line = leaf_line(frames)
        if line is None:
            continue
        totals[line] = totals.get(line, 0.0) + float(mb)
    return totals


def test_both_allocator_leaves_present(tmp_path: Path) -> None:
    """Every ``memory_stacks`` leaf for our fixture should land on one
    of the two allocator lines — nothing should leaf on the loop body
    in ``run()``."""
    profile = run_scalene_memory_profile(
        tmp_path, FIXTURE, extra_args=["--stacks"], require_memory_stacks=True
    )
    totals = _totals_by_leaf(profile["memory_stacks"])
    assert totals.get(SMALL_LINE, 0.0) > 0.0, (
        f"No memory_stacks entry leafed on small allocator line "
        f"{SMALL_LINE}. Leaf totals: {totals}"
    )
    assert totals.get(BIG_LINE, 0.0) > 0.0, (
        f"No memory_stacks entry leafed on big allocator line "
        f"{BIG_LINE}. Leaf totals: {totals}"
    )


def test_big_leaf_outweighs_small_leaf(tmp_path: Path) -> None:
    """The 4x allocation-size ratio should show up in the stacks view
    (asserted loosely at 1.5x)."""
    profile = run_scalene_memory_profile(
        tmp_path, FIXTURE, extra_args=["--stacks"], require_memory_stacks=True
    )
    totals = _totals_by_leaf(profile["memory_stacks"])
    small = totals.get(SMALL_LINE, 0.0)
    big = totals.get(BIG_LINE, 0.0)
    assert big >= 1.5 * small, (
        f"BIG leaf total ({big} MB) should exceed SMALL leaf total "
        f"({small} MB). Leaf totals: {totals}"
    )
