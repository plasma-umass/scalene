#!/usr/bin/env python3
import subprocess
import sys
import json

def smoketest(fname):
    proc = subprocess.run( [sys.executable, "-m", "scalene", "--cli", "--json", "--outfile", "/dev/stderr", fname] ,capture_output=True)
    if proc.returncode != 0:
        print("Exited with a non-zero code:", proc.returncode)
        print("Stdout:", proc.stdout.decode('utf-8'))
        print("Stderr:", proc.stderr.decode('utf-8'))

        exit(proc.returncode)

    stderr = proc.stderr.decode('utf-8')
    try:
        scalene_json = json.loads(stderr)
    except json.JSONDecodeError:
        print("Invalid JSON", stderr)
        exit(1)
    if len(scalene_json) == 0:
        print("No JSON output")
        exit(1)
    files = scalene_json['files']
    if not len(files) > 0:
        print("No files found in output")
        exit(1)
    _fname = list(files.keys())[0]
    function_list = files[_fname]['functions']
    exit_code = 0

    # if 'doit1' not in function_dict:
    expected_functions = ['doit1', 'doit3']
    unexpected_functions = ['doit2']
    for fn_name in expected_functions:
        if not any(fn_name in f['line'] for f in function_list):
            print(f"Expected function '{fn_name}' not returned")
            exit_code = 1
    for fn_name in unexpected_functions:
        if any(fn_name in f['line'] for f in function_list):
            print(f"Unexpected function '{fn_name}' returned")
            exit_code = 1
    if exit_code != 0:
        print(function_list)
        exit(exit_code)

if __name__ == '__main__':
    smoketest('test/profile_annotation_test.py')
