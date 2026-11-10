"""Tests for get_line_atomic: bounds handling (#1117) and log reuse (#1122).

get_line_atomic used to bound its newline search by the size of the *result*
buffer rather than by the bytes left in the *signal* buffer, so with
``lastpos`` near the end of the mapping it read past it. These tests place a
PROT_NONE guard page directly after the signal buffer; the old code died with
SIGBUS/SIGSEGV there. The guard-page probe runs in a subprocess so a crash is
reported as a test failure instead of killing pytest.

The log is append-only on the writer side; once the owning reader has drained
it, the reader rewinds it (write position back to 0, generation bumped), so a
long run doesn't fill it and start dropping samples (#1122).
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
GENERATION_OFFSET = 64  # kGenerationOffset in get_line_atomic.cpp


def _lock(writer_pos: int, generation: int = 0) -> bytearray:
    lock = bytearray(LOCK_SIZE)
    struct.pack_into("<Q", lock, 0, writer_pos)
    struct.pack_into("<Q", lock, GENERATION_OFFSET, generation)
    return lock


def _writer(lock: bytearray):
    return (
        struct.unpack_from("<Q", lock, 0)[0],
        struct.unpack_from("<Q", lock, GENERATION_OFFSET)[0],
    )


def _call(signal: bytes, lastpos: int, result_size: int = RESULT_SIZE, writer_pos=None):
    from scalene import get_line_atomic  # type: ignore

    lock = _lock(len(signal) if writer_pos is None else writer_pos)
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
    lock.write(struct.pack("<Q", 6))
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
    # A (corrupt) writer position past the end of the buffer must be clamped.
    lock = bytearray(4096)
    lock[:8] = struct.pack("<Q", 2 * page)
    ok = get_line_atomic.get_line_atomic(lock, signal, bytearray(4096), pos)
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


def test_reads_stop_at_writer_position():
    # Bytes past the writer's position are stale records from before the last
    # reset and must not be read.
    signal = b"new\nold-stale\n"
    ok, result, pos = _call(signal, 0, writer_pos=4)
    assert ok is True and result.startswith(b"new\n") and pos == 4
    ok, _, pos = _call(signal, 4, writer_pos=4)
    assert ok is False and pos == 4


def _read_all(lock, signal, state, may_reset):
    from scalene import get_line_atomic  # type: ignore

    lines = []
    result = bytearray(RESULT_SIZE)
    while get_line_atomic.get_line_atomic(lock, signal, result, state, may_reset):
        lines.append(bytes(result[: result.index(b"\n")]))
    return lines


def test_owner_rewinds_log_once_drained():
    signal = bytearray(b"a\nb\n" + bytes(64))
    lock = _lock(4)
    state = bytearray(16)
    assert _read_all(lock, signal, state, True) == [b"a", b"b"]
    # Drained: the writer is rewound and the generation bumped.
    assert _writer(lock) == (0, 1)
    assert struct.unpack("<QQ", state) == (0, 1)

    # The writer continues at offset 0; the old records beyond it are stale.
    signal[0:2] = b"c\n"
    struct.pack_into("<Q", lock, 0, 2)
    assert _read_all(lock, signal, state, True) == [b"c"]
    assert _writer(lock) == (0, 2)


def test_non_owner_never_rewinds():
    signal = b"a\nb\n"
    lock = _lock(4)
    state = bytearray(16)
    assert _read_all(lock, signal, state, False) == [b"a", b"b"]
    assert _writer(lock) == (4, 0)
    assert struct.unpack("<QQ", state) == (4, 0)


def test_legacy_eight_byte_state_never_rewinds():
    lock = _lock(4)
    state = bytearray(8)
    assert _read_all(lock, b"a\nb\n", state, True) == [b"a", b"b"]
    assert _writer(lock) == (4, 0)


def test_no_rewind_while_unread_records_remain():
    from scalene import get_line_atomic  # type: ignore

    lock = _lock(4)
    state = bytearray(16)
    result = bytearray(RESULT_SIZE)
    assert get_line_atomic.get_line_atomic(lock, b"a\nb\n", result, state, True)
    assert _writer(lock) == (4, 0)  # "b" is still unread


def test_stale_reader_restarts_after_rewind():
    # A forked child inherits the parent's reader state. Once the parent has
    # rewound the log, the child's position refers to old data; it must start
    # over at the beginning of the current generation instead.
    signal = b"x\ny\n" + b"stale-record\n"
    lock = _lock(4, generation=3)
    state = bytearray(struct.pack("<QQ", 10, 2))  # old generation, old offset
    assert _read_all(lock, signal, state, False) == [b"x", b"y"]
    assert struct.unpack("<QQ", state) == (4, 3)
