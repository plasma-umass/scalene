"""Issue #466: time in an operator was charged to the next line.

CPython runs a Python signal handler only at its next safe point (a call's
return, a loop back-edge, a function's entry), not after every bytecode. A sample that arrived during an operator running C code (numpy's
`x @ y`, or `big + big` on lists) was handled at the end of the next line's
call and charged there, so the operator's line showed no time at all. The
C-level handler now records where the main thread was at each timer arrival,
and keeps sampling while the Python handler is pending, so the time is split
between the lines that actually ran."""

import json
import os
import subprocess
import sys
import textwrap

import pytest

PROGRAM = textwrap.dedent("""
    import time

    big = list(range(2_000_000))


    def work(seconds):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            p = big + big  # OPERATOR: C code, no safe point
            q = sum(range(3_000_000))  # CALL
        return p, q


    work(1.5)
""")


def test_operator_line_gets_its_time(tmp_path) -> None:
    prog = tmp_path / "prog.py"
    prog.write_text(PROGRAM)
    out = tmp_path / "profile.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("SCALENE")}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scalene",
            "run",
            "--cpu-only",
            "-o",
            str(out),
            str(prog),
        ],
        check=True,
        capture_output=True,
        timeout=120,
        env=env,
    )
    profile = json.loads(out.read_text())
    entry = next(v for k, v in profile["files"].items() if k.endswith("prog.py"))

    def percent(marker: str) -> float:
        line = next(line for line in entry["lines"] if marker in line["line"])
        return float(line["n_cpu_percent_python"] + line["n_cpu_percent_c"])

    operator, call = percent("# OPERATOR"), percent("# CALL")
    assert operator + call > 50, (operator, call)  # the loop got sampled
    # The concatenation (and freeing the previous result) is 18-26% of each
    # iteration (13% on 3.10, which profiling speeds up); macOS measures
    # within a point or two of that. Before the fix it got exactly 0%, with
    # 93-97% on the call's line.
    assert operator > 0.03 * (operator + call), (operator, call)


_LOOP_SOURCE = """\
def work(big):
    p = big + big
    q = sum(range(10))
    return p, q
"""
_LOOP_CODE = next(
    c
    for c in compile(_LOOP_SOURCE, "/fake/issue466.py", "exec").co_consts
    if hasattr(c, "co_code")
)


def _offset_on_line(code, line: int) -> int:
    import dis

    current = None
    for instr in dis.get_instructions(code):
        starts = getattr(instr, "line_number", None)
        if starts is None and not isinstance(instr.starts_line, bool):
            starts = instr.starts_line
        if starts is not None:
            current = starts
        if current == line and instr.opname not in ("RESUME", "NOP", "CACHE"):
            return instr.offset
    raise AssertionError(f"no instruction on line {line}")


def test_every_arrival_stands_for_the_same_time() -> None:
    """The handler always runs at the same safe point (after the call on the
    second line returns), so samples with an arrival on the operator's line
    also have one on the call's line, while samples with a single arrival
    are on the call's line. Splitting each sample's time among its own
    arrivals gave the operator a quarter of the time here, not a third."""
    import threading
    from unittest.mock import MagicMock

    from scalene.scalene_cpu_profiler import ScaleneCPUProfiler
    from scalene.scalene_statistics import Filename, LineNumber, ScaleneStatistics
    from scalene.time_info import TimeInfo

    first = _LOOP_CODE.co_firstlineno
    operator_line, call_line = first + 1, first + 2
    operator = (id(_LOOP_CODE), _offset_on_line(_LOOP_CODE, operator_line))
    call = (id(_LOOP_CODE), _offset_on_line(_LOOP_CODE, call_line))

    frame = MagicMock()
    frame.f_code = _LOOP_CODE
    frame.f_lineno = call_line
    frame.f_lasti = call[1]
    frame.f_back = None
    frame.f_globals = {"__name__": "__main__"}

    stats = ScaleneStatistics()
    profiler = ScaleneCPUProfiler(stats, available_cpus=1, use_virtual_time=False)
    main_tid = threading.main_thread().ident
    t = 0.0
    total = 0.0
    for k in range(100):
        # 30 ms each: an arrival on each line, then one on the call's line.
        arrivals = (
            [(0.02, 0.02, operator), (0.01, 0.01, call)]
            if k % 2 == 0
            else [(0.01, 0.01, call)]
        )
        prev = TimeInfo(virtual=t, wallclock=t, sys=0.0, user=t)
        t += 0.03
        total += 0.03
        now = TimeInfo(virtual=t, wallclock=t, sys=0.0, user=t)
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
            signal_deferral=arrivals[0][0],
            signal_arrivals=arrivals,
        )
    cpu = stats.cpu_stats
    fname = Filename("/fake/issue466.py")

    def time_on(line: int) -> float:
        return cpu.cpu_samples_python[fname].get(LineNumber(line), 0.0) + cpu.cpu_samples_c[
            fname
        ].get(LineNumber(line), 0.0)

    op, rest = time_on(operator_line), time_on(call_line)
    assert op / (op + rest) == pytest.approx(1 / 3, abs=0.01)
    assert op + rest == pytest.approx(total, rel=0.02)
