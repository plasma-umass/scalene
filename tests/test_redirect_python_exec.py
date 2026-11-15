"""A child Python started under Scalene must have the PID its parent was given.

Scalene replaces ``python`` with a small bash script so that child Pythons
run under Scalene. The script used to run Python as a child of bash, so the
PID the parent got was bash's: ``terminate()`` and ``kill()`` stopped bash
and left the real Python running, and a spawn-mode multiprocessing Pool
never exited.
"""

import os
import subprocess
import sys

import pytest

from scalene.redirect_python import redirect_python
from scalene.scalene_arguments import ScaleneArguments
from scalene.scalene_preload import ScalenePreload


@pytest.mark.skipif(
    sys.platform == "win32", reason="on Windows the wrapper always changes the PID"
)
def test_child_python_has_the_pid_its_parent_was_given(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "executable", sys.executable)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("PATH", os.environ["PATH"])

    # The variables Scalene gives its children. Without them a child starts
    # itself a second time (ScalenePreload.setup_preload), in a new process.
    environ = ScalenePreload.get_preload_environ(ScaleneArguments(memory=False))
    preface = " ".join(f"{name}='{value}'" for name, value in environ.items())

    # From here on, sys.executable is Scalene's wrapper script.
    redirect_python(preface, f"--cpu-only --pid={os.getpid()} ---", tmp_path)

    child = subprocess.Popen(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        stdout=subprocess.PIPE,
    )
    pid_the_child_sees = int(child.communicate(timeout=10)[0])

    assert pid_the_child_sees == child.pid
