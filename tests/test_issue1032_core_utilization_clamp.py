"""Regression test for issue #1032: n_core_utilization can exceed 1.0.

Issue: https://github.com/plasma-umass/scalene/issues/1032

On multi-core Linux machines, ``elapsed.user / elapsed.wallclock`` can
briefly exceed ``available_cpus`` due to measurement noise between user
and wallclock accounting. The resulting ``core_utilization`` came out
above 1.0 (e.g. 1.007, 1.024, 1.021), tripping the ``le=1`` Pydantic
validator on ``FunctionDetail`` / ``LineDetail`` / ``ScaleneJSONSchema``
and printing a warning per affected entry.

This test pegs all cores with a BLAS-heavy numpy workload under scalene,
then verifies every ``n_core_utilization`` in the resulting profile is
within [0, 1] and that no Pydantic validation warning was printed.
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import textwrap

import pytest

numpy = pytest.importorskip("numpy")


_WORKLOAD = textwrap.dedent("""\
    import numpy as np

    def heavy_matmul(n=1500, iters=20):
        a = np.random.rand(n, n)
        b = np.random.rand(n, n)
        total = 0.0
        for _ in range(iters):
            total += float((a @ b).sum())
        return total

    def heavy_svd(n=1200, iters=15):
        a = np.random.rand(n, n)
        total = 0.0
        for _ in range(iters):
            _, s, _ = np.linalg.svd(a, full_matrices=False)
            total += float(s.sum())
        return total

    if __name__ == "__main__":
        heavy_matmul()
        heavy_svd()
""")


def _iter_core_utilizations(profile: dict):
    """Yield every ``n_core_utilization`` value found anywhere in the profile."""

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "n_core_utilization" and isinstance(v, (int, float)):
                    yield v
                else:
                    yield from walk(v)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)

    yield from walk(profile)


def test_core_utilization_within_bounds_under_blas_load():
    """Pegging the cores must never produce ``n_core_utilization`` > 1."""
    with tempfile.TemporaryDirectory(prefix="scalene_1032_") as tmp:
        tmp = pathlib.Path(tmp)
        script = tmp / "mwe.py"
        script.write_text(_WORKLOAD)
        outfile = tmp / "profile.json"

        cmd = [
            sys.executable,
            "-m",
            "scalene",
            "run",
            "--cpu-only",
            "-o",
            str(outfile),
            str(script),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if not outfile.exists():
            pytest.skip(
                "Scalene did not produce a profile in this environment; "
                f"rc={proc.returncode} stderr={proc.stderr[-400:]}"
            )

        # The Pydantic validator emits this exact prefix when le=1 fails.
        # Catch it directly so a future regression that re-raises the bound
        # without producing a >1 value (e.g. via clamp logic moving) still
        # surfaces as a test failure rather than silent stderr noise.
        assert "JSON failed validation" not in proc.stderr, (
            f"scalene printed a JSON validation warning:\n{proc.stderr}"
        )

        profile = json.loads(outfile.read_text())
        values = list(_iter_core_utilizations(profile))
        assert values, "profile contained no n_core_utilization entries"

        over = [v for v in values if v > 1.0 or v < 0.0]
        assert not over, (
            f"n_core_utilization out of [0, 1]: "
            f"{sorted(over, reverse=True)[:5]} (max={max(values)})"
        )
