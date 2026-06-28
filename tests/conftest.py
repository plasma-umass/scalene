"""Pytest hooks for the Scalene test suite.

The free-threaded CI jobs (3.13t/3.14t) can run past the 45-minute job
timeout and get cancelled mid-suite. When that happens pytest never reaches
its end-of-session ``-rs`` summary, so the *reasons* any memory_* tests
skipped are lost. ``pytest_runtest_logreport`` fires as each test finishes,
so printing the skip reason here (flushed) guarantees it lands in the CI log
even if the job is killed before the summary. Gated on SCALENE_TEST_DIAG=1
so normal local runs stay quiet.
"""

import os
import sys


def pytest_runtest_logreport(report):
    if os.environ.get("SCALENE_TEST_DIAG") != "1":
        return
    if not report.skipped:
        return
    if report.when not in ("setup", "call"):
        return
    # report.longrepr for a skip is a (path, lineno, reason) tuple.
    reason = report.longrepr
    if isinstance(reason, tuple) and len(reason) == 3:
        reason = reason[2]
    print(
        f"\n[SCALENE_TEST_DIAG] SKIP {report.nodeid}\n"
        f"  reason: {reason}\n"
        f"  LD_PRELOAD={os.environ.get('LD_PRELOAD')!r} "
        f"DYLD_INSERT_LIBRARIES={os.environ.get('DYLD_INSERT_LIBRARIES')!r}\n"
        f"  PYTHONMALLOC={os.environ.get('PYTHONMALLOC')!r} "
        f"PYTHON_GIL={os.environ.get('PYTHON_GIL')!r}\n"
        f"  sys.executable={sys.executable!r}",
        flush=True,
    )
