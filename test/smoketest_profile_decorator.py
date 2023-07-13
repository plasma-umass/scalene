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
    # stdout = proc.stdout.decode('utf-8')
    stderr = proc.stderr.decode('utf-8')
#    print("STDOUT", stdout)
#    print("\nSTDERR", stderr)
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
    if not any('doit1' in f['line'] for f in function_list):
        print("Expected function 'doit1' not returned")
        exit_code = 1

    if not any('doit2' in f['line'] for f in function_list):
        print("Expected function 'doit2' not returned")
        exit_code = 1
    if exit_code != 0:
        # print(files)
        print(function_list)
        exit(exit_code)

if __name__ == '__main__':
    smoketest('test/profile_annotation_test.py')
