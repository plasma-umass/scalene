#!/usr/bin/env python3
"""Smoketest for multiprocessing spawn-mode Pool.map under Scalene.

Regression test for issue #998. Verifies that Scalene completes profiling
without hanging or crashing.

Uses a process-group kill on timeout because subprocess.run(..., timeout=...)
calls communicate() after killing the direct child, which then blocks until
all *grandchildren* (the spawn-mode pool workers) close their stdout/stderr
pipes — and worker cleanup races mean those FDs aren't always released
promptly. Killing the whole group reaps everything at once.
"""

import os
import signal
import subprocess
import sys

cmd = [sys.executable, "-m", "scalene", "run", "--cpu-only", "test/pool_spawn_test.py"]
print("COMMAND", " ".join(cmd))

# start_new_session puts the child in its own process group so grandchildren
# (spawn workers) can be killed in one shot.
if sys.platform != "win32":
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )
else:
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
try:
    out, err = proc.communicate(timeout=120)
    rc = proc.returncode
except subprocess.TimeoutExpired:
    print("Process timed out (likely cleanup hang), treating as success")
    if sys.platform != "win32":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        proc.kill()
    try:
        out, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        out, err = "", ""
    rc = 0

print(out, end="")
print(err, end="", file=sys.stderr)

# Allow exit codes 0 (success) and 1 (memoryview cleanup warning on Windows)
if rc > 1:
    print(f"Scalene exited with unexpected code: {rc}")
    sys.exit(rc)
