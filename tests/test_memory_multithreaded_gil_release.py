"""End-to-end test: issue #857 regression — GIL-releasing worker allocations.

Fixture ``mt_gil_release_worker.py`` has a worker thread calling
``np.zeros((1024, 1024))``. OpenBLAS/MKL typically release the GIL
around large numpy allocations, which historically made the sampled
bytes land on the *main* thread's idle ``time.sleep`` line (the main
thread holds the GIL during sleep). The synchronous stack capture in
``whereInPythonWithStack`` must walk the *allocating* thread's
``PyThreadState``, not whichever thread happens to hold the GIL.

Skipped if numpy isn't available — the fixture exits early, leaving
no samples; the subprocess helper skips on missing-fixture profiles.

The ``--stacks``-based variant is additionally skipped on Windows:
``libscalene.dll`` intercepts allocations via Detours and records
leaf ``(filename, lineno)`` correctly, but does not implement
``whereInPythonWithStack``, so ``memory_stacks`` is always empty
(see ``scalene_profiler.py:839``). The byte-attribution variant
(``test_worker_alloc_outweighs_main_sleep``) runs on Windows.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from _scalene_subprocess import (
    fixture_lines,
    leaf_filename,
    leaf_line,
    run_scalene_memory_profile,
)


FIXTURE = (
    Path(__file__).parent.parent
    / "test"
    / "line_attribution_tests"
    / "mt_gil_release_worker.py"
)

WORKER_ALLOC_LINE = 26
MAIN_SLEEP_LINE = 34


def test_worker_alloc_outweighs_main_sleep(tmp_path: Path) -> None:
    """Worker line must dominate the main-thread idle line by >= 10x.

    Regression this pins: if the stack-walk uses the GIL-holder's
    frames instead of the allocator's thread, the main thread's
    ``time.sleep`` line ends up with the worker's bytes.
    """
    profile = run_scalene_memory_profile(tmp_path, FIXTURE, timeout=180)
    lines = fixture_lines(profile, FIXTURE.name)
    by_lineno = {ln["lineno"]: ln for ln in lines}

    worker = by_lineno.get(WORKER_ALLOC_LINE)
    assert worker is not None, (
        f"Worker line {WORKER_ALLOC_LINE} missing. "
        f"Lines present: {sorted(by_lineno)}"
    )
    worker_mb = worker["n_malloc_mb"]
    main_mb = by_lineno.get(MAIN_SLEEP_LINE, {}).get("n_malloc_mb", 0.0)

    assert worker_mb > 0.0, (
        f"Worker line {WORKER_ALLOC_LINE} got zero bytes: {worker!r}"
    )
    assert worker_mb >= 10.0 * max(main_mb, 0.1), (
        f"Worker line {WORKER_ALLOC_LINE} got {worker_mb} MB but main "
        f"sleep line {MAIN_SLEEP_LINE} got {main_mb} MB. Expected "
        f"worker >= 10x main. This is the issue-#857 regression: "
        f"worker-thread allocations leaking onto the main thread's "
        f"idle frame because the stack walker picked the GIL holder "
        f"instead of the allocating thread."
    )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows libscalene.dll doesn't implement whereInPythonWithStack; memory_stacks is always empty (scalene_profiler.py:839)",
)
def test_memory_stacks_leaf_is_worker(tmp_path: Path) -> None:
    """With ``--stacks``, at least one ``memory_stacks`` entry must
    leaf on the worker's allocator line in the fixture file."""
    profile = run_scalene_memory_profile(
        tmp_path, FIXTURE, extra_args=["--stacks"], timeout=180,
        require_memory_stacks=True,
    )
    found = False
    for frames, _mb in profile["memory_stacks"]:
        fn = leaf_filename(frames) or ""
        ln = leaf_line(frames)
        if fn.endswith(FIXTURE.name) and ln == WORKER_ALLOC_LINE:
            found = True
            break
    assert found, (
        f"No memory_stacks entry leafed on worker allocator line "
        f"{WORKER_ALLOC_LINE} of {FIXTURE.name}. Stack capture is "
        f"picking the wrong thread."
    )
