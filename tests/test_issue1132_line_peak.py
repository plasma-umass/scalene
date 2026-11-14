"""Issue #1132: the peak recorded for a line that allocates and keeps memory
across many samples must cover all of it.

With sys.monitoring line tracking (Python 3.12+), the call depth that marks
"still on the profiled line" was taken inside Scalene's malloc signal
handler, so the next handler's own lines ended the user's line and reset
its running footprint: a comprehension keeping 50 MB showed a ~2 MB peak."""

import json
import os
import subprocess
import sys
import textwrap

import pytest

PROGRAM = textwrap.dedent("""
    data = [bytearray(1_000_000) for _ in range(50)]
    print(len(data))
""")


@pytest.mark.skipif(
    sys.platform == "win32", reason="memory sampling differs on Windows"
)
def test_comprehension_peak_covers_kept_allocations(tmp_path) -> None:
    prog = tmp_path / "prog.py"
    prog.write_text(PROGRAM)
    out = tmp_path / "profile.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("SCALENE")}
    subprocess.run(
        [sys.executable, "-m", "scalene", "run", "--memory", "-o", str(out), str(prog)],
        check=True,
        capture_output=True,
        timeout=180,
        env=env,
    )
    profile = json.loads(out.read_text())
    entry = next(v for k, v in profile["files"].items() if k.endswith("prog.py"))
    line = next(x for x in entry["lines"] if x["lineno"] == 2)
    assert line["n_malloc_mb"] > 30, line["n_malloc_mb"]
    assert line["n_peak_mb"] > 0.8 * line["n_malloc_mb"], (
        line["n_peak_mb"],
        line["n_malloc_mb"],
    )
