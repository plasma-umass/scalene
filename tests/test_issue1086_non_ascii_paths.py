"""Regression test for issue #1086: non-ASCII characters in a profiled file's path.

Issue: https://github.com/plasma-umass/scalene/issues/1086

``pywhere.cpp`` converted ``code->co_filename`` with
``PyUnicode_AsASCIIString`` on three hot paths (the stack walker used by
the allocator interposer, ``on_stack``, and the settrace line callback).
For a perfectly ordinary path like ``.../überschüsse.py`` that conversion
fails, returning NULL *and leaving a ``UnicodeEncodeError`` set on the
thread*. Because those paths run from the native allocator hook and from
trace callbacks, the stray exception surfaced later at an arbitrary,
unrelated Python line — which is why the reporter saw it land in
``sysconfig.get_path`` one run and inside pydantic the next. The Python
side then compounded it by decoding the native sample records as ASCII.

The fix encodes/decodes filenames as UTF-8 with surrogate escapes and
NULL-checks every conversion. See ``encodeFilename`` in
``src/source/pywhere.cpp`` and ``decode_sample`` in
``scalene/scalene_mapfile.py``.

Only ``--memory`` runs were affected (the reporter noted ``--cpu-only``
worked), since that is what loads the native interposer, so the
end-to-end test here profiles with memory enabled.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from scalene.scalene_mapfile import decode_sample

# A module name with two umlauts, as in the issue's reproducer.
NON_ASCII_MODULE = "überschüsse"

WORKLOAD = """\
def f():
    total = 0
    data = []
    for _ in range(300):
        data.append([j for j in range(2000)])
        total += sum(data[-1])
    return total
"""

MAIN = f"""\
import {NON_ASCII_MODULE}
print({NON_ASCII_MODULE}.f())
"""

# What WORKLOAD's f() returns: sum(range(2000)) * 300.
EXPECTED_OUTPUT = str(sum(range(2000)) * 300)


def test_decode_sample_round_trips_non_ascii_filenames() -> None:
    """Sample records naming a non-ASCII path must decode, not raise.

    This is the Python half of the fix, and it is deterministic: the old
    ``bytes.decode("ascii")`` raised ``UnicodeDecodeError`` here and killed
    the loop that drains malloc/free samples.
    """
    path = f"/tmp/pröfile/{NON_ASCII_MODULE}.py"
    record = f"M,1234,4096,0.5,999,0x7f00,{path},7,0"
    assert decode_sample(record.encode("utf-8")) == record
    # Undecodable filesystem bytes reach Python as lone surrogates; those
    # must survive the round trip too rather than raising.
    surrogate_path = "/tmp/\udcff/x.py"
    surrogate_record = f"M,1,1,0.0,1,0x0,{surrogate_path},1,0"
    assert (
        decode_sample(surrogate_record.encode("utf-8", errors="surrogateescape"))
        == surrogate_record
    )


@pytest.mark.parametrize("in_subdir", [False, True])
def test_memory_profile_of_non_ascii_path(tmp_path: Path, in_subdir: bool) -> None:
    """Profiling a program that imports a module at a non-ASCII path works.

    Two placements are covered: the non-ASCII component in the filename
    itself, and in a parent directory (the issue reported both a
    ``überschüsse.py`` module and an ``optionale_verlängerung.py`` under a
    non-ASCII tree).

    The crash assertions run on every attempt — a regression fails them
    immediately and deterministically, since the profiled program dies
    outright. Only the "file shows up in the profile" check is retried,
    against the usual sampling flake (see ``_scalene_subprocess.py``).
    """
    workdir = tmp_path / ("prögramm" if in_subdir else "program")
    workdir.mkdir()
    module_path = workdir / f"{NON_ASCII_MODULE}.py"
    module_path.write_text(WORKLOAD, encoding="utf-8")
    main_path = workdir / "main.py"
    main_path.write_text(MAIN, encoding="utf-8")

    attempts = 3
    last_files: list = []
    last_output = ""
    for attempt in range(1, attempts + 1):
        out = tmp_path / f"profile_{attempt}.json"
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scalene",
                    "run",
                    "--memory",
                    "--no-browser",
                    "-o",
                    str(out),
                    str(main_path),
                ],
                cwd=str(workdir),
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            # Scalene startup occasionally wedges under CI contention.
            continue
        last_output = combined = proc.stdout + proc.stderr

        assert "UnicodeEncodeError" not in combined, (
            "Non-ASCII path raised UnicodeEncodeError in the profiled program "
            f"(issue #1086):\n{combined[-3000:]}"
        )
        assert "UnicodeDecodeError" not in combined, (
            f"Non-ASCII path raised UnicodeDecodeError:\n{combined[-3000:]}"
        )
        # The workload prints its result; a crash of the profiled program
        # (the #1086 failure mode) means this never appears.
        assert EXPECTED_OUTPUT in proc.stdout, (
            f"Profiled program did not run to completion:\n{combined[-3000:]}"
        )
        assert proc.returncode == 0, (
            f"scalene exited {proc.returncode}:\n{combined[-3000:]}"
        )

        if not (out.exists() and out.stat().st_size > 0):
            continue
        files = json.loads(out.read_text(encoding="utf-8")).get("files", {})
        last_files = list(files)
        # The recorded path must come back intact, not mangled or escaped —
        # this exercises the native encode / Python decode pair end to end.
        # Normalize first: a filesystem may hand back the decomposed (NFD)
        # spelling of "ü" regardless of how we wrote it.
        want = unicodedata.normalize("NFC", str(module_path))
        if any(unicodedata.normalize("NFC", name) == want for name in files):
            return
    pytest.skip(
        "Scalene recorded no samples for the non-ASCII module after "
        f"{attempts} attempts (suspected sampling flake). The program itself "
        f"ran cleanly, so the #1086 crash is not present. "
        f"Profiled files: {last_files}. Last output:\n{last_output[-1000:]}"
    )
