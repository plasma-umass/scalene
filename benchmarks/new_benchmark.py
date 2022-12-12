import json
import subprocess
import re
import statistics
from glob import glob
from collections import defaultdict
import sys

cmds = {
    # "baseline": ["python3"],
    # "scalene": ["python3", "-m", "scalene", "--json", "--outfile", "/dev/null"],
    # "scalene-cpu": ["python3", "-m", "scalene", "--json", "--cpu", "--outfile", "/dev/null"],
    # "scalene-cpu-gpu": ["python3", "-m", "scalene", "--json", "--cpu", "--gpu", "--outfile", "/dev/null"],
    # "scalene-5M":  ["python3", "-m", "scalene", "--json", "--outfile", "/dev/null", "--allocation-sampling-window", "5242883"],
    # "scalene-10M": ["python3", "-m", "scalene", "--json", "--outfile", "/dev/null", "--allocation-sampling-window", "10485767"],
    # "scalene-20M": ["python3", "-m", "scalene", "--json", "--outfile", "/dev/null", "--allocation-sampling-window","20971529"],
    # "memray": [
    #     "python3",
    #     "-m",
    #     "memray",
    #     "run",
    #     "--trace-python-allocators",
    #     "-f",
    #     "-o",
    #     "/tmp/memray.out",
    # ],
    # "fil": ["fil-profile", "-o", "/tmp/abc", '--no-browser', "run"],
    # "austin_full": ["austin", "-o", "/dev/null", "-f"],
    # "austin_cpu": ["austin", "-o", "/dev/null"],
    # 'py-spy': ['py-spy', 'record', '-o', '/tmp/profile.svg', '--', 'python3'],
    # 'cProfile': ['python3', '-m', 'cProfile', '-o', '/dev/null'],
    'yappi_wall': ['python3', '-m', 'yappi', '-o', '/dev/null', '-c', 'wall'],
    'yappi_cpu': ['python3', '-m', 'yappi', '-o', '/dev/null', '-c', 'cpu'],
    # 'pprofile_det': ['pprofile', '-o', '/dev/null'],
    # 'pprofile_stat': ['pprofile', '-o', '/dev/null', '-s', '0.001'],
    # 'line_profiler': ['kernprof', '-l', '-o', '/dev/null', '-v'],
    # 'profile': ['python3', '-m', 'profile', '-o', '/dev/null']
}
result_regexp = re.compile(r"Time elapsed:\s+([0-9]*\.[0-9]+)")


def main():
    out = defaultdict(lambda : {})
    
    for progname in [
        # "./test/expensive_benchmarks/bm_mdp.py",
        # "./test/expensive_benchmarks/bm_async_tree_io.py none",
        # "./test/expensive_benchmarks/bm_async_tree_io.py io",
        # "./test/expensive_benchmarks/bm_async_tree_io.py cpu_io_mixed",
        # "./test/expensive_benchmarks/bm_async_tree_io.py memoization",
        # "./test/expensive_benchmarks/bm_fannukh.py",
        # "./test/expensive_benchmarks/bm_pprint.py",
        # "./test/expensive_benchmarks/bm_raytrace.py",
        # "./test/expensive_benchmarks/bm_sympy.py",
        "./test/expensive_benchmarks/bm_docutils.py"
    ]:
        for profile_name, profile_cmd in cmds.items():
            times = []
            for i in range(5):
                print(
                    f"Running {profile_name} on {progname} using \"{' '.join(profile_cmd + progname.split(' '))}\"...",
                    end="",
                    flush=True,
                )
                result = subprocess.run(
                    profile_cmd + progname.split(' '),
                    stderr=subprocess.STDOUT,
                    stdout=subprocess.PIPE,
                )
                
                output = result.stdout.decode("utf-8")
                # print(output)
                match = result_regexp.search(output)
                if match is not None:
                    print(f"... {match.group(1)}", end=('\n' if profile_name != 'memray' else ''))
                    times.append(round(100 * float(match.group(1))) / 100.0)
                    if profile_name == 'memray':
                        res2 = subprocess.run(
                            ['time', 
                            sys.executable,
                            '-m', 
                            'memray',
                            'flamegraph',
                            '-f',
                            '/tmp/memray.out'],
                            capture_output=True,
                            env={'TIME': 'Time elapsed: %e'}
                        )
                        output2 = res2.stderr.decode("utf-8")
                        match2 = result_regexp.search(output2)
                        if match2 is not None:
                            print(f"... {match2.group(1)}")
                            times[-1] += round(100 * float(match2.group(1))) / 100.0
                        else:
                            print("... RUN FAILED")
                            # exit(1)
                else:
                    print("RUN FAILED")
                    # exit(1)
            out[profile_name][progname] = times
    with open('yappi.json', 'w+') as f:
        json.dump(dict(out), f)


if __name__ == "__main__":
    main()
