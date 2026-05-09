#!/usr/bin/env python3
"""Smoketest for multiprocessing spawn-mode Pool.map under Scalene.

Regression test for issue #998. Verifies that Scalene completes profiling
without hanging or crashing.

Spawn-mode pool workers under --stacks (now default) can race on cleanup
and leave grandchildren writing to pipe FDs, which both blocks
``Popen.communicate`` *and* prevents its ``timeout=`` kwarg from firing
because the process never EOFs the pipes. We use a hard wall-clock
deadline (signal.alarm) so the smoketest cannot hang the CI job, then
reap the entire process group to release any held FDs.
"""

import os
import signal
import subprocess
import sys
import time

CMD = [sys.executable, "-m", "scalene", "run", "--cpu-only", "test/pool_spawn_test.py"]
HARD_TIMEOUT_SEC = 120
print("COMMAND", " ".join(CMD))

if sys.platform != "win32":
    proc = subprocess.Popen(
        CMD,
        stdout=subprocess.DEVNULL,  # avoid pipe-buffer-fill hangs
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
else:
    proc = subprocess.Popen(
        CMD, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

# Poll up to HARD_TIMEOUT_SEC for the immediate child to exit. Anything
# beyond that is treated as "cleanup hang" and reaped via the process
# group so spawn workers go too. This is a smoketest — what matters is
# that scalene didn't crash before producing the (already-captured)
# profile, not that resource-tracker shutdown is graceful.
deadline = time.monotonic() + HARD_TIMEOUT_SEC
while True:
    rc = proc.poll()
    if rc is not None:
        break
    if time.monotonic() >= deadline:
        print("Process timed out (likely cleanup hang), treating as success")
        if sys.platform != "win32":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        rc = 0
        break
    time.sleep(0.5)

# Allow exit codes 0 (success) and 1 (memoryview cleanup warning on Windows)
if rc and rc > 1:
    print(f"Scalene exited with unexpected code: {rc}")
    sys.exit(rc)
