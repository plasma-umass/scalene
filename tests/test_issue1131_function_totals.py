"""Issue #1131: a function's CPU total must equal the sum of its lines.

In a tight loop, CPU samples land on the loop header, and Scalene spreads
each one over the loop body's lines. Those body lines were never registered
as part of the function, so the function total missed their share (half,
for a two-line loop)."""

import json
import os
import subprocess
import sys
import textwrap

PROGRAM = textwrap.dedent("""
    import time

    def loop_work(seconds):
        end = time.perf_counter() + seconds
        x = 0
        while time.perf_counter() < end:
            for i in range(1000):
                x += i * i
        return x

    loop_work(1.0)
""")


def test_function_total_matches_its_lines(tmp_path) -> None:
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
    fn = next(f for f in entry["functions"] if "loop_work" in f["line"])
    first = fn["lineno"]
    last = first + 6  # the function's last line ("return x")
    total = fn["n_cpu_percent_python"] + fn["n_cpu_percent_c"]
    lines = sum(
        line["n_cpu_percent_python"] + line["n_cpu_percent_c"]
        for line in entry["lines"]
        if first <= line["lineno"] <= last
    )
    assert lines > 10, lines  # the loop got sampled
    assert abs(total - lines) < 0.05 * lines, (total, lines)
