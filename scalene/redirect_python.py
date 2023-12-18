import os
import pathlib
import stat
import sys


def redirect_python(
    preface: str, cmdline: str, python_alias_dir: pathlib.Path
) -> None:
    # Likely names for the Python interpreter.
    base_python_extension = ".exe" if sys.platform == "win32" else ""
    all_python_names = [
        "python" + base_python_extension,
        "python" + str(sys.version_info.major) + base_python_extension,
        "python"
        + str(sys.version_info.major)
        + "."
        + str(sys.version_info.minor)
        + base_python_extension,
    ]
    # if sys.platform == "win32":
    #     base_python_name = re.sub(r'\.exe$', '', os.path.basename(sys.executable))
    # else:
    #     base_python_name = sys.executable

    # Don't show commands on Windows; regular shebang for
    # shell scripts on Linux/OS X
    shebang = "@echo off" if sys.platform == "win32" else "#!/bin/bash"
    # Get all arguments, platform specific
    # all_args = "%* & exit 0" if sys.platform == "win32" else '"$@"'
    all_args = "%*" if sys.platform == "win32" else '"$@"'

    payload = f"""{shebang}
{preface} {sys.executable} -m scalene {cmdline} {all_args}
"""

    # Now create all the files.
    for name in all_python_names:
        fname = os.path.join(python_alias_dir, name)
        if sys.platform == "win32":
            fname = re.sub(r"\.exe$", ".bat", fname)
        with open(fname, "w") as file:
            file.write(payload)
        os.chmod(fname, stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR)

    # Finally, insert this directory into the path.
    sys.path.insert(0, str(python_alias_dir))
    os.environ["PATH"] = (
        str(python_alias_dir) + os.pathsep + os.environ["PATH"]
    )
    # Force the executable (if anyone invokes it later) to point to one of our aliases.
    sys.executable = os.path.join(
        python_alias_dir,
        all_python_names[0],
    )
    if sys.platform == "win32" and sys.executable.endswith(".exe"):
        sys.executable = re.sub(r"\.exe$", ".bat", sys.executable)
