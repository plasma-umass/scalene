#!/usr/bin/env python3
import json
import pathlib
import tempfile
import subprocess
import sys


def smoketest(fname, rest):
    outfile = pathlib.Path(
        tempfile.mkdtemp(prefix="scalene") / pathlib.Path("smoketest.json")
    )
    cmd = [
        sys.executable,
        "-m",
        "scalene",
        "run",
        "--profile-all",
        "-o",
        str(outfile),
        *rest,
        fname,
    ]
    print("COMMAND", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True)
    stdout = proc.stdout.decode("utf-8")
    stderr = proc.stderr.decode("utf-8")

    if proc.returncode != 0:
        print("Exited with a non-zero code:", proc.returncode)
        print("STDOUT", stdout)
        print("STDERR", stderr)

        exit(proc.returncode)
    #    print("STDOUT", stdout)
    #    print("\nSTDERR", stderr)
    try:
        with open(outfile, "r") as f:
            outfile_contents = f.read()
        scalene_json = json.loads(outfile_contents)
    except json.JSONDecodeError:
        print("Invalid JSON", stderr)
        print("STDOUT", stdout)
        print("STDERR", stderr)
        exit(1)
    if len(scalene_json) == 0:
        print("No JSON output")
        print("STDOUT", stdout)
        print("STDERR", stderr)
        exit(1)
    files = scalene_json["files"]
    if not len(files) > 0:
        print("No files found in output")
        exit(1)
    # Check that the target file (fname) has non-zero lines.
    # With --profile-all, other files may be included but may not have
    # any CPU activity, so we only require the target file to have activity.
    target_file = None
    # Normalize the target filename for cross-platform comparison
    fname_parts = pathlib.PurePath(fname).parts
    for _fname in files:
        # Check if the target path parts appear at the end of the profiled path
        _fname_parts = pathlib.PurePath(_fname).parts
        if len(_fname_parts) >= len(fname_parts):
            if _fname_parts[-len(fname_parts):] == fname_parts:
                target_file = _fname
                break
    if target_file is None:
        print(f"Target file {fname} not found in output")
        print("Files in output:", list(files.keys()))
        exit(1)
    if not any(
        (line["n_cpu_percent_c"] > 0 or line["n_cpu_percent_python"] > 0)
        for line in files[target_file]["lines"]
    ):
        print("No non-zero lines in target file", target_file)
        exit(1)


if __name__ == "__main__":
    smoketest(sys.argv[1], sys.argv[2:])
