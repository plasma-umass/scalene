import os
import pathlib
import re
import stat
import sys


def redirect_python(preface: str, cmdline: str, python_alias_dir: pathlib.Path) -> str:
    """
    Redirects Python calls to a different command with a preface and cmdline.

    Args:
        preface: A string to be prefixed to the Python command.
        cmdline: Additional command line arguments to be appended.
        python_alias_dir: The directory where the alias scripts will be stored.
    """
    base_python_extension = ".exe" if sys.platform == "win32" else ""
    all_python_names = [
        "python" + base_python_extension,
        f"python{sys.version_info.major}{base_python_extension}",
        f"python{sys.version_info.major}.{sys.version_info.minor}{base_python_extension}",
    ]

    shebang = "@echo off" if sys.platform == "win32" else "#!/bin/bash"
    all_args = "%*" if sys.platform == "win32" else '"$@"'

    payload = f"{shebang}\n{preface} {sys.executable} -m scalene {cmdline} {all_args}\n"

    for name in all_python_names:
        fname = python_alias_dir / name
        if sys.platform == "win32":
            fname = fname.with_suffix(".bat")
        try:
            with open(fname, "w") as file:
                file.write(payload)
            if sys.platform != "win32":
                os.chmod(fname, stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR)
        except IOError as e:
            print(f"Error writing to {fname}: {e}")

    sys.path.insert(0, str(python_alias_dir))
    os.environ["PATH"] = f"{python_alias_dir}{os.pathsep}{os.environ['PATH']}"

    orig_sys_executable = sys.executable

    # Compute the new sys executable path
    sys_executable_path = python_alias_dir / all_python_names[0]

    # On Windows, adjust the path to use a .bat file instead of .exe
    if sys.platform == "win32" and sys_executable_path.suffix == ".exe":
        sys_executable_path = sys_executable_path.with_suffix(".bat")

    sys.executable = str(sys_executable_path)
    
    return orig_sys_executable
