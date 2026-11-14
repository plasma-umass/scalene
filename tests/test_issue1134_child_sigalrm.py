"""Issue #1134: Scalene wraps os functions to block SIGALRM while they run
(#841). Functions that start a new program must not be wrapped, or the
program inherits a blocked SIGALRM."""

import os
import subprocess
import sys
import textwrap

import pytest

from scalene.scalene_utility import _starts_a_program


def test_program_starting_functions_are_recognized() -> None:
    for name in (
        "system",
        "popen",
        "posix_spawn",
        "posix_spawnp",
        "execv",
        "execvpe",
        "execl",
        "spawnv",
        "spawnlp",
        "_spawnvef",
    ):
        assert _starts_a_program(name), name
    for name in ("fork", "read", "waitpid", "getpid", "kill", "stat"):
        assert not _starts_a_program(name), name


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal masks")
def test_children_do_not_inherit_blocked_sigalrm() -> None:
    script = textwrap.dedent("""
        import os, signal, sys
        from scalene.scalene_utility import patch_module_functions_with_signal_blocking
        signal.pthread_sigmask(signal.SIG_UNBLOCK, [signal.SIGALRM])
        patch_module_functions_with_signal_blocking(os, signal.SIGALRM)
        check = ("import signal, sys; "
                 "sys.exit(10 if signal.SIGALRM in "
                 "signal.pthread_sigmask(signal.SIG_BLOCK, []) else 0)")
        args = [sys.executable, "-c", check]
        assert os.WEXITSTATUS(os.system(f'"{sys.executable}" -c "{check}"')) == 0, "system"
        _, st = os.waitpid(os.posix_spawn(sys.executable, args, os.environ), 0)
        assert os.WEXITSTATUS(st) == 0, "posix_spawn"
        assert os.spawnv(os.P_WAIT, sys.executable, args) == 0, "spawnv"
        pid = os.fork()
        if pid == 0:
            os.execv(sys.executable, args)
        _, st = os.waitpid(pid, 0)
        assert os.WEXITSTATUS(st) == 0, "execv"
        # Still blocked during ordinary os calls (#841).
        assert hasattr(os.read, "__wrapped__")
        print("OK")
    """)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LD_PRELOAD", "DYLD_", "SCALENE"))
    }
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert out.returncode == 0 and out.stdout.strip() == "OK", out.stdout + out.stderr
