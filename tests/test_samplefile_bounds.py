"""SampleFile must not write past the end of its log (POSIX).

The native sample log is append-only and never wraps. writeToFile used to
append unconditionally, so a long enough run (or a short one with large
--stacks records) wrote past the end of the mapping. This compiles a small
harness against samplefile.hpp with a tiny log, overfills it, and checks that
the writer stops at the end, keeps what it wrote, and warns once.
"""

import os
import shutil
import struct
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HEAP_LAYERS = ROOT / "vendor" / "Heap-Layers"
PRINTF = ROOT / "vendor" / "printf"
CXX = os.environ.get("CXX") or shutil.which("c++") or shutil.which("g++")

pytestmark = [
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX SampleFile"),
    pytest.mark.skipif(CXX is None, reason="no C++ compiler"),
    pytest.mark.skipif(
        not (HEAP_LAYERS / "heaplayers.h").exists()
        or not (PRINTF / "printf.cpp").exists(),
        reason="vendored Heap-Layers/printf not fetched",
    ),
]

MAX_FILE_SIZE = 16 * 4096  # passed as SCALENE_SAMPLEFILE_MAX_FILE_SIZE
MAX_BUFSIZE = 4096

HARNESS = textwrap.dedent(r"""
    #include <stdio.h>
    #include <stdlib.h>
    #include <string.h>
    #include "samplefile.hpp"

    // Required by the vendored printf (libscalene defines its own).
    extern "C" void _putchar(char c) { fputc(c, stderr); }

    int main(int argc, char** argv) {
      // argv[1]: directory; argv[2]: number of records; argv[3]: record length
      char sig[1024], lock[1024], init[1024];
      snprintf(sig, sizeof sig, "%s/signal%%d", argv[1]);
      snprintf(lock, sizeof lock, "%s/lock%%d", argv[1]);
      snprintf(init, sizeof init, "%s/init%%d", argv[1]);
      SampleFile f(sig, lock, init);
      int n = atoi(argv[2]);
      int len = atoi(argv[3]);  // total record length, including "\n\n"
      char* rec = (char*)malloc(SampleFile::MAX_BUFSIZE);
      memset(rec, 'r', len - 2);
      rec[len - 2] = '\n';
      rec[len - 1] = '\n';
      rec[len] = '\0';
      for (int i = 0; i < n; i++) {
        f.writeToFile(rec);
      }
      // Report where the writer ended up via the lock file contents.
      fflush(stdout);
      _exit(0);  // skip ~SampleFile, which unlinks the files we inspect
    }
    """)


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    d = tmp_path_factory.mktemp("samplefile")
    src = d / "harness.cpp"
    src.write_text(HARNESS)
    exe = d / "harness"
    cmd = [
        CXX,
        "-std=c++14",
        "-O1",
        f"-DSCALENE_SAMPLEFILE_MAX_FILE_SIZE={MAX_FILE_SIZE}",
        f"-I{ROOT / 'src' / 'include'}",
        f"-I{HEAP_LAYERS}",
        f"-I{HEAP_LAYERS / 'utility'}",
        f"-I{PRINTF}",
        str(src),
        str(PRINTF / "printf.cpp"),
        "-o",
        str(exe),
        "-lpthread",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"could not build harness:\n{proc.stderr[-2000:]}"
    return exe


def _run(harness, tmp_path, n, length):
    proc = subprocess.run(
        [str(harness), str(tmp_path), str(n), str(length)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    lock = next(tmp_path.glob("lock*")).read_bytes()
    pos = struct.unpack("<Q", lock[:8])[0]
    signal = next(tmp_path.glob("signal*")).read_bytes()
    return proc, pos, signal


def test_records_within_capacity_are_written(harness, tmp_path):
    proc, pos, signal = _run(harness, tmp_path, 3, 100)
    assert proc.returncode == 0, proc.stderr
    assert pos == 3 * 99  # each record advances by len - 1
    assert signal[: 3 * 99] == (b"r" * 98 + b"\n") * 3
    assert "sample log is full" not in proc.stderr


@pytest.mark.parametrize("length", [100, 1000, MAX_BUFSIZE - 1])
def test_overfilling_stops_at_end_and_warns_once(harness, tmp_path, length):
    # Far more data than fits: the old code wrote past the end of the
    # mapping here and crashed.
    n = 4 * MAX_FILE_SIZE // (length - 1)
    proc, pos, signal = _run(harness, tmp_path, n, length)
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    assert len(signal) == MAX_FILE_SIZE
    # Every write needs MAX_BUFSIZE of headroom (strncpy pads).
    assert pos <= MAX_FILE_SIZE - MAX_BUFSIZE + (length - 1)
    assert pos > MAX_FILE_SIZE - MAX_BUFSIZE - length
    # Everything accepted is intact and still newline-terminated.
    assert signal[:pos] == (b"r" * (length - 2) + b"\n") * (pos // (length - 1))
    assert signal[pos : pos + 1] == b"\n"
    assert proc.stderr.count("sample log is full") == 1
