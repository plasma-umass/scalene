"""Test that Scalene can profile multiprocessing Pool.map with spawn context."""

import json
import pathlib
import subprocess
import sys
import tempfile
import textwrap

import pytest


def test_pool_spawn_cpu_only():
    """Run Scalene on a spawn-mode Pool.map program and verify JSON output."""
    program = textwrap.dedent("""\
        import multiprocessing

        def worker(n):
            total = 0
            for i in range(n):
                total += i * i
            return total

        if __name__ == "__main__":
            # Enough computation in the main process to be reliably sampled
            total = 0
            for i in range(5000000):
                total += i * i
            ctx = multiprocessing.get_context("spawn")
            with ctx.Pool(2) as pool:
                results = pool.map(worker, [200000] * 4)
            print(total + sum(results))
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

        # Basic structure checks
        assert "files" in data, f"No 'files' key in JSON output: {list(data.keys())}"
        assert len(data["files"]) > 0, "No files in profiling output"
        assert "elapsed_time_sec" in data, "Missing elapsed_time_sec"
        assert data["elapsed_time_sec"] > 0, "Elapsed time should be positive"

        # Find the target file in the output
        target_file = None
        for fname in data["files"]:
            if "pool_spawn_program" in fname:
                target_file = fname
                break
        assert target_file is not None, (
            f"Target file not found in output. Files: {list(data['files'].keys())}"
        )

        # Verify the target file has profiling data that makes sense
        lines = data["files"][target_file]["lines"]
        assert len(lines) > 0, "Target file has no line data"

        # Check that at least one line has non-zero CPU activity
        has_cpu_activity = any(
            line["n_cpu_percent_python"] > 0 or line["n_cpu_percent_c"] > 0
            for line in lines
        )
        assert has_cpu_activity, (
            "No CPU activity recorded in target file. "
            "Expected non-zero n_cpu_percent_python or n_cpu_percent_c on at least one line."
        )

        # Verify CPU percentages are within valid bounds (0-100)
        for line in lines:
            assert 0 <= line["n_cpu_percent_python"] <= 100, (
                f"Line {line['lineno']}: n_cpu_percent_python={line['n_cpu_percent_python']} out of range"
            )
            assert 0 <= line["n_cpu_percent_c"] <= 100, (
                f"Line {line['lineno']}: n_cpu_percent_c={line['n_cpu_percent_c']} out of range"
            )
            assert 0 <= line["n_sys_percent"] <= 100, (
                f"Line {line['lineno']}: n_sys_percent={line['n_sys_percent']} out of range"
            )
