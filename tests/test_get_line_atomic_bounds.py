"""Regression tests for get_line_atomic's bounds handling (issue #1117).

get_line_atomic used to bound its newline search by the size of the *result*
buffer rather than by the bytes left in the *signal* buffer, so with
``lastpos`` near the end of the mapping it read past it. These tests place a
PROT_NONE guard page directly after the signal buffer; the old code died with
SIGBUS/SIGSEGV there. The guard-page probe runs in a subprocess so a crash is
reported as a test failure instead of killing pytest.
"""

import struct
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="get_line_atomic is POSIX-only"
)

LOCK_SIZE = 4096
RESULT_SIZE = 4096  # ScaleneMapFile.MAX_BUFSIZE


def _call(signal: bytes, lastpos: int, result_size: int = RESULT_SIZE):
    from scalene import get_line_atomic  # type: ignore

    lock = bytearray(LOCK_SIZE)
    result = bytearray(result_size)
    pos = bytearray(struct.pack("<Q", lastpos))
    ok = get_line_atomic.get_line_atomic(lock, signal, result, pos)
    return ok, bytes(result), struct.unpack("<Q", pos)[0]


def test_reads_lines_in_order():
    ok, result, pos = _call(b"abc\ndef\n", 0)
    assert ok is True
    assert result.startswith(b"abc\n")
    assert pos == 4

    ok, result, pos = _call(b"abc\ndef\n", 4)
    assert ok is True
    assert result.startswith(b"def\n")
    assert pos == 8


def test_no_newline_in_remaining_bytes_returns_false():
    # Newline-free tail: must report "no complete line" and leave lastpos alone.
    ok, _, pos = _call(b"x" * 64, 60)
    assert ok is False
    assert pos == 60


@pytest.mark.parametrize("lastpos", [64, 65, 1 << 40])
def test_lastpos_at_or_past_end_returns_false(lastpos):
    ok, _, pos = _call(b"x" * 63 + b"\n", lastpos)
    assert ok is False
    assert pos == lastpos


def test_line_longer_than_result_buffer_is_not_copied():
    # The line plus its newline would not fit in the result buffer; it must
    # not be copied (that would overflow the result buffer).
    signal = b"y" * 32 + b"\n"
    ok, result, pos = _call(signal, 0, result_size=16)
    assert ok is False
    assert pos == 0
    assert result == bytes(16)


def test_line_exactly_filling_result_buffer():
    signal = b"z" * 15 + b"\n"
    ok, result, pos = _call(signal, 0, result_size=16)
    assert ok is True
    assert result == signal
    assert pos == 16


def test_buffers_are_released():
    # Each call used to leak a buffer export on every argument, which made
    # the mmaps impossible to close ("exported pointers exist").
    import mmap

    from scalene import get_line_atomic  # type: ignore

    signal = mmap.mmap(-1, mmap.PAGESIZE)
    signal.write(b"hello\n")
    lock = mmap.mmap(-1, LOCK_SIZE)
    result = bytearray(RESULT_SIZE)
    pos = bytearray(8)
    assert get_line_atomic.get_line_atomic(lock, signal, result, pos) is True
    signal.close()
    lock.close()


def test_too_small_lock_or_lastpos_buffer_raises():
    from scalene import get_line_atomic  # type: ignore

    with pytest.raises(ValueError):
        get_line_atomic.get_line_atomic(
            bytearray(4), b"a\n", bytearray(16), bytearray(8)
        )
    with pytest.raises(ValueError):
        get_line_atomic.get_line_atomic(
            bytearray(LOCK_SIZE), b"a\n", bytearray(16), bytearray(4)
        )


GUARD_PAGE_PROBE = textwrap.dedent("""
    import ctypes, ctypes.util, mmap, struct, sys
    from scalene import get_line_atomic

    page = mmap.PAGESIZE
    mm = mmap.mmap(-1, 2 * page)
    mm.write(b"x" * page)  # first page: no newline anywhere
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    libc.mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    base = ctypes.addressof(ctypes.c_char.from_buffer(mm))
    if libc.mprotect(base + page, page, 0) != 0:  # PROT_NONE guard page
        sys.exit(2)
    signal = memoryview(mm)[:page]
    pos = bytearray(struct.pack("<Q", page - 4))
    ok = get_line_atomic.get_line_atomic(
        bytearray(4096), signal, bytearray(4096), pos
    )
    assert ok is False, ok
    assert struct.unpack("<Q", pos)[0] == page - 4
    print("OK")
    """)


def test_does_not_read_past_signal_buffer():
    proc = subprocess.run(
        [sys.executable, "-c", GUARD_PAGE_PROBE],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode == 2:
        pytest.skip("mprotect unavailable")
    assert proc.returncode == 0, (
        f"probe failed (returncode {proc.returncode}):\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    assert "OK" in proc.stdout
