"""Regression test for issue #999: Wall clock mode Python/Native attribution.

Issue: https://github.com/plasma-umass/scalene/issues/999

In wall clock mode, numpy-heavy code was incorrectly showing ~15-20% Python time
for lines that should be nearly 100% native (C extension) time. The fix uses
instruction-based detection (checking if we're at a CALL opcode) instead of
the interval-based formula which doesn't work in wall clock mode.
"""

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
