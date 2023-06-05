#!/usr/bin/env python3
import subprocess
import sys
import json

def smoketest(fname, rest):
    proc = subprocess.run( [sys.executable, "-m", "scalene", "--cli", "--json", "--outfile", "/dev/stderr", *rest, fname] ,capture_output=True)
    if proc.returncode != 0:
        print("Exited with a non-zero code:", proc.returncode)
        print("Stdout:", sys.stdout.decode('utf-8'))
        exit(proc.returncode)

    stderr = proc.stderr.decode('utf-8')
    print(stderr)
    try:
        scalene_json = json.loads(stderr)
    except json.JSONDecodeError:
        print("Invalid JSON", stderr)
        exit(1)
    files = scalene_json['files']
    if not len(files) > 0:
        print("No files found in output")
        exit(1)
    for _fname in files:
        if not any( (line['n_cpu_percent_c'] > 0 or line['n_cpu_percent_python'] > 0) for line in files[fname]['lines']):
            print("No non-zero lines in", _fname)
            exit(1)

if __name__ == '__main__':
    smoketest(sys.argv[1], sys.argv[2:])
