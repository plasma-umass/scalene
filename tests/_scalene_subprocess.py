"""Shared helper for end-to-end memory-attribution tests.

Runs Scalene as a subprocess against a fixture, retries on empty output,
and skips cleanly if no usable profile ever comes back. Factored out of
``tests/test_line_attribution_nested.py`` and ``tests/test_memory_stacks_bigmem.py``
once a third family of tests started needing the same logic.

Not a test module — pytest ignores files whose basename starts with ``_``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import pytest


def run_scalene_memory_profile(
    tmp_path: Path,
    fixture: Path,
    *,
    extra_args: Optional[List[str]] = None,
    timeout: int = 120,
    attempts: int = 3,
    require_memory_stacks: bool = False,
) -> dict:
    """Profile *fixture* with ``--memory``; return the parsed JSON profile.

    Retries on two known flake modes:
      - Scalene startup wedges (``DYLD_INSERT_LIBRARIES`` / ``sys.monitoring``
        init under CI contention): caught via ``TimeoutExpired``.
      - Scalene runs but writes no samples for the fixture (program finished
        before a sampling interval): detected by the fixture path not being
        present in ``profile["files"]``.

    If ``require_memory_stacks`` is set, an otherwise-valid profile whose
    ``memory_stacks`` is empty is also treated as a failed attempt. Used by
    tests that assert on the synchronous stack-capture output.
    """
    extra = list(extra_args or [])
    fixture_name = fixture.name
    last: Optional[subprocess.CompletedProcess] = None
    for attempt in range(1, attempts + 1):
        out = tmp_path / f"{fixture.stem}_{attempt}.json"
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
            str(fixture),
        ]
        try:
            last = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            continue
        if not (out.exists() and out.stat().st_size > 0):
            continue
        with open(out) as f:
            profile = json.load(f)
        files = profile.get("files", {})
        if not any(fname.endswith(fixture_name) for fname in files):
            continue
        if require_memory_stacks and not profile.get("memory_stacks"):
            continue
        return profile
    pytest.skip(
        f"Scalene produced no usable profile for {fixture_name} after "
        f"{attempts} attempts (suspected subprocess startup flake). "
        f"last returncode={last.returncode if last else 'timeout'}, "
        f"last stderr={(last.stderr[-400:] if last else '')!r}"
    )


def fixture_lines(profile: dict, fixture_basename: str) -> List[dict]:
    """Return the per-line records for the file whose path ends in *fixture_basename*.

    ``run_scalene_memory_profile`` only returns profiles where the fixture is
    present, so the guard here is for misuse (wrong basename) rather than
    flake.
    """
    files = profile.get("files", {})
    matches = [
        fdata for fname, fdata in files.items() if fname.endswith(fixture_basename)
    ]
    assert matches, (
        f"Fixture {fixture_basename!r} missing from profile: "
        f"files={list(files.keys())}"
    )
    return matches[0]["lines"]


def leaf_line(frames: List[dict]) -> Optional[int]:
    """Line number of the innermost (leaf) frame in a ``memory_stacks`` entry."""
    return frames[-1]["line"] if frames else None


def leaf_filename(frames: List[dict]) -> Optional[str]:
    """Filename of the innermost frame."""
    return frames[-1].get("filename_or_module") if frames else None
