"""Regression test for issue #1063: non-ASCII --profile-only crashes (SIGSEGV).

Issue: https://github.com/plasma-umass/scalene/issues/1063

The ``pywhere`` extension's ``TraceConfig`` constructor converted each
``--profile-only`` pattern with ``PyUnicode_AsASCIIString`` and fed the
result straight into ``PyBytes_AsString`` without a NULL check. For a
non-ASCII value like ``é`` the ASCII conversion returns NULL, so the
unchecked ``PyBytes_AsString(NULL)`` dereference crashed the whole
process with SIGSEGV (return code 245 / -SIGSEGV).

The fix decodes patterns as UTF-8 via ``PyUnicode_AsUTF8AndSize`` and
skips items that fail to decode instead of dereferencing NULL. This test
runs scalene with a non-ASCII ``--profile-only`` value and asserts the
target program runs to completion without a signal-induced crash.
"""

import pathlib
import subprocess
import sys
import tempfile

_TARGET = 'print("target ran")\n'


def _run_with_profile_only(pattern: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="scalene_1063_") as tmp:
        tmp = pathlib.Path(tmp)
        script = tmp / "noop_target.py"
        script.write_text(_TARGET)
        outfile = tmp / "profile.json"

        cmd = [
            sys.executable,
            "-m",
            "scalene",
            "run",
            "-o",
            str(outfile),
            "--profile-only",
            pattern,
            str(script),
        ]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def test_non_ascii_profile_only_does_not_crash():
    """A non-ASCII --profile-only value must not SIGSEGV the profiler."""
    proc = _run_with_profile_only("é")

    # A negative return code is a signal-induced termination; -11 is SIGSEGV,
    # which is the exact failure mode reported in #1063.
    assert proc.returncode >= 0, (
        f"scalene crashed with signal {-proc.returncode} on non-ASCII "
        f"--profile-only; stderr={proc.stderr[-400:]}"
    )
    assert "SIGSEGV" not in proc.stderr, (
        f"scalene reported SIGSEGV on non-ASCII --profile-only:\n{proc.stderr}"
    )
    # The target program should still have run.
    assert "target ran" in proc.stdout, (
        f"target program did not run; rc={proc.returncode} "
        f"stdout={proc.stdout[-400:]} stderr={proc.stderr[-400:]}"
    )


def test_ascii_profile_only_control():
    """An ASCII --profile-only value behaves identically (control case)."""
    proc = _run_with_profile_only("ascii")

    assert proc.returncode >= 0, (
        f"scalene crashed with signal {-proc.returncode} on ASCII "
        f"--profile-only; stderr={proc.stderr[-400:]}"
    )
    assert "target ran" in proc.stdout, (
        f"target program did not run; rc={proc.returncode} "
        f"stdout={proc.stdout[-400:]} stderr={proc.stderr[-400:]}"
    )
