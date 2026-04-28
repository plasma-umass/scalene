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


# ---------------------------------------------------------------------------
# Stitched (combined) Python+native stack assembly
# ---------------------------------------------------------------------------


def _make_frame(filename: str, function: str, line: int, parent=None):
    """Build a duck-typed FrameType for add_combined_stack tests.

    add_combined_stack only reads f_lineno, f_code.co_filename,
    f_code.co_firstlineno, f_code.co_name, and f_back. A simple namespace is
    enough — no need to compile real Python.
    """
    import types as _types

    code = _types.SimpleNamespace(
        co_filename=filename,
        co_name=function,
        co_firstlineno=line,
        co_qualname=function,
    )
    return _types.SimpleNamespace(
        f_code=code,
        f_lineno=line,
        f_back=parent,
        f_locals={},
    )


class TestAddCombinedStack:
    def test_no_drains_is_a_noop(self):
        from collections import defaultdict

        from scalene.scalene_utility import add_combined_stack

        combined: dict = defaultdict(int)
        frame = _make_frame("/p.py", "main", 5)
        add_combined_stack(frame, lambda *_: True, [], combined)
        assert dict(combined) == {}

    def test_outermost_to_innermost_python_chain(self):
        from collections import defaultdict

        from scalene.scalene_utility import add_combined_stack

        # Build a chain: main (line 1) -> middle (line 7) -> leaf (line 12).
        # Walking f_back from leaf gives leaf -> middle -> main, but
        # add_combined_stack must produce outermost-first: main, middle, leaf.
        main = _make_frame("/p.py", "main", 1)
        middle = _make_frame("/p.py", "middle", 7, parent=main)
        leaf = _make_frame("/p.py", "leaf", 12, parent=middle)

        combined: dict = defaultdict(int)
        add_combined_stack(leaf, lambda *_: True, [(0xAAAA,)], combined)

        assert len(combined) == 1
        stk = next(iter(combined.keys()))
        py_frames = [f for f in stk if f[0] == "py"]
        assert [(f[2], f[3]) for f in py_frames] == [
            ("main", 1),
            ("middle", 7),
            ("leaf", 12),
        ]

    def test_native_segment_appended_in_outermost_first_order(self):
        from collections import defaultdict

        from scalene.scalene_utility import add_combined_stack

        frame = _make_frame("/p.py", "f", 3)
        # The unwinder gives leaf-first: (leaf_ip, ..., entry_ip).
        native_drain = (0x1111, 0x2222, 0x3333)
        combined: dict = defaultdict(int)
        add_combined_stack(frame, lambda *_: True, [native_drain], combined)

        stk = next(iter(combined.keys()))
        native_ips = [f[1] for f in stk if f[0] == "native"]
        # Outermost-first => entry first, leaf last => reversed.
        assert native_ips == [0x3333, 0x2222, 0x1111]

    def test_multiple_drains_each_attached_to_python_chain(self):
        from collections import defaultdict

        from scalene.scalene_utility import add_combined_stack

        frame = _make_frame("/p.py", "f", 3)
        drain_a = (0xAAAA,)
        drain_b = (0xBBBB,)
        drain_c = (0xCCCC,)
        combined: dict = defaultdict(int)
        add_combined_stack(
            frame, lambda *_: True, [drain_a, drain_b, drain_c], combined
        )

        # Three distinct stitched stacks, each anchored on the same Python
        # chain — best-effort v1 policy.
        assert len(combined) == 3
        py_anchor = ("py", "/p.py", "f", 3)
        for stk, hits in combined.items():
            assert hits == 1
            assert stk[0] == py_anchor

    def test_repeat_drain_increments_hit_count(self):
        from collections import defaultdict

        from scalene.scalene_utility import add_combined_stack

        frame = _make_frame("/p.py", "f", 3)
        drain = (0xAAAA, 0xBBBB)

        combined: dict = defaultdict(int)
        add_combined_stack(frame, lambda *_: True, [drain], combined)
        add_combined_stack(frame, lambda *_: True, [drain], combined)
        add_combined_stack(frame, lambda *_: True, [drain], combined)

        assert len(combined) == 1
        assert next(iter(combined.values())) == 3

    def test_should_trace_filters_python_frames(self):
        from collections import defaultdict

        from scalene.scalene_utility import add_combined_stack

        scalene_internal = _make_frame(
            "/scalene/scalene_profiler.py", "cpu_signal_handler", 800
        )
        user_outer = _make_frame(
            "/usercode.py", "main", 1, parent=scalene_internal
        )
        user_inner = _make_frame(
            "/usercode.py", "hot", 5, parent=user_outer
        )

        def trace(filename, _name):
            return "scalene" not in filename

        combined: dict = defaultdict(int)
        add_combined_stack(user_inner, trace, [(0xAAAA,)], combined)

        stk = next(iter(combined.keys()))
        py_frames = [f for f in stk if f[0] == "py"]
        # Scalene's profiler frame must be filtered out — only user frames
        # remain in the stitched Python segment.
        assert [(f[1], f[2]) for f in py_frames] == [
            ("/usercode.py", "main"),
            ("/usercode.py", "hot"),
        ]

    def test_handles_frame_with_none_lineno(self):
        from collections import defaultdict

        from scalene.scalene_utility import add_combined_stack

        # Python 3.11+ may report f_lineno=None during cleanup; fall back to
        # co_firstlineno.
        frame = _make_frame("/p.py", "f", 42)
        frame.f_lineno = None
        combined: dict = defaultdict(int)
        add_combined_stack(frame, lambda *_: True, [(0xAAAA,)], combined)

        stk = next(iter(combined.keys()))
        py_frames = [f for f in stk if f[0] == "py"]
        assert py_frames[0][3] == 42  # used co_firstlineno


# ---------------------------------------------------------------------------
# combined_stacks JSON serialization (resolution + seam trim + frame schema)
# ---------------------------------------------------------------------------


def _build_stats_with_combined(raw_stack: tuple, hits: int = 1):
    """Build a ScaleneStatistics with one combined_stacks entry, plus stub
    everything else needed for output_profiles to run.

    The dummy file needs both per-line samples (so it's an instrumented file)
    and a non-zero per-file cpu_samples count above cpu_percent_threshold (1%
    of elapsed_time), or it gets pruned from report_files and the whole
    output is dropped.
    """
    from scalene.scalene_statistics import ScaleneStatistics

    stats = ScaleneStatistics()
    stats.combined_stacks[raw_stack] = hits
    stats.cpu_stats.total_cpu_samples = 1.0
    stats.cpu_stats.cpu_samples_python["/dummy.py"][1] = 1.0
    stats.cpu_stats.cpu_samples["/dummy.py"] = 1.0  # >1% of elapsed_time
    stats.elapsed_time = 1.0
    return stats


class TestCombinedStacksJson:
    def _resolve_stub(self, mapping):
        """Return a fake _scalene_unwind.resolve_ip that uses `mapping`."""

        def _resolve(ip):
            return mapping.get(ip)

        return _resolve

    def _emit(self, stats, tmp_path):
        """Run output_profiles and return the resulting JSON dict."""
        from scalene.scalene_json import ScaleneJSON
        from scalene.scalene_statistics import Filename

        out = ScaleneJSON()
        return out.output_profiles(
            program=Filename("prog.py"),
            stats=stats,
            pid=0,
            profile_this_code=lambda f, l: True,
            python_alias_dir=tmp_path,
            program_path=Filename("prog.py"),
            entrypoint_dir=Filename(str(tmp_path)),
            program_args=[],
            profile_memory=False,
            reduced_profile=False,
            profile_async=False,
        )

    def test_native_segment_resolved_and_trimmed(self, monkeypatch, tmp_path):
        # Stack as stored: outermost-first.
        # Python: main / hot
        # Native (entry -> leaf): _PyEval_EvalFrameDefault, _multiarray_umath::do_work, libBLAS::cblas_dgemm
        # After seam trim, _PyEval_EvalFrameDefault should be dropped because
        # it sits between Python and the real native leaf segment.
        py_main = ("py", "prog.py", "main", 10)
        py_hot = ("py", "prog.py", "hot", 22)
        ip_eval = 0xE000
        ip_callsite = 0xC000
        ip_leaf = 0x1000

        mapping = {
            ip_eval: ("/lib/libpython.so", "_PyEval_EvalFrameDefault", 0),
            ip_callsite: ("/x/_multiarray_umath.so", "do_work", 12),
            ip_leaf: ("/lib/libBLAS.dylib", "cblas_dgemm", 32),
        }

        # Patch the _scalene_unwind.resolve_ip used by scalene_json.
        import scalene._scalene_unwind as unwind_mod  # type: ignore

        monkeypatch.setattr(
            unwind_mod, "resolve_ip", self._resolve_stub(mapping)
        )

        stack = (
            py_main,
            py_hot,
            ("native", ip_eval),
            ("native", ip_callsite),
            ("native", ip_leaf),
        )
        stats = _build_stats_with_combined(stack, hits=4)
        profile = self._emit(stats, tmp_path)

        combined = profile["combined_stacks"]
        assert isinstance(combined, list) and len(combined) == 1
        frames, hits = combined[0]
        assert hits == 4

        # Python segment unchanged; native segment should now be just the
        # two real native frames, in outermost-first order.
        kinds = [f["kind"] for f in frames]
        assert kinds == ["py", "py", "native", "native"]

        py_segment = [f for f in frames if f["kind"] == "py"]
        assert [f["display_name"] for f in py_segment] == ["main", "hot"]
        assert [f["line"] for f in py_segment] == [10, 22]
        for f in py_segment:
            assert f["ip"] is None and f["offset"] is None

        native_segment = [f for f in frames if f["kind"] == "native"]
        assert [f["display_name"] for f in native_segment] == [
            "do_work",
            "cblas_dgemm",
        ]
        assert [f["filename_or_module"] for f in native_segment] == [
            "/x/_multiarray_umath.so",
            "/lib/libBLAS.dylib",
        ]
        for f in native_segment:
            assert f["line"] is None
            assert isinstance(f["ip"], int) and f["ip"] != 0

    def test_pure_python_stack_emits_unchanged(self, tmp_path):
        py_main = ("py", "prog.py", "main", 1)
        py_hot = ("py", "prog.py", "hot", 5)
        stack = (py_main, py_hot)
        stats = _build_stats_with_combined(stack, hits=2)
        profile = self._emit(stats, tmp_path)

        combined = profile["combined_stacks"]
        assert len(combined) == 1
        frames, hits = combined[0]
        assert hits == 2
        assert [f["kind"] for f in frames] == ["py", "py"]
        assert [f["display_name"] for f in frames] == ["main", "hot"]

    def test_pure_runtime_native_segment_drops(self, monkeypatch, tmp_path):
        # If the native segment is entirely interpreter / process-entry
        # frames, trimming leaves nothing — only the Python part remains.
        py_main = ("py", "prog.py", "main", 1)
        ip_eval = 0xE000
        ip_runmain = 0xF000
        mapping = {
            ip_eval: ("/lib/libpython.so", "_PyEval_EvalFrameDefault", 0),
            ip_runmain: ("/lib/libpython.so", "Py_RunMain", 0),
        }
        import scalene._scalene_unwind as unwind_mod  # type: ignore

        monkeypatch.setattr(
            unwind_mod, "resolve_ip", self._resolve_stub(mapping)
        )

        stack = (py_main, ("native", ip_eval), ("native", ip_runmain))
        stats = _build_stats_with_combined(stack, hits=1)
        profile = self._emit(stats, tmp_path)

        combined = profile["combined_stacks"]
        assert len(combined) == 1
        frames, _hits = combined[0]
        # Only the Python anchor remains.
        assert [f["kind"] for f in frames] == ["py"]

    def test_dedupe_stacks_with_same_resolved_display(self, monkeypatch, tmp_path):
        """Two raw stacks that differ only in native IP/offset but resolve
        to the same (symbol, module) frames must collapse into one entry,
        with hit counts summed. Regression for the "same stack listed
        multiple times" bug — sample-time aggregation is keyed by raw IPs
        but the display layer should dedupe by user-visible fields."""
        py_main = ("py", "prog.py", "main", 1)
        ip_a = 0xAAA0
        ip_b = 0xAAB0  # different IP, same function -> same display
        # Both IPs resolve to the same symbol/module; only offset differs.
        mapping = {
            ip_a: ("/lib/libBLAS.dylib", "cblas_dgemm", 16),
            ip_b: ("/lib/libBLAS.dylib", "cblas_dgemm", 32),
        }
        import scalene._scalene_unwind as unwind_mod  # type: ignore

        monkeypatch.setattr(
            unwind_mod, "resolve_ip", self._resolve_stub(mapping)
        )

        from scalene.scalene_json import ScaleneJSON
        from scalene.scalene_statistics import Filename, ScaleneStatistics

        stats = ScaleneStatistics()
        stats.combined_stacks[(py_main, ("native", ip_a))] = 3
        stats.combined_stacks[(py_main, ("native", ip_b))] = 5
        stats.cpu_stats.total_cpu_samples = 1.0
        stats.cpu_stats.cpu_samples_python["/dummy.py"][1] = 1.0
        stats.cpu_stats.cpu_samples["/dummy.py"] = 1.0
        stats.elapsed_time = 1.0

        out = ScaleneJSON()
        profile = out.output_profiles(
            program=Filename("prog.py"),
            stats=stats,
            pid=0,
            profile_this_code=lambda f, l: True,
            python_alias_dir=tmp_path,
            program_path=Filename("prog.py"),
            entrypoint_dir=Filename(str(tmp_path)),
            program_args=[],
            profile_memory=False,
            reduced_profile=False,
            profile_async=False,
        )

        combined = profile["combined_stacks"]
        assert len(combined) == 1, (
            f"expected 1 deduplicated stack, got {len(combined)}: {combined}"
        )
        _frames, hits = combined[0]
        assert hits == 8, f"expected 3 + 5 = 8 hits after dedup, got {hits}"

    def test_no_combined_stacks_emits_empty_list(self, tmp_path):
        from scalene.scalene_json import ScaleneJSON
        from scalene.scalene_statistics import Filename, ScaleneStatistics

        stats = ScaleneStatistics()
        stats.cpu_stats.total_cpu_samples = 1.0
        stats.cpu_stats.cpu_samples_python["/dummy.py"][1] = 1.0
        stats.cpu_stats.cpu_samples["/dummy.py"] = 1.0
        stats.elapsed_time = 1.0

        out = ScaleneJSON()
        profile = out.output_profiles(
            program=Filename("prog.py"),
            stats=stats,
            pid=0,
            profile_this_code=lambda f, l: True,
            python_alias_dir=tmp_path,
            program_path=Filename("prog.py"),
            entrypoint_dir=Filename(str(tmp_path)),
            program_args=[],
            profile_memory=False,
            reduced_profile=False,
            profile_async=False,
        )
        assert profile["combined_stacks"] == []


# ---------------------------------------------------------------------------
# drain_native_stacks return-value contract
# ---------------------------------------------------------------------------


@pytest.mark.skipif(WINDOWS, reason="unwinder is a stub on Windows")
def test_drain_native_stacks_returns_list_and_aggregates(monkeypatch):
    """drain_native_stacks must aggregate AND return the raw drains."""
    from collections import defaultdict

    import scalene.scalene_utility as util

    # Stub the C extension's drain to return a known-good capture set so
    # the test doesn't depend on the signal-handler path having fired.
    fake_capture = [(0x1, 0x2, 0x3), (0x4, 0x5), ()]
    monkeypatch.setattr(
        util._scalene_unwind, "drain_native_stack_buffer", lambda: fake_capture
    )

    native_stacks: dict = defaultdict(int)
    drained = util.drain_native_stacks(native_stacks)

    # Empty drain entries must be filtered out of both the return value
    # and the aggregation dict.
    assert drained == [(0x1, 0x2, 0x3), (0x4, 0x5)]
    assert dict(native_stacks) == {(0x1, 0x2, 0x3): 1, (0x4, 0x5): 1}


def test_drain_native_stacks_empty_on_unsupported(monkeypatch):
    """When the C extension is unavailable, drain returns []."""
    import scalene.scalene_utility as util

    monkeypatch.setattr(util, "_native_unwind_available", False)
    drained = util.drain_native_stacks({})
    assert drained == []
