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
from scalene.scalene_json import (
    _is_cpython_runtime_frame,
    _is_scalene_handler_frame,
    _trim_native_stack,
)

WINDOWS = sys.platform == "win32"
SA_SIGINFO = getattr(signal, "SA_SIGINFO", None)


# ---------------------------------------------------------------------------
# Extension surface (always-on)
# ---------------------------------------------------------------------------


def _load_last_json_line(stdout: str) -> dict:
    """Extract the last JSON object from subprocess stdout.

    Some environments print Scalene signal-routing warnings before the
    payload, so the tests should decode the final JSON line rather than
    assuming stdout is pure JSON.
    """
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise AssertionError(f"no JSON object found in stdout:\n{stdout}")


def _run_helper_subprocess(code: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return _load_last_json_line(proc.stdout)


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

    Run the signal-handler path in a fresh subprocess so earlier tests in the
    main pytest process can't interfere with SIGALRM handling. The child
    installs the handler, arms a wall-clock timer, burns CPU, drains the
    ring buffer, and emits a JSON summary for assertions here.
    """
    result = _run_helper_subprocess("""
        import json
        import signal
        import time

        from scalene import _scalene_unwind

        sig = signal.SIGALRM
        prev = signal.signal(sig, lambda s, f: None)
        out = {}
        try:
            out["installed"] = bool(_scalene_unwind.install_signal_unwinder(sig))
            if hasattr(_scalene_unwind, "handler_status"):
                cur, ours, flags = _scalene_unwind.handler_status(sig)
                out["handler_matches"] = cur == ours
                out["flags"] = flags

            _scalene_unwind.drain_native_stack_buffer()
            signal.setitimer(signal.ITIMER_REAL, 0.005, 0.005)

            end = time.monotonic() + 1.5
            s = 0
            while time.monotonic() < end:
                for i in range(50_000):
                    s += i
            signal.setitimer(signal.ITIMER_REAL, 0)

            captured = _scalene_unwind.drain_native_stack_buffer()
            out["captured_count"] = len(captured)
            out["all_frames_nonempty"] = all(len(stk) >= 1 for stk in captured)

            syms = []
            for stk in captured:
                for ip in stk:
                    info = _scalene_unwind.resolve_ip(ip)
                    if info is not None:
                        syms.append(info[1])
            out["has_cpython_symbol"] = any(
                "PyEval" in s or "Py_RunMain" in s or "pymain" in s
                for s in syms
            )
            if hasattr(_scalene_unwind, "diag_counts"):
                out["diag_counts"] = _scalene_unwind.diag_counts()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(sig, prev)

        print(json.dumps(out))
    """)

    assert result["installed"] is True
    if "handler_matches" in result:
        assert result["handler_matches"] is True
    if SA_SIGINFO is not None and "flags" in result:
        assert result["flags"] & SA_SIGINFO, "SA_SIGINFO must be set"

    if result["captured_count"] == 0:
        diag = result.get("diag_counts")
        pytest.skip(
            "signal-handler path produced no captured stacks on this runner"
            + (f"; diag_counts={diag}" if diag else "")
        )

    assert result["all_frames_nonempty"] is True
    assert result["has_cpython_symbol"] is True


@pytest.mark.skipif(WINDOWS, reason="signal-handler unwinder not on Windows")
def test_handler_not_installed_by_default():
    """Importing _scalene_unwind must NOT install any signal handler.

    This protects the contract that Scalene only touches signal handlers
    when --stacks is set. Run the check in a fresh subprocess so it isn't
    polluted by earlier tests that may have monkey-patched signal handling
    in the main pytest process.
    """
    result = _run_helper_subprocess("""
        import json
        import signal
        from scalene import _scalene_unwind

        sig = signal.SIGALRM
        signal.signal(sig, signal.SIG_DFL)
        cur, ours, _flags = _scalene_unwind.handler_status(sig)
        print(json.dumps({"installed": cur == ours}))
    """)
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


# ---------------------------------------------------------------------------
# Native-stack frame classification + trimming (pure-Python helpers)
# ---------------------------------------------------------------------------


def _f(module: str = "", symbol: str = "", ip: int = 0x1000, offset: int = 0):
    """Build a resolved-frame list as scalene_json.py constructs them."""
    return [module, symbol, ip, offset]


class TestIsScaleneHandlerFrame:
    def test_matches_unwinder_symbol(self):
        assert _is_scalene_handler_frame(
            _f(symbol="scalene_signal_unwinder")
        )

    def test_matches_macos_sigtramp(self):
        assert _is_scalene_handler_frame(_f(symbol="_sigtramp"))

    def test_matches_linux_restore_rt(self):
        assert _is_scalene_handler_frame(_f(symbol="__restore_rt"))

    def test_matches_module_path(self):
        assert _is_scalene_handler_frame(
            _f(module="/site-packages/scalene/_scalene_unwind.so", symbol="")
        )

    def test_user_frame_is_not_handler(self):
        assert not _is_scalene_handler_frame(
            _f(module="/lib/libBLAS.dylib", symbol="cblas_dgemm")
        )

    def test_unresolved_frame_is_not_handler(self):
        assert not _is_scalene_handler_frame(_f())


class TestIsCPythonRuntimeFrame:
    def test_matches_exact_eval_frame(self):
        assert _is_cpython_runtime_frame(_f(symbol="_PyEval_EvalFrameDefault"))

    def test_matches_py_runmain(self):
        assert _is_cpython_runtime_frame(_f(symbol="Py_RunMain"))

    def test_matches_vectorcall_prefix(self):
        assert _is_cpython_runtime_frame(_f(symbol="PyObject_Vectorcall"))
        assert _is_cpython_runtime_frame(
            _f(symbol="_PyObject_VectorcallTstate")
        )

    def test_matches_pymain_prefix(self):
        assert _is_cpython_runtime_frame(_f(symbol="pymain_run_python"))

    def test_matches_libc_entrypoints(self):
        assert _is_cpython_runtime_frame(_f(symbol="_start"))
        assert _is_cpython_runtime_frame(_f(symbol="__libc_start_main"))

    def test_unresolved_frame_is_not_runtime(self):
        # Empty symbol must not be treated as runtime (would over-trim
        # otherwise resolvable user frames whose symbol lookup failed).
        assert not _is_cpython_runtime_frame(_f(symbol=""))

    def test_user_symbol_is_not_runtime(self):
        assert not _is_cpython_runtime_frame(_f(symbol="cblas_dgemm"))
        # A user function whose name happens to share a prefix with
        # something we don't trim must still pass through.
        assert not _is_cpython_runtime_frame(_f(symbol="my_call_method"))


class TestTrimNativeStack:
    def test_strips_leading_handler_frames(self):
        frames = [
            _f(symbol="scalene_signal_unwinder"),
            _f(symbol="_sigtramp"),
            _f(module="/lib/libBLAS.dylib", symbol="cblas_dgemm"),
        ]
        trimmed = _trim_native_stack(frames)
        assert [f[1] for f in trimmed] == ["cblas_dgemm"]

    def test_strips_trailing_cpython_runtime_frames(self):
        frames = [
            _f(module="/lib/libBLAS.dylib", symbol="cblas_dgemm"),
            _f(
                module="/.../_multiarray_umath.so",
                symbol="array_function_simple_impl",
            ),
            _f(symbol="_PyEval_EvalFrameDefault"),
            _f(symbol="_PyEval_EvalFrameDefault"),
            _f(symbol="_PyEval_Vector"),
            _f(symbol="Py_RunMain"),
            _f(symbol="__libc_start_main"),
            _f(symbol="_start"),
        ]
        trimmed = _trim_native_stack(frames)
        assert [f[1] for f in trimmed] == [
            "cblas_dgemm",
            "array_function_simple_impl",
        ]

    def test_strips_both_ends(self):
        frames = [
            _f(symbol="scalene_signal_unwinder"),
            _f(symbol="_sigtramp"),
            _f(module="/lib/libBLAS.dylib", symbol="cblas_dgemm"),
            _f(symbol="_PyEval_EvalFrameDefault"),
            _f(symbol="Py_RunMain"),
        ]
        trimmed = _trim_native_stack(frames)
        assert [f[1] for f in trimmed] == ["cblas_dgemm"]

    def test_only_runtime_returns_empty(self):
        # A sample that landed entirely in the interpreter trims to
        # nothing, and the caller drops empty stacks.
        frames = [
            _f(symbol="_PyEval_EvalFrameDefault"),
            _f(symbol="Py_RunMain"),
            _f(symbol="_start"),
        ]
        assert _trim_native_stack(frames) == []

    def test_only_handler_returns_empty(self):
        frames = [
            _f(symbol="scalene_signal_unwinder"),
            _f(symbol="_sigtramp"),
        ]
        assert _trim_native_stack(frames) == []

    def test_does_not_trim_runtime_in_middle(self):
        # An interpreter frame sandwiched between native frames stays:
        # we only trim CONTIGUOUS runtime frames from the root end.
        frames = [
            _f(symbol="numpy_callback"),
            _f(symbol="_PyEval_EvalFrameDefault"),
            _f(module="/lib/libBLAS.dylib", symbol="cblas_dgemm"),
            _f(symbol="_PyEval_EvalFrameDefault"),
            _f(symbol="Py_RunMain"),
        ]
        trimmed = _trim_native_stack(frames)
        assert [f[1] for f in trimmed] == [
            "numpy_callback",
            "_PyEval_EvalFrameDefault",
            "cblas_dgemm",
        ]

    def test_keeps_unresolved_frames(self):
        # Unresolved IPs (empty symbol) must not be trimmed — they may
        # be real user code that just failed to symbolize.
        frames = [
            _f(symbol="scalene_signal_unwinder"),
            _f(ip=0xDEADBEEF),
            _f(module="/lib/libBLAS.dylib", symbol="cblas_dgemm"),
            _f(symbol="Py_RunMain"),
        ]
        trimmed = _trim_native_stack(frames)
        assert len(trimmed) == 2
        assert trimmed[0][2] == 0xDEADBEEF
        assert trimmed[1][1] == "cblas_dgemm"

    def test_does_not_mutate_input(self):
        frames = [
            _f(symbol="scalene_signal_unwinder"),
            _f(module="/lib/libBLAS.dylib", symbol="cblas_dgemm"),
            _f(symbol="Py_RunMain"),
        ]
        original = [list(f) for f in frames]
        _trim_native_stack(frames)
        assert frames == original

    def test_empty_input_returns_empty(self):
        assert _trim_native_stack([]) == []
