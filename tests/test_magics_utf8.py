"""%%scalene and %scrun must save the cell as UTF-8.

``ScaleneMagics.run_code`` writes the cell to ``_ipython-input-N-profile``
and ``run_profiler`` reads that file back as UTF-8. Writing it with the
locale encoding broke cells with non-ASCII text wherever that encoding is
not UTF-8 (e.g. cp1252 or cp932 on Windows). The check runs in a child
process with a non-UTF-8 locale (ASCII under ``LC_ALL=C`` on Linux and
macOS, the ANSI code page on Windows).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("IPython")

CHILD = textwrap.dedent(
    """
    import types
    from pathlib import Path
    from unittest import mock

    import IPython
    from scalene import scalene_profiler
    from scalene.scalene_arguments import ScaleneArguments
    from scalene.scalene_magics import ScaleneMagics

    code = "\\nprint('caf\\u00e9 \\u65e5\\u672c\\u8a9e')\\n"
    shell = types.SimpleNamespace(
        history_manager=types.SimpleNamespace(input_hist_raw=["", code])
    )
    saved = []

    def run_profiler(args, progs, is_jupyter=False):
        saved.append(Path(progs[0]).read_text(encoding="utf-8"))

    with mock.patch.object(IPython, "get_ipython", return_value=shell):
        with mock.patch.object(scalene_profiler.Scalene, "run_profiler", run_profiler):
            ScaleneMagics.run_code(None, ScaleneArguments(), code)
    assert saved == [code], saved
    """
)


def test_magic_saves_cell_as_utf8(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "LC_ALL": "C",
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONIOENCODING": "utf-8",
    }
    result = subprocess.run(
        [sys.executable, "-c", CHILD],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-3000:]
