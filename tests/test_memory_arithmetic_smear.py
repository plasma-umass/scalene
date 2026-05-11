"""Regression tests: pure-arithmetic hot-loop lines must not receive
phantom C-side memory traffic.

The C++ heap interposer stamps every malloc sample with the leaf
Python frame from ``whereInPython``. When the leaf is a pure-arithmetic
line (``z = z * z``) and the underlying bytes are pure C-side (system
``malloc``, ``python_fraction ≈ 0``) — typically from CPython arena
resizes / GC / scalene's own bookkeeping under the GIL — those bytes
get smeared onto whatever arithmetic line the eval loop happens to be
on. The smear correction in ``scalene_memory_profiler.py`` reattributes
such samples up the captured Python stack to the nearest frame whose
line has a CALL-class opcode.

These tests pin two behaviors:

  1. Pure-arithmetic lines do not accumulate ``n_malloc_mb`` traffic
     comparable to the legitimate allocator lines.
  2. The synchronously-captured ``memory_stacks`` (``--stacks`` is the
     default) still contains the legitimate allocator stack paths —
     the per-line redistribution must not perturb that data.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


FIXTURE = (
    Path(__file__).parent.parent
    / "test"
    / "line_attribution_tests"
    / "arithmetic_smear.py"
)

# Line numbers in ``arithmetic_smear.py``. Keep these in sync if the
# fixture is edited (the assertions below depend on exact lines).
ALLOC_LINES = (30, 31, 32)             # list comps inside do_allocs
ARITH_LINES = (43, 44, 45, 46)         # body of hot_arith — pure float ops
HOT_ARITH_CALL_SITE = 56               # ``hot_arith(x)`` inside run

_SCALENE_TIMEOUT = 180
_SCALENE_ATTEMPTS = 3


def _run_scalene(tmp_path: Path) -> dict:
    """Run Scalene against the fixture with memory + stacks. Same retry
    pattern as ``test_line_attribution_nested.py``: scalene's subprocess
    startup can wedge under CI contention, and short fixtures sometimes
    finish before the first sampling interval. Skip if all attempts
    come back empty."""
    last: subprocess.CompletedProcess | None = None
    for attempt in range(1, _SCALENE_ATTEMPTS + 1):
        out = tmp_path / f"arith_smear_{attempt}.json"
        cmd = [
            sys.executable,
            "-m",
            "scalene",
            "run",
            "--memory",
            "--stacks",
            "--no-browser",
            "-o",
            str(out),
            str(FIXTURE),
        ]
        try:
            last = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=_SCALENE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            continue
        if out.exists() and out.stat().st_size > 0:
            with open(out) as f:
                profile = json.load(f)
            files = profile.get("files", {})
            if any(fname.endswith("arithmetic_smear.py") for fname in files):
                return profile
    pytest.skip(
        f"Scalene produced no usable profile after {_SCALENE_ATTEMPTS} "
        f"attempts. last returncode="
        f"{last.returncode if last else 'timeout'}, "
        f"last stderr={(last.stderr[-400:] if last else '')!r}"
    )


def _fixture_lines(profile: dict) -> list[dict]:
    files = profile.get("files", {})
    matches = [
        f for fname, f in files.items() if fname.endswith("arithmetic_smear.py")
    ]
    assert matches, f"Fixture missing from profile: files={list(files.keys())}"
    return matches[0]["lines"]


def _by_lineno(profile: dict) -> dict[int, dict]:
    return {ln["lineno"]: ln for ln in _fixture_lines(profile)}


def test_arithmetic_lines_have_minimal_malloc_traffic(tmp_path: Path) -> None:
    """The pure-arithmetic body of ``hot_arith`` must not collect
    significant per-line malloc traffic.

    Pre-fix, ``z = z * z`` could accumulate hundreds of MB on a single
    line (the eval loop happens to be on whichever arithmetic line
    when CPython internals fire a raw malloc). Post-fix the smear is
    redirected up the captured stack, and the arithmetic lines stay
    well below the legitimate allocator lines."""
    profile = _run_scalene(tmp_path)
    by_ln = _by_lineno(profile)

    alloc_total = sum(by_ln.get(ln, {}).get("n_malloc_mb", 0.0) for ln in ALLOC_LINES)
    if alloc_total < 50.0:
        pytest.skip(
            f"Fixture allocator lines saw only {alloc_total:.1f} MB total — "
            f"the run was too short for sampling, can't draw conclusions."
        )

    # Each arithmetic line must be far below the allocator-line total.
    # Pre-fix on the equivalent testme.py workload, line 24 sat at ~40%
    # of the file total; the bound here (5%) is well above any residual
    # legitimate pymalloc activity but well below the smear regression.
    cap = 0.05 * alloc_total
    offenders = {
        ln: by_ln.get(ln, {}).get("n_malloc_mb", 0.0)
        for ln in ARITH_LINES
        if by_ln.get(ln, {}).get("n_malloc_mb", 0.0) > cap
    }
    assert not offenders, (
        f"Arithmetic lines collected phantom malloc traffic exceeding "
        f"{cap:.1f} MB (5% of {alloc_total:.1f} MB allocator total): "
        f"{offenders}. Smear-correction in process_malloc_free_samples "
        f"may have regressed."
    )


def test_allocator_lines_still_dominate(tmp_path: Path) -> None:
    """The list-comprehension lines inside ``do_allocs`` must keep
    getting the bulk of byte attribution — the smear fix must not
    over-redirect and steal credit from legitimate allocator lines
    (which carry CALL / BUILD_LIST opcodes)."""
    profile = _run_scalene(tmp_path)
    by_ln = _by_lineno(profile)

    alloc_mb = sum(by_ln.get(ln, {}).get("n_malloc_mb", 0.0) for ln in ALLOC_LINES)
    arith_mb = sum(by_ln.get(ln, {}).get("n_malloc_mb", 0.0) for ln in ARITH_LINES)

    if alloc_mb == 0:
        pytest.skip("No allocator-line samples this run; can't compare.")

    # Allocator total should dominate arithmetic total by at least 5x.
    # On a quiet run arith_mb can be 0, in which case any positive
    # alloc_mb passes; we just want to guard against a regression that
    # accidentally redistributes legitimate credit upstream.
    assert alloc_mb > max(arith_mb * 5, 50.0), (
        f"Allocator lines ({alloc_mb:.1f} MB across {ALLOC_LINES}) should "
        f"dominate over arithmetic lines ({arith_mb:.1f} MB across "
        f"{ARITH_LINES}) by more than 5x and clear 50 MB outright. If the "
        f"ratio is small, the smear correction is either letting through "
        f"too many spurious arithmetic-line credits or the allocator "
        f"lines have lost their attribution."
    )


def test_function_rollup_does_not_smear_onto_arith_function(tmp_path: Path) -> None:
    """The per-function rollup (the table the GUI shows above the
    per-line view) must not credit ``hot_arith`` with allocator traffic.

    ``hot_arith`` is pure float arithmetic — no CALL, no BUILD_*, no
    container/iter opcode anywhere in its body. With the inline smear
    redirect applied in ``process_malloc_free_samples``, every per-line
    memory accumulator inside ``hot_arith`` stays at zero, so the
    function-level sum (which is what the GUI's function-profile table
    renders) is also zero.

    Pre-fix this would show ``hot_arith`` with hundreds of MB of peak
    memory and a sizable usage-fraction pie wedge, matching the visible
    smear on ``doit2`` in the user's original screenshot of testme.py."""
    profile = _run_scalene(tmp_path)
    files = profile.get("files", {})
    matches = [
        f for fname, f in files.items() if fname.endswith("arithmetic_smear.py")
    ]
    assert matches, f"Fixture missing from profile: files={list(files.keys())}"
    fdata = matches[0]

    functions = fdata.get("functions", [])
    by_name: dict[str, dict] = {fn.get("line", "").strip(): fn for fn in functions}

    if "hot_arith" not in by_name:
        pytest.skip(
            "hot_arith function not present in profile (likely no samples "
            "landed inside it this run)."
        )

    hot_arith = by_name["hot_arith"]
    do_allocs = by_name.get("do_allocs", {})

    do_allocs_mb = do_allocs.get("n_malloc_mb", 0.0)
    if do_allocs_mb < 50.0:
        pytest.skip(
            f"do_allocs function only saw {do_allocs_mb:.1f} MB — the run "
            f"was too short for sampling to mean anything."
        )

    hot_arith_mb = hot_arith.get("n_malloc_mb", 0.0)
    hot_arith_peak = hot_arith.get("n_peak_mb", 0.0)
    hot_arith_usage = hot_arith.get("n_usage_fraction", 0.0)

    # The pure-arithmetic function should be effectively zero across
    # all three memory columns. Generous bounds to tolerate any single
    # legitimate pymalloc sample that happens to land here.
    assert hot_arith_mb < 5.0, (
        f"Function ``hot_arith`` accumulated {hot_arith_mb:.1f} MB of "
        f"malloc traffic — pure float arithmetic shouldn't allocate. "
        f"Inline smear redirect in process_malloc_free_samples may have "
        f"regressed."
    )
    assert hot_arith_peak < 50.0, (
        f"Function ``hot_arith`` peak memory is {hot_arith_peak:.1f} MB. "
        f"Pre-fix this column was the most visible smear artifact "
        f"(testme.py showed 810 MB on doit2). Inline redirect must "
        f"also correct memory_max_footprint, not just memory_malloc_samples."
    )
    assert hot_arith_usage < 0.05, (
        f"Function ``hot_arith`` usage fraction is {hot_arith_usage:.3f} "
        f"(should be ~0). The memory-activity pie wedge in the GUI "
        f"is computed from this; a non-zero value means smear is still "
        f"reaching the function-level rollup."
    )


def test_memory_stacks_preserve_full_paths(tmp_path: Path) -> None:
    """The ``--stacks`` memory-flame data must record legitimate full
    Python call paths down to allocator leaves — and *only* those.
    Smear samples must be dropped from ``memory_stacks`` too, not just
    from the per-line accumulators: otherwise the flame chart credits
    bytes along whichever call chain happened to be active when the
    eval loop was on an arithmetic line, putting hot non-allocators
    like ``hot_arith`` on the flame view even though no allocation
    came from anything they did."""
    profile = _run_scalene(tmp_path)
    memory_stacks = profile.get("memory_stacks", [])
    if not memory_stacks:
        pytest.skip(
            "No memory_stacks recorded — sync stack capture unavailable "
            "on this platform / libscalene build."
        )

    fixture_tail = "arithmetic_smear.py"
    seen_alloc_leaf = False
    smear_leaves: list[tuple[int, float]] = []
    for frames, mb in memory_stacks:
        if not frames:
            continue
        leaf = frames[-1]
        if not leaf.get("filename_or_module", "").endswith(fixture_tail):
            continue
        leaf_line = leaf.get("line")
        if leaf_line in ALLOC_LINES:
            seen_alloc_leaf = True
        elif leaf_line in ARITH_LINES:
            smear_leaves.append((leaf_line, mb))

    assert seen_alloc_leaf, (
        f"No memory_stacks entry has its leaf on one of the allocator "
        f"lines {ALLOC_LINES}. Synchronous stack capture appears broken "
        f"for this fixture."
    )
    assert not smear_leaves, (
        f"memory_stacks contains entries whose leaf is on a pure-"
        f"arithmetic line {ARITH_LINES}: {smear_leaves}. The smear "
        f"suppression in process_malloc_free_samples should drop "
        f"these from memory_stacks too — otherwise the flame chart "
        f"credits bytes to whatever call chain was incidentally active "
        f"(not the chain that actually caused the allocation)."
    )
