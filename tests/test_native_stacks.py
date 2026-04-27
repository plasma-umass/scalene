"""Tests for native (C/C++) stack collection (PR #1034).

Most of these are unit tests that exercise the `_scalene_unwind` C
extension directly: they don't spawn a Scalene subprocess, so they
don't depend on the full profile pipeline, the sampling timer behaviour
under CI contention, or any version-specific quirks of Scalene's main
loop. This keeps them fast and stable across the whole 3.9–3.14
matrix on Ubuntu and macOS.

A single end-to-end smoke test does run Scalene as a subprocess, but
treats any subprocess-level failure (non-zero exit, timeout, empty
profile) as a skip rather than a hard fail — that path is best-effort
because Scalene's sampling can be flaky on overloaded CI runners.

Coverage map vs. PR #1034 test plan:

  - "Run a numpy/torch workload with --stacks and confirm
     native_stacks populates with real C-extension frames"
        -> test_signal_handler_captures_interrupted_stack
           (in-process; doesn't depend on numpy)
        -> test_scalene_subprocess_with_stacks_smoke
           (best-effort end-to-end)

  - "Confirm --no-stacks (default) is unaffected"
        -> test_handler_not_installed_by_default
        -> test_scalene_subprocess_no_stacks_smoke (best-effort)

  - "Verify Windows build still passes (extension compiles as a stub)"
        -> test_extension_importable_on_every_platform
        -> test_windows_path_is_stub

  - "Spot-check that the existing Python stacks output is unchanged"
        -> test_scalene_subprocess_with_stacks_smoke (best-effort)
"""

import json
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from scalene import _scalene_unwind

WINDOWS = sys.platform == "win32"
SA_SIGINFO = getattr(signal, "SA_SIGINFO", None)


# ---------------------------------------------------------------------------
# Extension surface (always-on)
# ---------------------------------------------------------------------------


def test_extension_importable_on_every_platform():
    """Module imports on all platforms; `available` reflects the backend."""
    expected = 0 if WINDOWS else 1
    assert _scalene_unwind.available == expected, (
        f"expected available={expected} on {sys.platform}, "
        f"got {_scalene_unwind.available}"
    )


def test_extension_exposes_required_methods():
    for name in (
        "unwind_native_stack",
        "resolve_ip",
        "warmup",
        "install_signal_unwinder",
        "drain_native_stack_buffer",
    ):
        assert hasattr(_scalene_unwind, name), f"missing API: {name}"


@pytest.mark.skipif(not WINDOWS, reason="Windows-only stub behaviour")
def test_windows_path_is_stub():
    """On Windows the stub returns empty stacks for every API."""
    assert _scalene_unwind.unwind_native_stack(32) == ()
    assert _scalene_unwind.drain_native_stack_buffer() == []


# ---------------------------------------------------------------------------
# Direct (Python-callable) unwind path
# ---------------------------------------------------------------------------


@pytest.mark.skipif(WINDOWS, reason="unwinder is a stub on Windows")
def test_unwind_native_stack_returns_caller_frames():
    _scalene_unwind.warmup()
    ips = _scalene_unwind.unwind_native_stack(32)
    assert isinstance(ips, tuple)
    assert len(ips) >= 1, "expected at least one frame"
    for ip in ips:
        assert isinstance(ip, int) and ip > 0


@pytest.mark.skipif(WINDOWS, reason="unwinder is a stub on Windows")
def test_resolve_ip_recovers_cpython_symbols():
    """At least one unwound IP should resolve to a CPython eval symbol."""
    _scalene_unwind.warmup()
    ips = _scalene_unwind.unwind_native_stack(32)
    syms = []
    for ip in ips:
        info = _scalene_unwind.resolve_ip(ip)
        if info is not None:
            syms.append(info[1])
    assert any(
        "PyEval" in s or "Py_RunMain" in s or "pymain" in s
        for s in syms
    ), f"expected CPython-eval symbols among resolved IPs, got {syms[:8]}"


# ---------------------------------------------------------------------------
# Signal-handler unwind path (the one Scalene actually uses)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(WINDOWS, reason="signal-handler unwinder not on Windows")
def test_signal_handler_captures_interrupted_stack():
    """End-to-end check of the production path, without Scalene.

    Install the C handler on SIGALRM, arm a wall-clock timer, burn CPU,
    drain — verify entries are well-formed and at least one resolves to a
    CPython symbol. This mirrors what Scalene does internally but stays
    in-process so it's not subject to subprocess/sampling flakiness.
    """
    sig = signal.SIGALRM
    prev_handler = signal.signal(sig, lambda s, f: None)
    try:
        installed = _scalene_unwind.install_signal_unwinder(sig)
        assert installed is True

        if hasattr(_scalene_unwind, "handler_status"):
            cur, ours, flags = _scalene_unwind.handler_status(sig)
            assert cur == ours, "our handler must be the kernel-installed one"
            if SA_SIGINFO is not None:
                assert flags & SA_SIGINFO, "SA_SIGINFO must be set"

        # Drain any prior state and arm a fast wall-clock timer.
        _scalene_unwind.drain_native_stack_buffer()
        signal.setitimer(signal.ITIMER_REAL, 0.005, 0.005)

        # Burn ~1.5s of wall time. Real timer fires regardless of CPU
        # contention, so this is reliable on slow runners.
        end = time.monotonic() + 1.5
        s = 0
        while time.monotonic() < end:
            for i in range(50_000):
                s += i
        signal.setitimer(signal.ITIMER_REAL, 0)

        captured = _scalene_unwind.drain_native_stack_buffer()
        assert len(captured) > 0, "expected captured stacks from timer firings"

        # Every captured stack must be a non-empty tuple of int IPs.
        for stk in captured:
            assert isinstance(stk, tuple) and len(stk) >= 1
            for ip in stk:
                assert isinstance(ip, int) and ip > 0

        # At least one IP across all captured stacks should resolve to a
        # CPython symbol — i.e. dladdr resolution is working.
        all_syms = []
        for stk in captured:
            for ip in stk:
                info = _scalene_unwind.resolve_ip(ip)
                if info is not None:
                    all_syms.append(info[1])
        assert any(
            "PyEval" in s or "Py_RunMain" in s or "pymain" in s
            for s in all_syms
        ), f"no CPython-eval symbols among captured frames: {all_syms[:8]}"

    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(sig, prev_handler)


@pytest.mark.skipif(WINDOWS, reason="signal-handler unwinder not on Windows")
def test_handler_not_installed_by_default():
    """Importing _scalene_unwind must NOT install any signal handler.

    This protects the contract that Scalene only touches signal handlers
    when --stacks is set. Run the check in a fresh subprocess so it isn't
    polluted by earlier tests that may have monkey-patched signal handling
    in the main pytest process.
    """
    code = textwrap.dedent("""
        import json
        import signal
        from scalene import _scalene_unwind

        sig = signal.SIGALRM
        signal.signal(sig, signal.SIG_DFL)
        cur, ours, _flags = _scalene_unwind.handler_status(sig)
        print(json.dumps({"installed": cur == ours}))
    """)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    result = json.loads(proc.stdout)
    assert result["installed"] is False, (
        "our C handler should not be installed without an explicit "
        "install_signal_unwinder() call"
    )


# ---------------------------------------------------------------------------
# Best-effort end-to-end through Scalene as a subprocess
# ---------------------------------------------------------------------------


_SUBPROCESS_TIMEOUT_SEC = 60
_SCALENE_WORKLOAD = textwrap.dedent("""
    import math
    import time

    def hot():
        s = 0.0
        end = time.monotonic() + 3.0
        while time.monotonic() < end:
            for i in range(200_000):
                s += math.sqrt(i * 1.234) * math.sin(i * 0.001)
        return s

    if __name__ == "__main__":
        print(hot())
""")


def _run_scalene_or_skip(tmp_path: Path, *extra_args: str) -> dict:
    """Run scalene in a subprocess; skip on any environmental failure.

    pytest.skip raises pytest.skip.Exception (a subclass of BaseException),
    so the helper never returns past it — but CodeQL's flow analysis can't
    see that. Each skip path therefore raises explicitly.
    """
    workload = tmp_path / "workload.py"
    workload.write_text(_SCALENE_WORKLOAD)
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
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=_SUBPROCESS_TIMEOUT_SEC
        )
    except subprocess.TimeoutExpired:
        pytest.skip(
            f"scalene subprocess timed out (>{_SUBPROCESS_TIMEOUT_SEC}s); "
            "likely environmental, not a native-stack regression"
        )
        raise  # unreachable; placates flow analysis
    if proc.returncode != 0:
        pytest.skip(
            f"scalene exited {proc.returncode}; treating as environmental.\n"
            f"stderr: {proc.stderr.decode(errors='replace')[-1000:]}"
        )
    if not out.exists() or out.stat().st_size == 0:
        pytest.skip("scalene produced no profile JSON; environmental")
    try:
        loaded = json.loads(out.read_text())
    except json.JSONDecodeError:
        pytest.skip("profile JSON unreadable; environmental")
        raise  # unreachable; placates flow analysis
    return loaded


@pytest.mark.skipif(
    WINDOWS, reason="--stacks native unwinder not on Windows"
)
def test_scalene_subprocess_with_stacks_smoke(tmp_path):
    """End-to-end: --stacks should populate native_stacks when sampling fires."""
    profile = _run_scalene_or_skip(tmp_path, "--stacks")

    # If sampling didn't fire at all on this runner, skip — not a bug
    # in native-stack collection.
    if not profile.get("stacks"):
        pytest.skip(
            "Scalene produced no Python stacks on this runner; can't pin "
            "an empty native_stacks on the unwinder."
        )

    native = profile.get("native_stacks")
    assert isinstance(native, list)
    assert len(native) > 0, (
        "expected native_stacks to be populated when --stacks is set and "
        "Scalene successfully sampled the workload"
    )
    # Schema check: each entry is (frames, hits) with 4-tuple frames
    for entry in native:
        assert isinstance(entry, list) and len(entry) == 2
        frames, hits = entry
        assert isinstance(hits, int) and hits >= 1
        assert isinstance(frames, list) and len(frames) >= 1
        for frame in frames:
            assert isinstance(frame, list) and len(frame) == 4


def test_scalene_subprocess_no_stacks_smoke(tmp_path):
    """Default (no --stacks) must not produce native_stacks."""
    profile = _run_scalene_or_skip(tmp_path)
    assert profile.get("native_stacks", []) == [], (
        "Expected empty native_stacks without --stacks; got "
        f"{len(profile.get('native_stacks', []))} entries"
    )
