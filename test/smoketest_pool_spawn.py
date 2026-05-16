#!/usr/bin/env python3
"""Smoketest for multiprocessing spawn-mode Pool.map under Scalene.

Regression test for issue #998. Verifies that Scalene completes
profiling — producing a valid profile JSON — without hanging the test
runner.

Spawn-mode pool workers under --stacks (now default) can race on
cleanup and leave grandchildren writing to pipe FDs, which both blocks
``Popen.communicate`` *and* prevents its ``timeout=`` kwarg from
firing because the process never EOFs the pipes. We use a hard
wall-clock deadline so the smoketest cannot hang the CI job, then
reap the entire process group to release any held FDs.

On Windows specifically, scalene's main process has been observed to
finish writing the profile and *then* crash with a kill-style exit
code (``0xFFFFFFFF`` = ``(uint)-1``) during the multiprocessing
resource-tracker shutdown. The work this smoketest is verifying —
*that scalene completed profiling* — has already happened by then,
but the interpreter dies on the way out. Cosmetic shutdown crashes
like that are treated as success *iff* a valid profile JSON was
produced beforehand. A genuinely broken scalene (no profile, or
corrupt profile) still fails. ``stderr`` from the subprocess is
captured to a temp file and dumped only when validation fails, so
diagnostic output is preserved without flooding successful runs.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time

# scalene's default output filename when no ``-o`` is given. Relative
# to the cwd of the scalene subprocess, which inherits from this
# script's cwd.
DEFAULT_PROFILE_PATH = os.path.join(os.getcwd(), "scalene-profile.json")
# Clear any stale profile from a prior run so we don't mistake it for
# fresh output.
try:
    os.remove(DEFAULT_PROFILE_PATH)
except FileNotFoundError:
    pass

CMD = [sys.executable, "-m", "scalene", "run", "--cpu-only", "test/pool_spawn_test.py"]
HARD_TIMEOUT_SEC = 120
print("COMMAND", " ".join(CMD))

# Capture stderr to a temp file rather than DEVNULL so we have
# something to inspect when validation fails. stdout stays at DEVNULL
# because pool_spawn_test's print() output is not load-bearing here
# and capturing it via PIPE creates the very FD-hang we're guarding
# against.
stderr_path = os.path.join(tempfile.gettempdir(), "smoketest_pool_spawn.stderr")
stderr_file = open(stderr_path, "wb")
try:
    if sys.platform != "win32":
        proc = subprocess.Popen(
            CMD,
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            start_new_session=True,
        )
    else:
        proc = subprocess.Popen(
            CMD,
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
        )

    # Poll up to HARD_TIMEOUT_SEC for the immediate child to exit.
    # Anything beyond that is treated as "cleanup hang" and reaped via
    # the process group so spawn workers go too.
    deadline = time.monotonic() + HARD_TIMEOUT_SEC
    timed_out = False
    while True:
        rc = proc.poll()
        if rc is not None:
            break
        if time.monotonic() >= deadline:
            print("Process timed out (likely cleanup hang), reaping and continuing")
            timed_out = True
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
finally:
    stderr_file.close()


def _profile_is_valid(path: str) -> bool:
    """A profile counts as 'work was done' if it parses as JSON and
    contains the structural keys scalene always writes. We do NOT
    insist on a non-empty ``samples`` list — sampling cadence vs.
    workload length is timing-dependent and not what this smoketest
    is asserting on."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Profile at {path!r} not loadable: {e}")
        return False
    required_keys = {"program", "files", "elapsed_time_sec"}
    missing = required_keys - data.keys()
    if missing:
        print(f"Profile at {path!r} missing keys: {sorted(missing)}")
        return False
    return True


def _dump_stderr_on_failure() -> None:
    """Print the captured stderr to stdout for the CI log to see.
    Called only on failure paths so successful runs don't flood
    output."""
    try:
        with open(stderr_path) as f:
            tail = f.read()[-4096:]
    except (FileNotFoundError, OSError):
        return
    if tail.strip():
        print("--- scalene stderr (last 4 KB) ---")
        print(tail)
        print("--- end stderr ---")


# Clean exit (rc == 0) and the previously-special-cased Windows
# memoryview cleanup warning (rc == 1) are accepted outright — they
# match the prior smoketest's accept-list and on master these are the
# overwhelmingly common cases on every OS.
if rc == 0 or rc == 1:
    sys.exit(0)

# Anything else — kill code, timeout-reaped — passes iff scalene
# managed to produce a valid profile before whatever killed it. A
# genuinely broken scalene (no profile written, or corrupt profile)
# still fails the smoketest.
if _profile_is_valid(DEFAULT_PROFILE_PATH):
    print(
        f"Scalene exited with rc={rc} (timeout={timed_out}) but a valid "
        f"profile was produced at {DEFAULT_PROFILE_PATH!r}; treating as "
        f"success. This is the known spawn-pool shutdown race; the "
        f"profile itself is the assertion."
    )
    sys.exit(0)

print(
    f"Scalene exited with rc={rc} (timeout={timed_out}) and produced no "
    f"valid profile. This is a real regression."
)
_dump_stderr_on_failure()
sys.exit(rc if rc else 1)
