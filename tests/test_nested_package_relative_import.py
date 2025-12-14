# tests/test_nested_package_imports.py
import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_nested_package_relative_import(tmp_path):
    """
    Scalene should profile a module inside a sub‑package without breaking
    its relative imports.  Regression test for PR #903
    (commit bb8b753b7…).
    """
    # ------------------------------------------------------------------
    # 1.  Create the package pkg.subpkg with a helper and a module.
    # ------------------------------------------------------------------
    pkg: Path = tmp_path / "pkg"
    subpkg: Path = pkg / "subpkg"
    subpkg.mkdir(parents=True)

    # mark both directories as packages
    (pkg / "__init__.py").write_text("")
    (subpkg / "__init__.py").write_text("")

    # helper that the target module will import relatively
    (subpkg / "helper.py").write_text("def foo():\n" "    return 42\n")

    # target module that depends on the relative import
    (subpkg / "mod.py").write_text(
        textwrap.dedent(
            """
        from .helper import foo

        if __name__ == "__main__":
            print(foo())   # prints 42 on success
        """
        )
    )

    # ------------------------------------------------------------------
    # 2.  Invoke Scalene as a separate process on that module.
    # ------------------------------------------------------------------
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path)  # make package discoverable

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scalene",
            "run",  # use the 'run' subcommand
            "-m",
            "pkg.subpkg.mod",
            "--cpu-only",  # CPU-only profiling, keep the run fast
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    # ------------------------------------------------------------------
    # 3.  Assertions: process exited cleanly and the helper ran.
    # ------------------------------------------------------------------
    assert result.returncode == 0, result.stderr
    assert "42" in result.stdout
