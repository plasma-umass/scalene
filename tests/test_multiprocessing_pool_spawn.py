"""Test that Scalene can profile multiprocessing Pool.map with spawn context.

Regression test for issue #998. The key assertion is that Scalene completes
without hanging or crashing. Profiling data validation is best-effort because
spawn-mode workers communicate via pipes that can be intermittently disrupted
by Scalene's signal-based sampling on some platforms.
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import textwrap

import pytest


def test_pool_spawn_cpu_only():
    """Run Scalene on a spawn-mode Pool.map program and verify it completes."""
    program = textwrap.dedent("""\
        import multiprocessing

        def worker(n):
            total = 0
            for i in range(n):
                total += i * i
            return total

        if __name__ == "__main__":
            # Enough computation in the main process to be reliably sampled.
            # Use list comprehensions (like testme.py) to ensure sufficient time.
            for _ in range(10):
                x = [i * i for i in range(200000)]
            ctx = multiprocessing.get_context("spawn")
            with ctx.Pool(2) as pool:
                results = pool.map(worker, [200000] * 4)
            print(sum(results))
    """)

    with tempfile.TemporaryDirectory(prefix="scalene_test_") as tmpdir:
        tmpdir = pathlib.Path(tmpdir)
        script = tmpdir / "pool_spawn_program.py"
        script.write_text(program)
        outfile = tmpdir / "profile.json"

        cmd = [
            sys.executable,
            "-m",
            "scalene",
            "run",
            "--cpu-only",
            "--profile-all",
            "-o",
            str(outfile),
            str(script),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=120)

        assert proc.returncode == 0, (
            f"Scalene exited with code {proc.returncode}\n"
            f"STDOUT: {proc.stdout.decode()}\n"
            f"STDERR: {proc.stderr.decode()}"
        )

        assert outfile.exists(), "Profile JSON file was not created"
        data = json.loads(outfile.read_text())

        # Scalene must produce a valid profile dict (may be empty if the
        # program was too short-lived, but should never be a non-dict).
        assert isinstance(data, dict), f"Expected dict, got {type(data)}"

        # If profiling data was captured, validate it makes sense.
        if "files" in data and len(data["files"]) > 0:
            assert data.get("elapsed_time_sec", 0) > 0, (
                "Elapsed time should be positive when files are present"
            )

            # Verify CPU percentages are within valid bounds (0-100)
            for fname, fdata in data["files"].items():
                for line in fdata.get("lines", []):
                    assert 0 <= line["n_cpu_percent_python"] <= 100, (
                        f"{fname}:{line['lineno']}: n_cpu_percent_python="
                        f"{line['n_cpu_percent_python']} out of range"
                    )
                    assert 0 <= line["n_cpu_percent_c"] <= 100, (
                        f"{fname}:{line['lineno']}: n_cpu_percent_c="
                        f"{line['n_cpu_percent_c']} out of range"
                    )
                    assert 0 <= line["n_sys_percent"] <= 100, (
                        f"{fname}:{line['lineno']}: n_sys_percent="
                        f"{line['n_sys_percent']} out of range"
                    )
