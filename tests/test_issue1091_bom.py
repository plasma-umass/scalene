"""Regression test for issue #1091: UTF-8 BOM in a profiled script."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("name", "source", "expected"),
    [
        ("plain", b'print("PLAIN_OK")\n', "PLAIN_OK"),
        ("bom", b'\xef\xbb\xbfprint("BOM_OK")\n', "BOM_OK"),
        ("utf8_non_ascii", 'print("é_OK")\n'.encode(), "é_OK"),
    ],
)
def test_cpu_only_cli_accepts_utf8_script_variants(
    tmp_path: Path, name: str, source: bytes, expected: str
) -> None:
    """The real CLI must execute BOM and ordinary UTF-8 scripts successfully."""
    script = tmp_path / f"{name}.py"
    script.write_bytes(source)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scalene",
            "run",
            "--cpu-only",
            "--no-browser",
            str(script),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, (
        f"Scalene failed for {name}: exit={result.returncode}\n{output[-3000:]}"
    )
    assert expected in result.stdout, (
        f"Profiled {name} script did not run to completion:\n{output[-3000:]}"
    )
