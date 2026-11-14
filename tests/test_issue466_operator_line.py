"""Issue #466: time in an operator was charged to the next line.

CPython runs a Python signal handler only at its next safe point: since 3.10,
a call's return, a loop back-edge, or a function's entry, not after every
bytecode. A sample that arrived during an operator running C code (numpy's
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
    # The concatenation (and freeing the previous result) is about a quarter
    # of each iteration; macOS measured 11-16% on 3.10-3.13 and 31% on 3.14.
    # Before the fix it got exactly 0%, with 93-97% on the call's line.
    assert operator > 0.03 * (operator + call), (operator, call)
