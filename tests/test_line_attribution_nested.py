"""Regression test: memory attribution for short-lived allocator
functions called from a hot caller.

Python signal delivery is asynchronous. The SIGXCPU handler that
Scalene uses for malloc sampling runs at the next bytecode boundary,
which means a short allocator frame may have already returned by then
— its ``f_lineno`` points at the caller. The fix is to stamp the
sample synchronously in C++ (``whereInPythonWithStack`` in
``src/source/pywhere.cpp``), and to publish that leaf into
``Scalene.__last_profiled`` before the signal even fires.

This test pins that behavior down: when we call a tiny allocator from
a tight loop, the per-line malloc count must land on the allocator's
line, not the caller's.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


FIXTURE = (
    Path(__file__).parent.parent / "test" / "line_attribution_tests" / "nested_allocator.py"
)

ALLOCATOR_LINE = 24  # `return array.array("d", [0]) * 200_000` inside allocate_one
CALLER_LINE = 44     # `held.append(allocate_one())` inside run


_SCALENE_TIMEOUT = 120
_SCALENE_ATTEMPTS = 3


def _run_scalene(tmp_path: Path, extra: list[str] | None = None) -> dict:
    """Run Scalene against the fixture, retrying on empty output.

    Same two flake modes as test/test_tracer.py's subprocess runner:
      - scalene hangs during startup (DYLD_INSERT_LIBRARIES / sys.monitoring
        init can wedge on loaded CI runners). We time out and retry.
      - scalene runs but writes no samples (fixture finished before a single
        sampling interval). We retry; if all attempts come back empty, skip.
    """
    extra = list(extra or [])
    last_result: subprocess.CompletedProcess | None = None
    for attempt in range(1, _SCALENE_ATTEMPTS + 1):
        out = tmp_path / f"nested_allocator_{attempt}.json"
        cmd = [
            sys.executable,
            "-m",
            "scalene",
            "run",
            "--memory",
            "--no-browser",
            "-o",
            str(out),
            *extra,
            str(FIXTURE),
        ]
        try:
            last_result = subprocess.run(
                cmd, check=False, capture_output=True, text=True,
                timeout=_SCALENE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            continue
        if out.exists() and out.stat().st_size > 0:
            with open(out) as f:
                profile = json.load(f)
            # Accept only if the profile actually captured the fixture.
            files = profile.get("files", {})
            if any(fname.endswith("nested_allocator.py") for fname in files):
                return profile
            # Empty or missing-fixture profile; try again.
    pytest.skip(
        f"Scalene produced no usable profile after {_SCALENE_ATTEMPTS} "
        f"attempts (suspected subprocess startup flake). "
        f"last returncode={last_result.returncode if last_result else 'timeout'}, "
        f"last stderr={(last_result.stderr[-400:] if last_result else '')!r}"
    )


def _fixture_lines(profile: dict) -> list[dict]:
    """Return the per-line records for the fixture. _run_scalene only
    returns profiles where the fixture is present, so this shouldn't
    fire in practice — but keep the guard for robustness."""
    files = profile.get("files", {})
    matches = [
        fdata for fname, fdata in files.items() if fname.endswith("nested_allocator.py")
    ]
    assert matches, f"Fixture missing from profile: files={list(files.keys())}"
    return matches[0]["lines"]


def test_mallocs_credited_to_allocator_not_caller(tmp_path: Path) -> None:
    """The allocator line must get the mallocs; everything else must not.

    When the async-signal handler runs, the short-lived allocator frame
    has usually already returned, so ``frame.f_lineno`` points at some
    non-allocator line (could be the direct caller, could be some
    further-along line depending on what's executing at handler-fire
    time). We assert that malloc counts land on the allocator and are
    NOT scattered across other lines.
    """
    profile = _run_scalene(tmp_path)
    lines = _fixture_lines(profile)
    by_lineno = {ln["lineno"]: ln for ln in lines}

    allocator = by_lineno.get(ALLOCATOR_LINE)
    assert allocator is not None, (
        f"Allocator line {ALLOCATOR_LINE} missing from profile. "
        f"Lines present: {sorted(by_lineno)}"
    )
    alloc_mallocs = allocator.get("n_mallocs", 0)
    alloc_mb = allocator.get("n_malloc_mb", 0.0)

    # Allocator line must have real sample activity.
    assert alloc_mallocs >= 1, (
        f"Expected allocator line {ALLOCATOR_LINE} to have n_mallocs >= 1, "
        f"got {alloc_mallocs}. Full line: {allocator!r}"
    )
    assert alloc_mb > 0.0, (
        f"Expected allocator line {ALLOCATOR_LINE} to have n_malloc_mb > 0, "
        f"got {alloc_mb}."
    )

    # No other line in the fixture should receive meaningful malloc
    # attribution. Historically (pre-fix) these numbers leaked onto
    # whichever line the async handler landed on — sometimes the caller
    # (line 44), sometimes the next-block def (line 27), etc. Any
    # off-allocator line with n_mallocs > alloc_mallocs indicates a
    # regression in the synchronous stack-capture path.
    bad = []
    for ln in lines:
        if ln["lineno"] == ALLOCATOR_LINE:
            continue
        n = ln.get("n_mallocs", 0)
        if n > 1:  # tolerate 1 stray as sampling noise
            bad.append((ln["lineno"], n, ln.get("line", "").strip()[:60]))
    assert not bad, (
        f"Allocator runs at line {ALLOCATOR_LINE} (n_mallocs={alloc_mallocs}), "
        f"but other lines received unexpected malloc attribution: {bad!r}. "
        f"This is the stale-async-handler bug — Scalene.__last_profiled "
        f"should be set synchronously from C++ inside process_malloc, not "
        f"from the deferred Python handler."
    )

    # Bytes: allocator should dominate.
    for ln in lines:
        if ln["lineno"] == ALLOCATOR_LINE:
            continue
        other_mb = ln.get("n_malloc_mb", 0.0)
        assert other_mb <= alloc_mb, (
            f"Line {ln['lineno']} got {other_mb} MB — more than the "
            f"allocator's {alloc_mb} MB on line {ALLOCATOR_LINE}. "
            f"Byte attribution is misdirected."
        )


def test_memory_samples_timeline_only_on_allocator(tmp_path: Path) -> None:
    """The per-line memory sparkline (memory_samples) must only be
    populated on the allocator line. An empty sparkline on a caller
    line is fine; a populated one is the regression.
    """
    profile = _run_scalene(tmp_path)
    lines = _fixture_lines(profile)
    by_lineno = {ln["lineno"]: ln for ln in lines}

    allocator = by_lineno.get(ALLOCATOR_LINE)
    caller = by_lineno.get(CALLER_LINE)
    assert allocator is not None and caller is not None

    alloc_samples = allocator.get("memory_samples", [])
    caller_samples = caller.get("memory_samples", [])

    assert len(alloc_samples) > 0, (
        f"Allocator line {ALLOCATOR_LINE} should have memory_samples, got "
        f"{len(alloc_samples)}. Full line: {allocator!r}"
    )
    assert len(caller_samples) == 0, (
        f"Caller line {CALLER_LINE} must not have a memory timeline, but "
        f"got {len(caller_samples)} samples. That means footprint samples "
        f"are leaking into caller lines — stale async-signal attribution "
        f"regressed."
    )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="--stacks memory flame chart not validated on Windows in this test",
)
def test_memory_stacks_leaf_is_allocator(tmp_path: Path) -> None:
    """When --stacks is enabled, the memory_stacks entries must name the
    allocator's line as the leaf frame."""
    profile = _run_scalene(tmp_path, extra=["--stacks"])
    memory_stacks = profile.get("memory_stacks", [])
    if not memory_stacks:
        pytest.skip(
            "No memory_stacks recorded — sync stack capture unavailable "
            "(libscalene predates whereInPythonWithStack or platform "
            "doesn't load it)."
        )
    # The dominant stack's leaf frame should be the allocator line.
    memory_stacks_sorted = sorted(memory_stacks, key=lambda e: -e[1])
    top_frames, top_mb = memory_stacks_sorted[0]
    assert top_mb > 0.0
    leaf = top_frames[-1]
    assert leaf["line"] == ALLOCATOR_LINE, (
        f"Dominant memory_stacks leaf landed on line {leaf['line']} "
        f"({leaf['display_name']}), expected allocator line "
        f"{ALLOCATOR_LINE}. Full leaf: {leaf!r}"
    )
    assert leaf["filename_or_module"].endswith("nested_allocator.py"), (
        f"Leaf file {leaf['filename_or_module']!r} is not the fixture."
    )
