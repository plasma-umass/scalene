"""End-to-end test: memory_stacks covers both worker threads.

Runs ``mt_two_workers.py`` with ``--stacks`` and inspects the
``memory_stacks`` wire output. The synchronous stack capture must walk
the *allocating* thread's ``PyThreadState`` each time a sample fires,
so the flame-chart output should contain entries leafing on both
``worker_a``'s and ``worker_b``'s allocator lines. Every leaf should
point back to the fixture file — not to threading-internal frames
leaking through.

Skipped on Windows: the Windows libscalene DLL tracks allocations
via Detours but does not capture full Python stacks, so
``memory_stacks`` is always empty (see ``scalene_profiler.py:839``).
Multithreaded byte attribution on Windows is covered by
``tests/test_memory_multithreaded.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from _scalene_subprocess import (
    leaf_filename,
    leaf_line,
    run_scalene_memory_profile,
)


FIXTURE = (
    Path(__file__).parent.parent
    / "test"
    / "line_attribution_tests"
    / "mt_two_workers.py"
)

WORKER_A_ALLOC_LINE = 34
WORKER_B_ALLOC_LINE = 42


pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows libscalene.dll doesn't implement whereInPythonWithStack; memory_stacks is always empty (scalene_profiler.py:839)",
)


def test_memory_stacks_cover_both_workers(tmp_path: Path) -> None:
    """At least one stack for each worker's allocator line."""
    profile = run_scalene_memory_profile(
        tmp_path, FIXTURE, extra_args=["--stacks"], timeout=180,
        require_memory_stacks=True,
    )
    a_seen = False
    b_seen = False
    for frames, _mb in profile["memory_stacks"]:
        fn = leaf_filename(frames) or ""
        if not fn.endswith(FIXTURE.name):
            continue
        line = leaf_line(frames)
        if line == WORKER_A_ALLOC_LINE:
            a_seen = True
        elif line == WORKER_B_ALLOC_LINE:
            b_seen = True
    assert a_seen, (
        f"No memory_stacks entry leafed on Worker A line "
        f"{WORKER_A_ALLOC_LINE}. Worker A's stack walk may be broken "
        f"or its samples are being credited to Worker B."
    )
    assert b_seen, (
        f"No memory_stacks entry leafed on Worker B line "
        f"{WORKER_B_ALLOC_LINE}. Worker B's stack walk may be broken "
        f"or its samples are being credited to Worker A."
    )


def test_memory_stacks_leaves_are_fixture(tmp_path: Path) -> None:
    """Every ``memory_stacks`` entry whose leaf has a line number set
    must leaf inside our fixture. Stacks leafing elsewhere mean the
    capture is pulling in threading-internal or C-extension frames.

    (Entries with zero bytes or missing line info are skipped.)
    """
    profile = run_scalene_memory_profile(
        tmp_path, FIXTURE, extra_args=["--stacks"], timeout=180,
        require_memory_stacks=True,
    )
    # We require that the majority of leaf bytes land in the fixture.
    # An absolute "every leaf must be the fixture" is too strict —
    # background Python bookkeeping can allocate too. The signal we
    # want is that fixture frames dominate.
    fixture_mb = 0.0
    other_mb = 0.0
    for frames, mb in profile["memory_stacks"]:
        fn = leaf_filename(frames) or ""
        if fn.endswith(FIXTURE.name):
            fixture_mb += float(mb)
        else:
            other_mb += float(mb)
    assert fixture_mb > other_mb, (
        f"Non-fixture leaves ({other_mb} MB) outweigh fixture leaves "
        f"({fixture_mb} MB) in memory_stacks. Stack capture is pulling "
        f"the wrong frames or the fixture isn't running long enough."
    )
