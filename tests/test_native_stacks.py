"""Tests for native (C/C++) stack collection (PR #1034).

Covers the test-plan items beyond "CI green":
- The `_scalene_unwind` extension is importable on every platform; its
  `available` flag matches the platform (1 on Linux/macOS, 0 on Windows).
- With `--stacks`, a CPU-bound workload populates `native_stacks` with
  well-formed (module, symbol, ip, offset) entries.
- Without `--stacks` (the default), `native_stacks` is empty — i.e. no
  C-level signal handler is installed and no buffer is drained.
- The existing Python `stacks` output is still emitted alongside
  `native_stacks` and is non-empty.

Each subprocess test runs Scalene end-to-end, so they're slower than the
unit tests (~10-30s). They sleep-pad the workload to ~2s so timer signals
have time to fire on loaded CI machines.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


WINDOWS = sys.platform == "win32"

# Workload chosen to be long enough that the CPU sampling timer fires many
# times, regardless of whether the timer is virtual (counts CPU time) or
# real (counts wall time). 2 seconds is a comfortable margin even on slow
# CI machines.
_WORKLOAD = textwrap.dedent("""
    import math
    import time

    def hot():
        s = 0.0
        end = time.monotonic() + 2.0
        while time.monotonic() < end:
            for i in range(200_000):
                s += math.sqrt(i * 1.234) * math.sin(i * 0.001)
        return s

    if __name__ == "__main__":
        print(hot())
""")


def _run_scalene(tmp_path: Path, *extra_args: str) -> dict:
    """Run scalene on the workload, return the parsed JSON profile."""
    workload = tmp_path / "workload.py"
    workload.write_text(_WORKLOAD)
    out = tmp_path / "profile.json"
    cmd = [
        sys.executable,
        "-m",
        "scalene",
        "run",
        "--cpu-only",
        "--json",
        "--outfile",
        str(out),
        *extra_args,
        str(workload),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    assert proc.returncode == 0, (
        f"scalene exited {proc.returncode}\n"
        f"stdout: {proc.stdout.decode(errors='replace')}\n"
        f"stderr: {proc.stderr.decode(errors='replace')}"
    )
    assert out.exists(), "scalene did not produce a profile JSON"
    return json.loads(out.read_text())


def test_extension_importable_with_correct_availability_flag():
    """The extension imports on every platform; `available` reflects backend."""
    from scalene import _scalene_unwind

    expected = 0 if WINDOWS else 1
    assert _scalene_unwind.available == expected, (
        f"expected available={expected} on {sys.platform}, "
        f"got {_scalene_unwind.available}"
    )


def test_extension_exposes_required_methods():
    """The Python-facing API is the surface scalene_utility expects."""
    from scalene import _scalene_unwind

    for name in (
        "unwind_native_stack",
        "resolve_ip",
        "warmup",
        "install_signal_unwinder",
        "drain_native_stack_buffer",
    ):
        assert hasattr(_scalene_unwind, name), f"missing API: {name}"


@pytest.mark.skipif(
    WINDOWS, reason="--stacks native unwinder not implemented on Windows"
)
def test_stacks_populates_native_stacks(tmp_path):
    """`--stacks` should produce well-formed native stack entries."""
    profile = _run_scalene(tmp_path, "--stacks")

    native = profile.get("native_stacks")
    assert isinstance(native, list), (
        "expected native_stacks key with a list value"
    )
    assert len(native) > 0, (
        "expected --stacks + a CPU-bound workload to populate native_stacks; "
        "got an empty list"
    )

    # Each entry is (frames, hits) where each frame is
    # [module, symbol, ip, offset]. Symbol/module may be empty strings if
    # dladdr couldn't resolve the IP, but the structure must hold.
    for entry in native:
        assert isinstance(entry, list) and len(entry) == 2
        frames, hits = entry
        assert isinstance(hits, int) and hits >= 1
        assert isinstance(frames, list) and len(frames) >= 1
        for frame in frames:
            assert isinstance(frame, list) and len(frame) == 4
            module, symbol, ip, offset = frame
            assert isinstance(module, str)
            assert isinstance(symbol, str)
            assert isinstance(ip, int) and ip > 0
            assert isinstance(offset, int)


@pytest.mark.skipif(
    WINDOWS, reason="--stacks native unwinder not implemented on Windows"
)
def test_stacks_preserves_python_stacks_output(tmp_path):
    """Adding `--stacks` must not regress the existing Python `stacks` field."""
    profile = _run_scalene(tmp_path, "--stacks")
    py_stacks = profile.get("stacks")
    assert isinstance(py_stacks, list), "stacks key missing or wrong type"
    assert len(py_stacks) > 0, (
        "Python stacks should still be populated under --stacks"
    )


def test_no_stacks_flag_yields_empty_native_stacks(tmp_path):
    """Default (no --stacks) must not install handlers or emit native frames."""
    profile = _run_scalene(tmp_path)
    # The key may exist for schema stability, but it must be empty.
    assert profile.get("native_stacks", []) == [], (
        "Expected native_stacks to be empty without --stacks; got "
        f"{len(profile.get('native_stacks', []))} entries"
    )
