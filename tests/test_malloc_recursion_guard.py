"""End-to-end check of libscalene's per-thread allocation state.

Every interposed malloc/free/memcpy consults a per-thread "already inside
malloc" flag (MallocRecursionGuard). On macOS the flag lives in a slot from
an mmap'd pool that is set up on a thread's first allocation and recycled
when the thread exits; on Linux it is an initial-exec thread-local. This
runs a memory profile across thousands of short-lived threads and a fork,
and checks that the run completes and allocations are still attributed.
"""

import json
import subprocess
import sys
import textwrap

import pytest

PROGRAM = textwrap.dedent("""
    import os, threading

    def work():
        xs = [bytearray(64 * 1024) for _ in range(32)]
        del xs

    for _ in range(4):
        threads = [threading.Thread(target=work) for _ in range(500)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    pid = os.fork()
    if pid == 0:
        work()
        os._exit(0)
    _, status = os.waitpid(pid, 0)
    assert status == 0, status

    big = [bytearray(1024 * 1024) for _ in range(64)]
    print("DONE", flush=True)
    """)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX allocator interposition")
def test_memory_profile_survives_thread_churn_and_fork(tmp_path):
    script = tmp_path / "churn.py"
    script.write_text(PROGRAM)
    outfile = tmp_path / "profile.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scalene",
            "run",
            "--memory",
            "-o",
            str(outfile),
            str(script),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert "DONE" in proc.stdout, proc.stdout[-2000:] + proc.stderr[-2000:]

    profile = json.loads(outfile.read_text())
    [entry] = [v for k, v in profile["files"].items() if k.endswith("churn.py")]
    malloc_mb = {line["lineno"]: line["n_malloc_mb"] for line in entry["lines"]}
    # The 64 MB allocated on the last line must be attributed to it.
    big_line = 1 + PROGRAM.splitlines().index(
        "big = [bytearray(1024 * 1024) for _ in range(64)]"
    )
    assert malloc_mb.get(big_line, 0) > 0, {k: v for k, v in malloc_mb.items() if v}
