"""Issue #1122: memory profiling with repeated @profile registration.

The crash in #1122 was the native sample log overflowing (fixed by bounding
the writer). These tests cover what made the log fill in the first place:

- the log was append-only, so any long enough run filled it; the owning
  reader now rewinds it whenever it has drained it;
- every ``profile()`` call -- e.g. decorating a nested function, which
  creates a new function object each time -- cleared every should_trace
  cache, rebuilt the native trace config, and kept the function object
  alive forever.
"""

import json
import subprocess
import sys
import textwrap
import types
from collections import defaultdict

import pytest

from scalene.scalene_mapfile import ScaleneMapFile
from scalene.scalene_profiler import Scalene


@pytest.fixture
def fresh_profile_state(monkeypatch):
    registrations = []
    monkeypatch.setattr(Scalene, "_Scalene__files_to_profile", set())
    monkeypatch.setattr(Scalene, "_Scalene__functions_to_profile", defaultdict(set))
    monkeypatch.setattr(Scalene, "_Scalene__profiled_code_objects", set())
    monkeypatch.setattr(
        Scalene, "_Scalene__args", types.SimpleNamespace(memory=True), raising=False
    )
    monkeypatch.delattr(Scalene, "_Scalene__tracing", raising=False)
    monkeypatch.setattr(
        Scalene,
        "_register_files_to_profile",
        staticmethod(lambda: registrations.append(1)),
    )
    return registrations


def _make_nested():
    def inner():
        return 1

    return inner


def _other():
    return 2


def test_repeated_registration_of_same_code_is_a_no_op(fresh_profile_state):
    registrations = fresh_profile_state
    first = _make_nested()
    for _ in range(1000):
        fn = _make_nested()
        assert Scalene._profile(fn) is fn
    Scalene._profile(first)

    funcs = Scalene._Scalene__functions_to_profile[first.__code__.co_filename]
    assert len(funcs) == 1  # not one per function object
    assert len(registrations) == 1  # the native side heard about the file once


def test_new_function_in_known_file_is_registered_without_native_rebuild(
    fresh_profile_state,
):
    registrations = fresh_profile_state
    Scalene._profile(_make_nested())
    Scalene._profile(_other)
    funcs = Scalene._Scalene__functions_to_profile[_other.__code__.co_filename]
    assert {f.__code__.co_name for f in funcs} == {"inner", "_other"}
    assert len(registrations) == 1  # same file: no native re-registration


def test_line_info_cache_includes_later_decorated_functions(fresh_profile_state):
    fname = _other.__code__.co_filename
    Scalene._profile(_make_nested())
    before = Scalene._get_line_info(fname)
    Scalene._profile(_other)
    after = Scalene._get_line_info(fname)
    assert len(before) == 1
    assert len(after) == 2


def test_get_str_returns_first_record_only():
    mf = ScaleneMapFile.__new__(ScaleneMapFile)
    mf._buf = bytearray(ScaleneMapFile.MAX_BUFSIZE)
    # A long earlier record left bytes behind; the reader then copied a
    # shorter one plus its newline to the front.
    mf._buf[:20] = b"M,1,2,3,4,5,old-long"
    mf._buf[:8] = b"F,9,9,9\n"
    assert mf.get_str() == "F,9,9,9"
    # NUL-padded record without a newline (Windows reader).
    mf._buf[:] = bytes(ScaleneMapFile.MAX_BUFSIZE)
    mf._buf[:5] = b"M,1,2"
    assert mf.get_str() == "M,1,2"


PROBE = textwrap.dedent("""
    import json, struct, sys, threading, time
    from scalene.scalene_profiler import Scalene

    stop = False

    def churn():
        while not stop:
            x = [bytearray(64 * 1024) for _ in range(64)]
            del x

    def state():
        mf = Scalene._Scalene__malloc_mapfile
        return {
            "generation": struct.unpack_from("<Q", mf._lock_mmap, 64)[0],
            "reader": list(struct.unpack_from("<QQ", mf._lastpos, 0)),
        }

    t = threading.Thread(target=churn)
    t.start()
    time.sleep(1)
    stop = True
    t.join()

    # The log is rewound only by a drain that fully catches up with the
    # writer, which a busy (or slow CI) machine may not manage while the
    # churn thread is running. Now that writing has (mostly) stopped, keep
    # triggering malloc samples -- each one makes the reader drain the log --
    # until a drain catches up.
    deadline = time.time() + 60
    while state()["generation"] == 0 and time.time() < deadline:
        x = bytearray(64 * 1024 * 1024)
        del x
        time.sleep(0.1)
    print("PROBE", json.dumps(state()), file=sys.stderr)
    """)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX sample log")
def test_sample_log_is_rewound_during_a_real_run(tmp_path):
    script = tmp_path / "churn.py"
    script.write_text(PROBE)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scalene",
            "run",
            "--memory",
            "-o",
            str(tmp_path / "p.json"),
            str(script),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    lines = [ln for ln in proc.stderr.splitlines() if ln.startswith("PROBE ")]
    assert lines, proc.stderr[-3000:]
    probe = json.loads(lines[-1][len("PROBE ") :])
    assert probe["generation"] >= 1, probe
    # The reader has followed a rewind. (Read without the lock, so it may
    # trail a rewind that happened between the two reads.)
    assert probe["reader"][1] >= 1, probe
