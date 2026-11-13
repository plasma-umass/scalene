"""Tests for the memory sample reader: ScaleneMapFile.read_records and the
record processing in ScaleneMemoryProfiler.

The records are fed through real (in-memory) log buffers, the same way the
native writer leaves them, so these cover the batch read path end to end.
"""

import os
import struct
import sys
import threading

import pytest

from scalene import scalene_memory_profiler as smp
from scalene.scalene_arguments import ScaleneArguments
from scalene.scalene_mapfile import ScaleneMapFile, decode_sample
from scalene.scalene_statistics import ScaleneStatistics

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="batch reads use the POSIX mapfile reader"
)

PID = os.getpid()
MB = 1024 * 1024


def _mapfile(records, chunk_size=None):
    """A ScaleneMapFile reading ``records`` (bytes, one per record)."""
    log = b"".join(r + b"\n" for r in records)
    m = ScaleneMapFile.__new__(ScaleneMapFile)
    m._name = "malloc"
    m._buf = bytearray(ScaleneMapFile.MAX_BUFSIZE)
    m._chunk = None
    m._lastpos = bytearray(16)
    m._owner_pid = PID
    lock = bytearray(4096)
    struct.pack_into("<Q", lock, 0, len(log))
    m._lock_mmap = lock
    m._signal_mmap = bytearray(log) + bytearray(64)
    if chunk_size is not None:
        m.READ_CHUNK_SIZE = chunk_size
    return m


def _drain(m):
    out = []
    while records := m.read_records():
        out.extend(records)
    return out


def test_read_records_returns_every_record_in_order():
    records = [f"record-{i}".encode() for i in range(1000)]
    m = _mapfile(records, chunk_size=256)  # forces many partial batches
    assert _drain(m) == [r.decode() for r in records]


def test_read_records_decodes_like_decode_sample():
    # Non-ASCII and undecodable bytes in paths must round-trip (#1086).
    records = ["M,1,2,0.5,1,0x1,/tmp/ümlaut.py,3,4".encode(), b"/tmp/bad\xff.py"]
    m = _mapfile(records)
    assert _drain(m) == [decode_sample(r) for r in records]


def test_read_records_rewinds_drained_log():
    m = _mapfile([b"a", b"b"])
    assert _drain(m) == ["a", "b"]
    lock = m._lock_mmap
    assert lock is not None
    # Writer position back to 0, generation bumped (see get_line_atomic.cpp).
    assert struct.unpack_from("<Q", lock, 0)[0] == 0
    assert struct.unpack_from("<Q", lock, 64)[0] == 1


def _alloc_line_file(tmp_path):
    """A source file whose line 1 can allocate and line 2 cannot."""
    path = tmp_path / "allocs.py"
    path.write_text("x = [0] * 10\npass\n")
    return str(path)


def _malloc(action, count, fname, lineno, pid=PID, ptr="0x10", stack=""):
    rec = f"{action},1,{count},0.250000,{pid},{ptr},{fname},{lineno},7"
    if stack:
        rec += "," + stack
    return rec.encode()


def _process(records):
    stats = ScaleneStatistics()
    profiler = smp.ScaleneMemoryProfiler(stats)
    profiler.set_mapfiles(_mapfile(records), None)
    profiler.process_malloc_free_samples(0, ScaleneArguments(), threading.Lock(), [])
    return stats


def test_mallocs_and_frees_are_attributed(tmp_path):
    fname = _alloc_line_file(tmp_path)
    stats = _process(
        [
            _malloc("M", 4 * MB, fname, 1, stack=f"|{fname};1|{fname};2"),
            _malloc("M", 2 * MB, fname, 1),
            _malloc("F", 1 * MB, fname, 1),
        ]
    )
    mem = stats.memory_stats
    assert mem.alloc_samples == 3
    assert mem.memory_malloc_samples[fname][1] == 6.0
    assert mem.memory_python_samples[fname][1] == 1.5
    assert mem.memory_free_samples[fname][1] == 1.0
    assert mem.memory_current_footprint[fname][1] == 5.0
    assert mem.max_footprint == 6.0
    assert mem.current_footprint == 5.0
    assert stats.bytei_map[fname][1] == {7}
    # The stack is leaf-first in the record and outermost-first in the stats.
    [(stack, mb)] = stats.memory_stacks.items()
    assert [(f.filename, f.line_number) for f in stack] == [(fname, 2), (fname, 1)]
    assert mb == 4.0


def test_samples_on_non_allocating_lines_are_not_attributed(tmp_path):
    fname = _alloc_line_file(tmp_path)
    stats = _process([_malloc("M", 4 * MB, fname, 2)])
    mem = stats.memory_stats
    assert mem.current_footprint == 4.0  # still in the global footprint
    assert fname not in mem.memory_malloc_samples


def test_malformed_and_foreign_records_are_skipped(tmp_path):
    # These used to raise ValueError out of the processing loop.
    fname = _alloc_line_file(tmp_path)
    good = _malloc("M", 1 * MB, fname, 1)
    stats = _process(
        [
            _malloc("M", 1 * MB, fname, 1, pid="notapid"),
            _malloc("M", "lots", fname, 1),
            _malloc("X", 1 * MB, fname, 1),
            _malloc("M", 1 * MB, fname, 1, pid=PID + 1),
            b"too,few,fields",
            good,
        ]
    )
    assert stats.memory_stats.alloc_samples == 1
    assert stats.memory_stats.memory_malloc_samples[fname][1] == 1.0


def test_memcpy_records_after_a_malformed_one_are_kept():
    stats = ScaleneStatistics()
    profiler = smp.ScaleneMemoryProfiler(stats)
    records = [
        f"5,100,{PID},a.py,3,1".encode(),
        f"bad,100,{PID},a.py,3,1".encode(),
        f"6,200,{PID},a.py,3,2".encode(),
        f"7,999,{PID + 1},a.py,3,2".encode(),
    ]
    profiler.set_mapfiles(None, _mapfile(records))  # type: ignore[arg-type]
    profiler.process_memcpy_samples()
    assert stats.memory_stats.memcpy_samples["a.py"][3] == 300
    assert stats.bytei_map["a.py"][3] == {1, 2}


def test_stack_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(smp, "_STACK_CACHE_LIMIT", 8)
    smp._stack_cache.clear()
    for i in range(50):
        stack = smp._parse_stack(f"|f.py;{i + 1}")
        assert stack is not None and stack[0].line_number == i + 1
        assert len(smp._stack_cache) <= 8
    assert smp._parse_stack("") is None
    assert smp._parse_stack("no-pipe") is None
    assert smp._parse_stack("|;3|bad|f.py;x") is None
