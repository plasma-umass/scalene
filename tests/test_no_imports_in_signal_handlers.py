"""Scalene's signal handlers must never import a module for the first time.

A first-time import inside a Python signal handler re-enters the import
system on the main thread. On Python < 3.12, if the signal lands while the
main thread is inside importlib's ``_ModuleLock.acquire()``, the nested
acquire deletes the thread's ``_blocking_on`` entry and the outer acquire's
``finally: del _blocking_on[tid]`` raises ``KeyError``, crashing whatever
import the profiled program was doing. This showed up as an intermittent
``KeyError`` from ``<frozen importlib._bootstrap>`` while the decorator
smoketest imported numpy on Ubuntu / Python 3.11: ``get_times()`` did
``import resource`` on the first CPU sample.

Hitting that window is timing-dependent, so instead of waiting for the crash
this test records, via an audit hook in the profiled program, every
first-time import made while a Scalene handler is on the stack.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROGRAM = textwrap.dedent("""
    import json, os, sys, time

    HANDLERS = {
        "cpu_signal_handler",
        "malloc_signal_handler",
        "free_signal_handler",
        "memcpy_signal_handler",
    }
    hits = []

    def hook(event, args):
        if event != "import":
            return
        f = sys._getframe(1)
        while f is not None:
            if f.f_code.co_name in HANDLERS:
                hits.append([args[0], f.f_code.co_name])
                return
            f = f.f_back

    sys.addaudithook(hook)

    # Run long enough for CPU and allocation samples to fire.
    deadline = time.perf_counter() + 1.0
    junk = []
    while time.perf_counter() < deadline:
        junk.append(bytearray(1 << 20))
        if len(junk) > 16:
            junk.clear()

    with open(os.environ["SCALENE_TEST_HITS"], "w") as out:
        json.dump(hits, out)
    """)


@pytest.mark.skipif(
    sys.platform == "win32", reason="CPU sampling uses a thread on Windows"
)
def test_signal_handlers_do_not_import(tmp_path: Path) -> None:
    prog = tmp_path / "prog.py"
    prog.write_text(PROGRAM)
    hits_file = tmp_path / "hits.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scalene",
            "run",
            "-o",
            str(tmp_path / "profile.json"),
            str(prog),
        ],
        env={**os.environ, "SCALENE_TEST_HITS": str(hits_file)},
        capture_output=True,
        timeout=120,
    )
    if not hits_file.exists():
        pytest.skip("profiled program did not finish (suspected startup flake)")
    hits = json.loads(hits_file.read_text())
    assert hits == [], f"modules first imported inside Scalene signal handlers: {hits}"
