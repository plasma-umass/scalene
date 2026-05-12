#!/usr/bin/env python3
"""Smoketest for pytest-xdist + ``--profile-all`` (regression for #1022).

Workers spawned by pytest-xdist inherit a sigmask that, in combination
with Scalene's ``patch_module_functions_with_signal_blocking`` shim
(issue #841), used to land with Scalene's CPU sampling signal blocked.
The setitimer fires, but the handler never runs, so each worker
collects zero samples; the parent then merges nothing and the user's
code is absent from the profile while ``"did not run for long enough"``
warnings print twice (once per worker).

This smoketest reproduces the exact shape: ``-n 2`` workers running a
CPU-busy fixture under ``--profile-all``. It asserts that the user's
source file appears in the merged profile. Pre-fix on Linux 3.13 the
profile contains only stdlib/execnet; post-fix it contains the fixture
source.

Linux-only: macOS and Windows did not exhibit the bug in the wild
(macOS goes through a different path that doesn't leak the sigmask
across subprocess fork; Windows doesn't use the LD_PRELOAD/sigmask
machinery at all).
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap

if sys.platform != "linux":
    print(f"skipping issue-1022 smoketest on {sys.platform}: bug is Linux-only")
    sys.exit(0)

# Install pytest-xdist into the running environment if missing. The
# smoketest workflow already installs scalene + numpy; xdist is the
# only extra requirement and pinning it isn't worth a separate step.
try:
    import xdist  # noqa: F401
except ImportError:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", "pytest-xdist"]
    )

workdir = tempfile.mkdtemp(prefix="scalene-1022-")
src_dir = os.path.join(workdir, "src")
os.makedirs(src_dir, exist_ok=True)

# Fixture: a CPU-busy function the workers will run. Each test calls it
# with 10M iterations so even on slow runners there is more than enough
# wall-clock time for the timer to fire many times per worker.
with open(os.path.join(src_dir, "__init__.py"), "w") as f:
    f.write(
        textwrap.dedent(
            """
            def crunch(n):
                total = 0
                for i in range(n):
                    total += i * i
                return total
            """
        ).lstrip()
    )

with open(os.path.join(workdir, "test_heavy.py"), "w") as f:
    f.write(
        textwrap.dedent(
            """
            from src import crunch

            def test_a():
                assert crunch(10_000_000) > 0

            def test_b():
                assert crunch(10_000_000) > 0

            def test_c():
                assert crunch(10_000_000) > 0

            def test_d():
                assert crunch(10_000_000) > 0
            """
        ).lstrip()
    )

profile_path = os.path.join(workdir, "issue1022.json")
cmd = [
    sys.executable,
    "-m",
    "scalene",
    "run",
    "--profile-all",
    "-o",
    profile_path,
    "---",
    "-m",
    "pytest",
    "-n",
    "2",
    "test_heavy.py",
]
print("COMMAND", " ".join(cmd))
proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=180)
print(proc.stdout)
print(proc.stderr, file=sys.stderr)

if proc.returncode != 0:
    print(f"scalene exited with rc={proc.returncode}")
    sys.exit(proc.returncode)

if not os.path.exists(profile_path):
    print(f"No profile produced at {profile_path}")
    sys.exit(1)

with open(profile_path) as f:
    data = json.load(f)

files = data.get("files", {})
if not files:
    print("Profile has empty 'files' dict — issue #1022 regression")
    sys.exit(1)

# The fixture lives in workdir; the entry we expect to see is
# "<workdir>/src/__init__.py" since that's where ``crunch`` runs. We
# match by path suffix to stay tolerant of symlinked tmpdirs.
user_file_suffix = os.path.join("src", "__init__.py")
matching = [name for name in files if name.endswith(user_file_suffix)]
if not matching:
    print(
        f"User-code file (...{user_file_suffix}) absent from profile. "
        f"Files present: {sorted(files)}"
    )
    sys.exit(1)

print(
    f"OK: issue #1022 fix holds. Profiled {len(files)} files, "
    f"user code at {matching[0]!r}, elapsed={data.get('elapsed_time_sec'):.2f}s"
)
sys.exit(0)
