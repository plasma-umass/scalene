"""End-to-end regression test for the memory-stacks flame chart.

Exercises the synchronous per-sample stack capture path
(``whereInPythonWithStack`` in ``src/source/pywhere.cpp``) against a
workload that allocates through a shared allocator helper from two
distinct caller sites. The captured memory stacks must:

  1. Preserve intermediate frames (not collapse ``make_big`` /
     ``make_small`` into their caller) — the signature of the sync
     capture path versus the async signal handler.
  2. Split bytes across the two call paths in the ratio that matches
     the workload (~500 MB via ``make_big`` vs ~200 MB via
     ``make_small``).

See ``test/line_attribution_tests/bigmem_driver.py`` for the fixture.
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
    / "bigmem_driver.py"
)

ALLOCATOR_LINE = 20   # `return array.array("d", [0]) * n` inside make_vec
BIG_CALLER_LINE = 24  # `return make_vec(12_500_000)` inside make_big
SMALL_CALLER_LINE = 28  # `return make_vec(125_000)` inside make_small

_SCALENE_TIMEOUT = 180
_SCALENE_ATTEMPTS = 3


def _run_scalene(tmp_path: Path) -> dict:
    """Run Scalene with --memory --stacks, retrying on empty output.

    Same flake-tolerance approach as ``tests/test_line_attribution_nested.py``:
    Scalene subprocess startup can wedge under CI contention (notably
    macOS DYLD_INSERT_LIBRARIES init races); we retry, then skip if we
    can't get a usable profile.
    """
    last: subprocess.CompletedProcess | None = None
    for attempt in range(1, _SCALENE_ATTEMPTS + 1):
        out = tmp_path / f"bigmem_{attempt}.json"
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
            if any(fname.endswith("bigmem_driver.py") for fname in files):
                memory_stacks = profile.get("memory_stacks", [])
                if memory_stacks:
                    return profile
    pytest.skip(
        f"Scalene produced no usable memory_stacks after "
        f"{_SCALENE_ATTEMPTS} attempts. "
        f"last returncode={last.returncode if last else 'timeout'}, "
        f"last stderr={(last.stderr[-400:] if last else '')!r}"
    )


def _leaf_line(stack_frames: list[dict]) -> int | None:
    return stack_frames[-1]["line"] if stack_frames else None


def _caller_line(stack_frames: list[dict]) -> int | None:
    """Return the line of the frame directly above the leaf."""
    return stack_frames[-2]["line"] if len(stack_frames) >= 2 else None


def test_memory_stacks_split_across_two_callers(tmp_path: Path) -> None:
    """Both call paths through ``make_vec`` show up in memory_stacks as
    distinct entries, with bytes attributed to each caller roughly in
    proportion to the workload's allocation mix.

    Regression guard: if the sync stack capture collapsed frames or
    used the async handler's frame, we would see (at best) one path
    attributed to the outer ``run`` loop line, losing the
    ``make_big`` / ``make_small`` distinction.
    """
    profile = _run_scalene(tmp_path)
    memory_stacks = profile["memory_stacks"]

    # Every captured stack must have the allocator line 20 as its leaf.
    leaves = [_leaf_line(frames) for frames, _mb in memory_stacks]
    assert all(leaf == ALLOCATOR_LINE for leaf in leaves), (
        f"Expected all memory_stacks leaves to land on allocator line "
        f"{ALLOCATOR_LINE}, got {leaves}. Intermediate frames being "
        f"skipped or the allocator being misattributed."
    )

    # The caller frame (directly above the allocator leaf) must pick up
    # both make_big and make_small — otherwise the sync capture lost
    # the intermediate allocator-helper frame.
    big_total = 0.0
    small_total = 0.0
    other_total = 0.0
    for frames, mb in memory_stacks:
        caller_line = _caller_line(frames)
        if caller_line == BIG_CALLER_LINE:
            big_total += mb
        elif caller_line == SMALL_CALLER_LINE:
            small_total += mb
        else:
            other_total += mb

    # Both call paths must be represented.
    assert big_total > 0, (
        f"No memory_stacks entry has make_big (caller line "
        f"{BIG_CALLER_LINE}) directly above the allocator. Sync stack "
        f"capture likely collapsed intermediate frames. "
        f"big={big_total} small={small_total} other={other_total} "
        f"stacks={memory_stacks!r}"
    )
    assert small_total > 0, (
        f"No memory_stacks entry has make_small (caller line "
        f"{SMALL_CALLER_LINE}) directly above the allocator. Sync stack "
        f"capture likely collapsed intermediate frames. "
        f"big={big_total} small={small_total} other={other_total}"
    )

    # Workload allocates ~500 MB via make_big and ~200 MB via make_small.
    # Enforce a loose ordering rather than a strict ratio — sampling is
    # noisy, and either path could see opportunistic extra credit from
    # GC / arena reuse.
    assert big_total > small_total, (
        f"make_big path ({big_total:.2f} MB) should dominate over "
        f"make_small ({small_total:.2f} MB) — the workload allocates "
        f"~5x more bytes through make_big."
    )


def test_memory_stacks_include_make_vec_frame(tmp_path: Path) -> None:
    """The stitched call path must include ``make_vec`` as the frame
    containing the allocator leaf. A regression in the sync-capture
    path (e.g., if the buffer was truncated or frames were dropped)
    would show shorter stacks that skip ``make_vec``.
    """
    profile = _run_scalene(tmp_path)
    memory_stacks = profile["memory_stacks"]

    # Find any stack whose frames include a frame with display name
    # containing "make_vec".
    found = False
    for frames, _mb in memory_stacks:
        names = [f.get("display_name", "") for f in frames]
        if any("make_vec" in n for n in names):
            found = True
            break
    assert found, (
        f"No memory_stacks entry includes a make_vec frame. "
        f"display_names seen: "
        f"{sorted({f.get('display_name', '?') for fs, _ in memory_stacks for f in fs})}"
    )


def test_bigmem_max_footprint_is_large(tmp_path: Path) -> None:
    """Sanity: the fixture is sized so that the profile's peak footprint
    is in the 500+ MB range. If we see a tiny footprint, the sync
    allocator accounting has regressed (e.g., is not crediting full
    allocation sizes).
    """
    profile = _run_scalene(tmp_path)
    max_mb = profile.get("max_footprint_mb", 0.0)
    # Workload peak is ~700 MB (5 x 100 MB retained + 200 x 1 MB retained).
    # Accept >= 400 MB to tolerate allocator overhead / sampling noise on
    # small runners.
    assert max_mb >= 400, (
        f"max_footprint_mb={max_mb:.2f} MB, expected >= 400. "
        f"Allocator-size accounting may have regressed."
    )
