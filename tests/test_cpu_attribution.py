"""Test CPU time attribution for the main thread.

Issue: https://github.com/plasma-umass/scalene/issues/994

When a C extension call (e.g., sorted(), numpy op, torch tensor op) runs on
line N, CPython defers the profiling signal until the C call returns.  By the
time the signal handler fires, f_lineno has advanced to line N+1.  The fix
walks backward from f_lasti to find the preceding CALL instruction and
attributes C time to that line instead.
"""

import dis
import threading
import types
from unittest.mock import MagicMock

import pytest

from scalene.scalene_cpu_profiler import ScaleneCPUProfiler
from scalene.scalene_statistics import (
    Filename,
    LineNumber,
    ScaleneStatistics,
)
from scalene.time_info import TimeInfo


# ---------------------------------------------------------------------------
# Helper: build a real function whose bytecodes we can inspect, with a C call
# on one line followed by pure-Python arithmetic on the next.
# ---------------------------------------------------------------------------

# We define this at module level so the code object has a stable co_filename.
_TEST_SOURCE = """\
def workload(data):
    result = sorted(data)
    x = 1 + 2
    return x
"""

# Compile so we get a real code object with accurate line numbers.
_TEST_CODE = compile(_TEST_SOURCE, "/fake/test_workload.py", "exec")
# Extract the inner function's code object.
_WORKLOAD_CODE: types.CodeType = next(
    c for c in _TEST_CODE.co_consts if isinstance(c, types.CodeType)
)

_FNAME = Filename("/fake/test_workload.py")


# Source for the pure-Python-only test (no C calls).
_PURE_PYTHON_SOURCE = """\
def pure_work():
    x = 1 + 2
    y = x * 3
    return y
"""

_PURE_PYTHON_CODE = compile(_PURE_PYTHON_SOURCE, "/fake/test_pure.py", "exec")
_PURE_WORKLOAD_CODE: types.CodeType = next(
    c for c in _PURE_PYTHON_CODE.co_consts if isinstance(c, types.CodeType)
)
_PURE_FNAME = Filename("/fake/test_pure.py")


# Source with multiple consecutive C calls.
_MULTI_CALL_SOURCE = """\
def multi_calls(data):
    a = sorted(data)
    b = len(data)
    c = sum(data)
    x = 1 + 2
    return x
"""

_MULTI_CALL_CODE = compile(_MULTI_CALL_SOURCE, "/fake/test_multi.py", "exec")
_MULTI_WORKLOAD_CODE: types.CodeType = next(
    c for c in _MULTI_CALL_CODE.co_consts if isinstance(c, types.CodeType)
)
_MULTI_FNAME = Filename("/fake/test_multi.py")


def _get_line(instr: dis.Instruction) -> int | None:
    """Get the line number from an instruction, compatible across Python versions.

    Python < 3.14: starts_line is int | None (the line number or None).
    Python >= 3.14: starts_line is bool; line_number holds the actual number.
    """
    if hasattr(instr, "line_number"):
        # Python 3.14+
        return instr.line_number
    # Python < 3.14: starts_line IS the line number (int or None)
    return instr.starts_line  # type: ignore[return-value]


def _is_new_line(instr: dis.Instruction) -> bool:
    """Check if this instruction starts a new line."""
    if hasattr(instr, "line_number"):
        # Python 3.14+: starts_line is a bool
        return bool(instr.starts_line)
    # Python < 3.14: starts_line is an int (line number) or None
    return instr.starts_line is not None  # type: ignore[union-attr]


def _find_instruction(code: types.CodeType, opname_prefix: str, target_line: int):
    """Find the first instruction matching *opname_prefix* on *target_line*."""
    for instr in dis.get_instructions(code):
        line = _get_line(instr)
        if line == target_line and instr.opname.startswith(opname_prefix):
            return instr
    raise ValueError(f"No {opname_prefix}* instruction found on line {target_line}")


def _first_instr_on_line(code: types.CodeType, target_line: int):
    """Return the first instruction whose line_number == target_line."""
    for instr in dis.get_instructions(code):
        if _get_line(instr) == target_line and _is_new_line(instr):
            return instr
    # Fallback: any instruction on the target line.
    for instr in dis.get_instructions(code):
        if _get_line(instr) == target_line:
            return instr
    raise ValueError(f"No instruction found on line {target_line}")


# ---------------------------------------------------------------------------
# Mock frame helpers
# ---------------------------------------------------------------------------


def _make_frame(
    code: types.CodeType,
    lineno: int,
    lasti: int,
    f_back=None,
):
    """Create a minimal mock that looks like a FrameType."""
    frame = MagicMock(spec=types.FrameType)
    frame.f_code = code
    frame.f_lineno = lineno
    frame.f_lasti = lasti
    frame.f_back = f_back
    return frame


# ---------------------------------------------------------------------------
# Shared simulate helper
# ---------------------------------------------------------------------------


def _simulate_signal(
    profiler: ScaleneCPUProfiler,
    stats: ScaleneStatistics,
    code: types.CodeType,
    *,
    frame_lineno: int,
    frame_lasti: int,
    elapsed_virtual: float,
    last_cpu_interval: float,
):
    """Simulate a single CPU profiling signal delivery."""
    main_tid = threading.main_thread().ident

    frame = _make_frame(code, frame_lineno, frame_lasti)
    new_frames = [(frame, main_tid, frame)]

    prev = TimeInfo(virtual=0.0, wallclock=0.0, sys=0.0, user=0.0)
    now = TimeInfo(
        virtual=elapsed_virtual,
        wallclock=elapsed_virtual,
        sys=0.0,
        user=elapsed_virtual,
    )

    is_sleeping = {main_tid: False}

    profiler.process_cpu_sample(
        new_frames=new_frames,
        now=now,
        gpu_load=0.0,
        gpu_mem_used=0.0,
        prev=prev,
        is_thread_sleeping=is_sleeping,
        should_trace=lambda _fn, _func: True,
        last_cpu_interval=last_cpu_interval,
        stacks_enabled=False,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMainThreadCTimeAttribution:
    """Verify that C time from a CALL on line N is attributed to line N,
    not line N+1 where f_lineno has advanced by the time the signal fires.
    """

    @pytest.fixture()
    def stats(self):
        return ScaleneStatistics()

    @pytest.fixture()
    def profiler(self, stats):
        return ScaleneCPUProfiler(stats, available_cpus=1)

    def test_c_time_attributed_to_call_line(self, profiler, stats):
        """C time from sorted() on line 2 is correctly placed on line 2,
        while Python time stays on line 3 (where f_lineno points).
        """
        sorted_line = _WORKLOAD_CODE.co_firstlineno + 1  # line with sorted()
        next_line = sorted_line + 1  # line with x = 1 + 2

        instr_next = _first_instr_on_line(_WORKLOAD_CODE, next_line)

        elapsed_virtual = 0.10
        last_cpu_interval = 0.01
        expected_c_time = elapsed_virtual - last_cpu_interval  # 0.09

        _simulate_signal(
            profiler,
            stats,
            _WORKLOAD_CODE,
            frame_lineno=next_line,
            frame_lasti=instr_next.offset,
            elapsed_virtual=elapsed_virtual,
            last_cpu_interval=last_cpu_interval,
        )

        c_on_sorted_line = stats.cpu_stats.cpu_samples_c[_FNAME].get(
            LineNumber(sorted_line), 0.0
        )
        c_on_next_line = stats.cpu_stats.cpu_samples_c[_FNAME].get(
            LineNumber(next_line), 0.0
        )
        python_on_next_line = stats.cpu_stats.cpu_samples_python[_FNAME].get(
            LineNumber(next_line), 0.0
        )

        # C time attributed to the line containing the C call.
        assert c_on_sorted_line == pytest.approx(expected_c_time, abs=1e-6)
        assert c_on_next_line == pytest.approx(0.0, abs=1e-6)
        # Python time stays on the line where the signal was delivered.
        assert python_on_next_line == pytest.approx(last_cpu_interval, abs=1e-6)

    def test_pure_python_no_preceding_call(self, profiler, stats):
        """When there is no preceding CALL (pure Python), all time goes to f_lineno."""
        # pure_work():  line+0 = def, line+1 = x = 1+2, line+2 = y = x*3
        target_line = _PURE_WORKLOAD_CODE.co_firstlineno + 2  # y = x * 3
        instr = _first_instr_on_line(_PURE_WORKLOAD_CODE, target_line)

        elapsed_virtual = 0.05
        last_cpu_interval = 0.04  # mostly Python time
        expected_c_time = elapsed_virtual - last_cpu_interval  # 0.01

        _simulate_signal(
            profiler,
            stats,
            _PURE_WORKLOAD_CODE,
            frame_lineno=target_line,
            frame_lasti=instr.offset,
            elapsed_virtual=elapsed_virtual,
            last_cpu_interval=last_cpu_interval,
        )

        c_on_target = stats.cpu_stats.cpu_samples_c[_PURE_FNAME].get(
            LineNumber(target_line), 0.0
        )
        python_on_target = stats.cpu_stats.cpu_samples_python[_PURE_FNAME].get(
            LineNumber(target_line), 0.0
        )

        # With no preceding CALL on a different line, everything goes to f_lineno.
        assert c_on_target == pytest.approx(expected_c_time, abs=1e-6)
        assert python_on_target == pytest.approx(last_cpu_interval, abs=1e-6)

    def test_multi_consecutive_c_calls(self, profiler, stats):
        """Multiple C calls: signal after sum() (line 4) with f_lineno on line 5.

        C time should go to line 4 (sum's CALL), Python time to line 5.
        """
        # multi_calls: line+1=sorted, line+2=len, line+3=sum, line+4=x=1+2
        base = _MULTI_WORKLOAD_CODE.co_firstlineno
        sum_line = base + 3      # c = sum(data)
        pure_line = base + 4     # x = 1 + 2

        instr_pure = _first_instr_on_line(_MULTI_WORKLOAD_CODE, pure_line)

        elapsed_virtual = 0.10
        last_cpu_interval = 0.01
        expected_c_time = elapsed_virtual - last_cpu_interval

        _simulate_signal(
            profiler,
            stats,
            _MULTI_WORKLOAD_CODE,
            frame_lineno=pure_line,
            frame_lasti=instr_pure.offset,
            elapsed_virtual=elapsed_virtual,
            last_cpu_interval=last_cpu_interval,
        )

        c_on_sum_line = stats.cpu_stats.cpu_samples_c[_MULTI_FNAME].get(
            LineNumber(sum_line), 0.0
        )
        c_on_pure_line = stats.cpu_stats.cpu_samples_c[_MULTI_FNAME].get(
            LineNumber(pure_line), 0.0
        )
        python_on_pure_line = stats.cpu_stats.cpu_samples_python[_MULTI_FNAME].get(
            LineNumber(pure_line), 0.0
        )

        # C time goes to the most recent CALL line (sum on line+3).
        assert c_on_sum_line == pytest.approx(expected_c_time, abs=1e-6)
        assert c_on_pure_line == pytest.approx(0.0, abs=1e-6)
        assert python_on_pure_line == pytest.approx(last_cpu_interval, abs=1e-6)


class TestNonMainThreadAttribution:
    """Verify that non-main threads DO use bytecode inspection."""

    @pytest.fixture()
    def stats(self):
        return ScaleneStatistics()

    @pytest.fixture()
    def profiler(self, stats):
        return ScaleneCPUProfiler(stats, available_cpus=1)

    def test_thread_at_call_instruction_attributes_to_c(self, profiler, stats):
        """When a non-main thread's f_lasti is at a CALL, time goes to C."""
        sorted_line = _WORKLOAD_CODE.co_firstlineno + 1
        main_tid = threading.main_thread().ident
        other_tid = main_tid + 1  # fake second thread

        call_instr = _find_instruction(_WORKLOAD_CODE, "CALL", sorted_line)

        main_frame = _make_frame(_WORKLOAD_CODE, sorted_line, call_instr.offset)
        thread_frame = _make_frame(_WORKLOAD_CODE, sorted_line, call_instr.offset)

        prev = TimeInfo(virtual=0.0, wallclock=0.0, sys=0.0, user=0.0)
        now = TimeInfo(virtual=0.10, wallclock=0.10, sys=0.0, user=0.10)

        profiler.process_cpu_sample(
            new_frames=[
                (main_frame, main_tid, main_frame),
                (thread_frame, other_tid, thread_frame),
            ],
            now=now,
            gpu_load=0.0,
            gpu_mem_used=0.0,
            prev=prev,
            is_thread_sleeping={main_tid: False, other_tid: False},
            should_trace=lambda _fn, _func: True,
            last_cpu_interval=0.01,
            stacks_enabled=False,
        )

        c_samples = stats.cpu_stats.cpu_samples_c[_FNAME].get(
            LineNumber(sorted_line), 0.0
        )

        assert c_samples > 0, (
            "Non-main thread at a CALL instruction should attribute time to C"
        )
