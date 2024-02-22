# file scalene/redirect_python.py:8-50
# lines [8, 17, 18, 19, 20, 21, 24, 25, 27, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 41, 42, 44, 46, 47, 48, 50]
# branches ['29->30', '29->41', '31->32', '31->33', '36->29', '36->37', '47->48', '47->50']

import os
import pathlib
import pytest
import shutil
import stat
import sys
from scalene.redirect_python import redirect_python

@pytest.fixture
def python_alias_dir(tmp_path):
    # Create a temporary directory for the test
    dir = tmp_path / "python_alias"
    dir.mkdir()
    return dir

def test_redirect_python(python_alias_dir):
    preface = "echo"
    cmdline = "--version"
    original_path = os.environ["PATH"]
    original_sys_executable = sys.executable
    original_sys_path = sys.path.copy()

    try:
        orig_executable = redirect_python(preface, cmdline, python_alias_dir)
        # Check if the sys.executable has been changed
        assert sys.executable != original_sys_executable
        # Check if the sys.path has been updated
        assert str(python_alias_dir) in sys.path
        # Check if the PATH environment variable has been updated
        assert str(python_alias_dir) in os.environ["PATH"]
        # Check if the files have been created
        base_python_extension = ".exe" if sys.platform == "win32" else ""
        all_python_names = [
            "python" + base_python_extension,
            f"python{sys.version_info.major}{base_python_extension}",
            f"python{sys.version_info.major}.{sys.version_info.minor}{base_python_extension}",
        ]
        for name in all_python_names:
            fname = python_alias_dir / name
            if sys.platform == "win32":
                fname = fname.with_suffix(".bat")
            assert fname.exists()
    finally:
        # Clean up: Restore the original sys.executable, sys.path, and PATH
        sys.executable = original_sys_executable
        sys.path = original_sys_path
        os.environ["PATH"] = original_path
        # Remove the temporary directory
        shutil.rmtree(python_alias_dir)
