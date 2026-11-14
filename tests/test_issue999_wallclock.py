"""Regression test for issue #999: Wall clock mode Python/Native attribution.

Issue: https://github.com/plasma-umass/scalene/issues/999

In wall clock mode, numpy-heavy code was incorrectly showing ~15-20% Python time
for lines that should be nearly 100% native (C extension) time. The fix uses
instruction-based detection (checking if we're at a CALL opcode) instead of
the interval-based formula which doesn't work in wall clock mode.
"""

import os
import sys
import threading
from unittest.mock import MagicMock

import pytest

from scalene.scalene_cpu_profiler import ScaleneCPUProfiler
from scalene.scalene_funcutils import ScaleneFuncUtils
from scalene.scalene_statistics import (
    Filename,
    LineNumber,
    ScaleneStatistics,
)
from scalene.time_info import TimeInfo


# ---------------------------------------------------------------------------
# Test workload: simulates a C extension call (like numpy.tensordot)
# ---------------------------------------------------------------------------

_TEST_SOURCE = """\
def numpy_like_workload(data):
    result = sorted(data)  # Simulates a C extension call
    x = 1 + 2              # Pure Python
    return x
"""

_TEST_CODE = compile(_TEST_SOURCE, "/fake/test_issue999.py", "exec")
_WORKLOAD_CODE = next(
    c for c in _TEST_CODE.co_consts if hasattr(c, "co_code")
)
_FNAME = Filename("/fake/test_issue999.py")


def _find_call_instruction(code, line: int):
    """Find the CALL instruction on the given line."""
    for instr, instr_line in ScaleneFuncUtils._instructions_with_lines(code):
        if instr_line == line and instr.opname.startswith("CALL"):
            return instr
    return None


def _first_instr_on_line(code, line: int):
    """Find the first instruction on the given line."""
    for instr, instr_line in ScaleneFuncUtils._instructions_with_lines(code):
        if instr_line == line:
            return instr
    return None


def _make_frame(code, lineno: int, lasti: int):
    """Create a mock frame object."""
    frame = MagicMock()
    frame.f_code = code
    frame.f_lineno = lineno
    frame.f_lasti = lasti
    frame.f_back = None
    frame.f_locals = {}
    frame.f_globals = {"__name__": "__main__"}
    return frame


class TestIssue999WallClockAttribution:
    """Verify wall clock mode correctly attributes Python vs Native time.

    The interval-based formula computes:
        python_time = last_cpu_interval
        c_time = max(elapsed.virtual - python_time, 0)

    When a signal is deferred during a C call, c_time captures the excess.
    But when elapsed.virtual ≈ last_cpu_interval (no excess), c_time ≈ 0
    even though we might be returning from C code.

    The fix augments this with instruction-based detection: if we're at a
    CALL instruction in wall clock mode, we attribute ALL time to native
    since the signal was likely deferred during the C call.
    """

    @pytest.fixture()
    def stats(self) -> ScaleneStatistics:
        return ScaleneStatistics()

    @pytest.fixture()
    def profiler_wall_clock(self, stats: ScaleneStatistics) -> ScaleneCPUProfiler:
        """Create a profiler in wall clock mode (use_virtual_time=False)."""
        return ScaleneCPUProfiler(stats, available_cpus=1, use_virtual_time=False)

    @pytest.fixture()
    def profiler_virtual_time(self, stats: ScaleneStatistics) -> ScaleneCPUProfiler:
        """Create a profiler in virtual time mode (use_virtual_time=True)."""
        return ScaleneCPUProfiler(stats, available_cpus=1, use_virtual_time=True)

    def test_wall_clock_at_call_attributes_to_native(
        self, profiler_wall_clock: ScaleneCPUProfiler, stats: ScaleneStatistics
    ) -> None:
        """In wall clock mode, time sampled at a CALL instruction goes to native.

        This is the core fix for issue #999. When the signal fires while we're
        at a CALL instruction (just returned from C code), all time should be
        attributed to native, not Python.
        """
        call_line = _WORKLOAD_CODE.co_firstlineno + 1  # "result = sorted(data)"
        call_instr = _find_call_instruction(_WORKLOAD_CODE, call_line)
        assert call_instr is not None, "Test setup: couldn't find CALL instruction"

        main_tid = threading.main_thread().ident
        frame = _make_frame(_WORKLOAD_CODE, call_line, call_instr.offset)

        # Simulate wall clock mode: elapsed.virtual ≈ last_cpu_interval
        # This is the scenario that was broken before the fix
        prev = TimeInfo(virtual=0.0, wallclock=0.0, sys=0.0, user=0.0)
        now = TimeInfo(virtual=0.01, wallclock=0.01, sys=0.0, user=0.01)

        profiler_wall_clock.process_cpu_sample(
            new_frames=[(frame, main_tid, frame)],
            now=now,
            gpu_load=0.0,
            gpu_mem_used=0.0,
            prev=prev,
            is_thread_sleeping={main_tid: False},
            should_trace=lambda _fn, _func: True,
            last_cpu_interval=0.01,
            stacks_enabled=False,
        )

        native_time = stats.cpu_stats.cpu_samples_c[_FNAME].get(
            LineNumber(call_line), 0.0
        )
        python_time = stats.cpu_stats.cpu_samples_python[_FNAME].get(
            LineNumber(call_line), 0.0
        )

        # The fix: at a CALL instruction in wall clock mode, time goes to native
        assert native_time > 0, (
            "Wall clock mode at CALL: time should be attributed to native"
        )
        assert python_time == pytest.approx(0.0, abs=1e-6), (
            "Wall clock mode at CALL: no Python time expected"
        )

    def test_wall_clock_not_at_call_attributes_to_python(
        self, profiler_wall_clock: ScaleneCPUProfiler, stats: ScaleneStatistics
    ) -> None:
        """In wall clock mode, time NOT at a CALL instruction goes to Python."""
        python_line = _WORKLOAD_CODE.co_firstlineno + 2  # "x = 1 + 2"
        instr = _first_instr_on_line(_WORKLOAD_CODE, python_line)
        assert instr is not None, "Test setup: couldn't find instruction"

        main_tid = threading.main_thread().ident
        frame = _make_frame(_WORKLOAD_CODE, python_line, instr.offset)

        prev = TimeInfo(virtual=0.0, wallclock=0.0, sys=0.0, user=0.0)
        now = TimeInfo(virtual=0.01, wallclock=0.01, sys=0.0, user=0.01)

        profiler_wall_clock.process_cpu_sample(
            new_frames=[(frame, main_tid, frame)],
            now=now,
            gpu_load=0.0,
            gpu_mem_used=0.0,
            prev=prev,
            is_thread_sleeping={main_tid: False},
            should_trace=lambda _fn, _func: True,
            last_cpu_interval=0.01,
            stacks_enabled=False,
        )

        native_time = stats.cpu_stats.cpu_samples_c[_FNAME].get(
            LineNumber(python_line), 0.0
        )
        python_time = stats.cpu_stats.cpu_samples_python[_FNAME].get(
            LineNumber(python_line), 0.0
        )

        # Not at a CALL: time goes to Python
        assert python_time > 0, (
            "Wall clock mode not at CALL: time should be attributed to Python"
        )
        assert native_time == pytest.approx(0.0, abs=1e-6), (
            "Wall clock mode not at CALL: no native time expected"
        )

    def test_virtual_time_preserves_interval_based_attribution(
        self, profiler_virtual_time: ScaleneCPUProfiler, stats: ScaleneStatistics
    ) -> None:
        """Virtual time mode still uses interval-based formula (not broken by fix).

        In virtual time mode, c_time = elapsed.virtual - last_cpu_interval
        can be > 0 when signals are deferred during C calls, so the formula
        still works. We verify the fix doesn't break this.
        """
        call_line = _WORKLOAD_CODE.co_firstlineno + 1
        next_line = call_line + 1
        instr = _first_instr_on_line(_WORKLOAD_CODE, next_line)
        assert instr is not None

        main_tid = threading.main_thread().ident
        frame = _make_frame(_WORKLOAD_CODE, next_line, instr.offset)

        # Simulate virtual time: elapsed.virtual > last_cpu_interval
        # (signal was deferred during C call, so extra time accumulated)
        prev = TimeInfo(virtual=0.0, wallclock=0.0, sys=0.0, user=0.0)
        now = TimeInfo(virtual=0.10, wallclock=0.10, sys=0.0, user=0.10)
        last_cpu_interval = 0.01  # Timer interval

        profiler_virtual_time.process_cpu_sample(
            new_frames=[(frame, main_tid, frame)],
            now=now,
            gpu_load=0.0,
            gpu_mem_used=0.0,
            prev=prev,
            is_thread_sleeping={main_tid: False},
            should_trace=lambda _fn, _func: True,
            last_cpu_interval=last_cpu_interval,
            stacks_enabled=False,
        )

        # In virtual time mode with excess time, C time should be attributed
        # to the preceding CALL line, Python time to the current line
        c_on_call_line = stats.cpu_stats.cpu_samples_c[_FNAME].get(
            LineNumber(call_line), 0.0
        )
        python_on_next_line = stats.cpu_stats.cpu_samples_python[_FNAME].get(
            LineNumber(next_line), 0.0
        )

        expected_c_time = now.virtual - last_cpu_interval  # 0.09
        assert c_on_call_line == pytest.approx(expected_c_time, abs=1e-6), (
            "Virtual time mode: C time should go to preceding CALL line"
        )
        assert python_on_next_line == pytest.approx(last_cpu_interval, abs=1e-6), (
            "Virtual time mode: Python time stays on current line"
        )


class TestThreadSampledAttribution:
    """A sampler thread (Windows, Apple SME) is late whenever it waits for the
    GIL, even while the main thread runs pure Python. Its lateness must not be
    counted as native time: only the CALL*-bytecode test decides. Before this,
    pure-Python loops on Windows were reported as mostly native.
    """

    @pytest.fixture()
    def stats(self) -> ScaleneStatistics:
        return ScaleneStatistics()

    @pytest.fixture()
    def profiler(self, stats: ScaleneStatistics) -> ScaleneCPUProfiler:
        # Virtual time is the default; thread_sampled must override it.
        return ScaleneCPUProfiler(
            stats, available_cpus=1, use_virtual_time=True, thread_sampled=True
        )

    def _late_sample(self, profiler: ScaleneCPUProfiler, frame) -> None:
        main_tid = threading.main_thread().ident
        prev = TimeInfo(virtual=0.0, wallclock=0.0, sys=0.0, user=0.0)
        # 0.10 s of CPU since the last sample against a 0.01 s interval.
        now = TimeInfo(virtual=0.10, wallclock=0.10, sys=0.0, user=0.10)
        profiler.process_cpu_sample(
            new_frames=[(frame, main_tid, frame)],
            now=now,
            gpu_load=0.0,
            gpu_mem_used=0.0,
            prev=prev,
            is_thread_sleeping={main_tid: False},
            should_trace=lambda _fn, _func: True,
            last_cpu_interval=0.01,
            stacks_enabled=False,
        )

    def test_late_sample_not_at_call_is_all_python(
        self, profiler: ScaleneCPUProfiler, stats: ScaleneStatistics
    ) -> None:
        call_line = _WORKLOAD_CODE.co_firstlineno + 1  # "result = sorted(data)"
        python_line = call_line + 1  # "x = 1 + 2"
        # A sampler thread finds pure-Python code at a GIL handoff point;
        # on 3.11+ use RESUME (offset 0), otherwise any instruction.
        if sys.version_info >= (3, 11):
            offset = 0
            assert ScaleneFuncUtils.is_gil_handoff_point(_WORKLOAD_CODE, offset)
        else:
            instr = _first_instr_on_line(_WORKLOAD_CODE, python_line)
            assert instr is not None
            offset = instr.offset
        self._late_sample(profiler, _make_frame(_WORKLOAD_CODE, python_line, offset))

        cpu = stats.cpu_stats
        assert cpu.cpu_samples_python[_FNAME].get(
            LineNumber(python_line), 0.0
        ) == pytest.approx(0.10, abs=1e-6)
        assert cpu.cpu_samples_c[_FNAME].get(LineNumber(python_line), 0.0) == 0.0
        # Nothing moved to the preceding CALL line as "deferred" C time.
        assert cpu.cpu_samples_c[_FNAME].get(LineNumber(call_line), 0.0) == 0.0

    def test_late_sample_at_call_is_all_native(
        self, profiler: ScaleneCPUProfiler, stats: ScaleneStatistics
    ) -> None:
        call_line = _WORKLOAD_CODE.co_firstlineno + 1
        call_instr = _find_call_instruction(_WORKLOAD_CODE, call_line)
        assert call_instr is not None
        self._late_sample(
            profiler, _make_frame(_WORKLOAD_CODE, call_line, call_instr.offset)
        )

        cpu = stats.cpu_stats
        assert cpu.cpu_samples_c[_FNAME].get(
            LineNumber(call_line), 0.0
        ) == pytest.approx(0.10, abs=1e-6)
        assert cpu.cpu_samples_python[_FNAME].get(LineNumber(call_line), 0.0) == 0.0

    @pytest.mark.skipif(
        sys.version_info < (3, 11), reason="handoff points are only distinct on 3.11+"
    )
    def test_sample_mid_operator_is_all_native(
        self, profiler: ScaleneCPUProfiler, stats: ScaleneStatistics
    ) -> None:
        """Found stopped inside a BINARY_OP (not a GIL handoff point), the main
        thread released the GIL in native code, e.g. numpy's ``a @ b``."""
        src = "def ops(a, b):\n    c = a @ b\n    return c\n"
        code = next(
            c
            for c in compile(src, "/fake/ops.py", "exec").co_consts
            if hasattr(c, "co_code")
        )
        line = code.co_firstlineno + 1
        binop = next(
            ins
            for ins, ln in ScaleneFuncUtils._instructions_with_lines(code)
            if ln == line and not ScaleneFuncUtils.is_gil_handoff_point(code, ins.offset)
            and ins.opname.startswith("BINARY")
        )
        self._late_sample(profiler, _make_frame(code, line, binop.offset))

        fname = Filename("/fake/ops.py")
        cpu = stats.cpu_stats
        assert cpu.cpu_samples_c[fname].get(LineNumber(line), 0.0) == pytest.approx(
            0.10, abs=1e-6
        )
        assert cpu.cpu_samples_python[fname].get(LineNumber(line), 0.0) == 0.0


class TestSignalArrivalDeferral:
    """On the signal path, a C-level handler timestamps the timer signal's
    arrival; the delay until the Python handler runs says what was running
    at the sample instant (CPython defers the handler only while C code
    runs). The whole sample is classified by it; OS timer leeway before
    arrival (2-3x the interval on macOS CI runners) no longer counts as
    native.
    """

    @pytest.fixture()
    def stats(self) -> ScaleneStatistics:
        return ScaleneStatistics()

    @pytest.fixture()
    def profiler(self, stats: ScaleneStatistics) -> ScaleneCPUProfiler:
        return ScaleneCPUProfiler(stats, available_cpus=1, use_virtual_time=False)

    def _sample(self, profiler, frame, deferral):
        main_tid = threading.main_thread().ident
        prev = TimeInfo(virtual=0.0, wallclock=0.0, sys=0.0, user=0.0)
        # 0.04 s of CPU against a 0.01 s interval: 0.03 s of timer leeway.
        now = TimeInfo(virtual=0.04, wallclock=0.04, sys=0.0, user=0.04)
        profiler.process_cpu_sample(
            new_frames=[(frame, main_tid, frame)],
            now=now,
            gpu_load=0.0,
            gpu_mem_used=0.0,
            prev=prev,
            is_thread_sleeping={main_tid: False},
            should_trace=lambda _fn, _func: True,
            last_cpu_interval=0.01,
            stacks_enabled=False,
            signal_deferral=deferral,
        )

    def _python_line_frame(self):
        python_line = _WORKLOAD_CODE.co_firstlineno + 2  # "x = 1 + 2"
        instr = _first_instr_on_line(_WORKLOAD_CODE, python_line)
        assert instr is not None
        return python_line, _make_frame(_WORKLOAD_CODE, python_line, instr.offset)

    def test_prompt_handler_means_python_despite_timer_leeway(
        self, profiler: ScaleneCPUProfiler, stats: ScaleneStatistics
    ) -> None:
        line, frame = self._python_line_frame()
        self._sample(profiler, frame, deferral=0.00001)  # 10 us
        cpu = stats.cpu_stats
        call_line = LineNumber(_WORKLOAD_CODE.co_firstlineno + 1)
        assert cpu.cpu_samples_python[_FNAME].get(LineNumber(line), 0.0) == pytest.approx(0.04)
        assert cpu.cpu_samples_c[_FNAME].get(LineNumber(line), 0.0) == 0.0
        assert cpu.cpu_samples_c[_FNAME].get(call_line, 0.0) == 0.0

    def test_deferred_handler_means_native(
        self, profiler: ScaleneCPUProfiler, stats: ScaleneStatistics
    ) -> None:
        # e.g. `big_list + big_list`: no CALL, but the handler waited 8 ms.
        line, frame = self._python_line_frame()
        self._sample(profiler, frame, deferral=0.008)
        cpu = stats.cpu_stats
        native = sum(cpu.cpu_samples_c[_FNAME].values())
        python = sum(cpu.cpu_samples_python[_FNAME].values())
        assert native == pytest.approx(0.04)
        assert python == 0.0


@pytest.mark.skipif(sys.platform == "win32", reason="signal path is Unix-only")
def test_native_arrival_timestamper_records_signal_arrival():
    # In a fresh interpreter: once scalene_profiler is imported (as other
    # tests do), signal.signal() is rerouted by its replacement shims.
    import subprocess
    import textwrap

    script = textwrap.dedent("""
        import signal, sys, time
        from scalene.scalene_utility import (
            consume_cpu_signal_arrival,
            install_cpu_signal_timestamper,
        )
        # The signal mask is inherited across fork/exec, and an earlier
        # test may have left SIGALRM blocked in the pytest process.
        blocked = signal.SIGALRM in signal.pthread_sigmask(signal.SIG_BLOCK, [])
        signal.pthread_sigmask(signal.SIG_UNBLOCK, [signal.SIGALRM])
        signal.signal(signal.SIGALRM, lambda *_: None)
        if not install_cpu_signal_timestamper(int(signal.SIGALRM)):
            print("SKIP")
            sys.exit(0)
        consume_cpu_signal_arrival()
        signal.setitimer(signal.ITIMER_REAL, 0.005)
        end = time.perf_counter() + 0.05
        while time.perf_counter() < end:
            pass
        arrival = consume_cpu_signal_arrival()
        if arrival is None:
            from scalene import _scalene_unwind as u
            cur, ours, flags = u.handler_status(int(signal.SIGALRM))
            raise AssertionError(
                f"no arrival recorded; handler is ours: {cur == ours}, "
                f"flags={flags:#x}, diag_counts={u.diag_counts()}, "
                f"SIGALRM was blocked on entry: {blocked}"
            )
        wall, cpu = arrival
        assert 0.0 <= wall < 1.0 and cpu >= 0.0, arrival
        assert consume_cpu_signal_arrival() is None
        print("OK", "(SIGALRM was blocked on entry)" if blocked else "")
    """)
    # Clean environment: other tests may leave LD_PRELOAD etc. set.
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LD_PRELOAD", "DYLD_", "PYTHON", "SCALENE"))
    }
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    if out.stdout.strip() == "SKIP":
        pytest.skip("native unwind extension unavailable")
    assert out.stdout.startswith("OK"), out.stdout + out.stderr
