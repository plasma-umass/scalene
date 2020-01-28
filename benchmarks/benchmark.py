import os
import sys
import re
import subprocess
import traceback
import statistics

python = "python3"
progname = "/Users/emery/git/scalene/benchmarks/julia1_nopil.py"
number_of_runs = 1 # We take the average of this many runs.

# Output timing string from the benchmark.
result_regexp = re.compile("calculate_z_serial_purepython  took ([0-9]*\.[0-9]+) seconds")

# Characteristics of the tools.

line_level = {}
cpu_profiler = {}
separate_profiler = {}
memory_profiler = {}
unmodified_code = {}


line_level["baseline"] = None
line_level["cProfile"] = False
line_level["Profile"] = False
line_level["line_profiler"] = True
line_level["pyinstrument"] = False
line_level["yappi_cputime"] = False
line_level["yappi_wallclock"] = False
line_level["pprofile_deterministic"] = True
line_level["pprofile_statistical"] = True
line_level["memory_profiler"] = True
line_level["scalene_cpu"] = True
line_level["scalene_cpu_memory"] = True

cpu_profiler["baseline"] = None
cpu_profiler["cProfile"] = True
cpu_profiler["Profile"] = True
cpu_profiler["pyinstrument"] = True
cpu_profiler["line_profiler"] = True
cpu_profiler["yappi_cputime"] = True
cpu_profiler["yappi_wallclock"] = True
cpu_profiler["pprofile_deterministic"] = True
cpu_profiler["pprofile_statistical"] = True
cpu_profiler["memory_profiler"] = False
cpu_profiler["scalene_cpu"] = True
cpu_profiler["scalene_cpu_memory"] = True

separate_profiler["baseline"] = None
separate_profiler["cProfile"] = False
separate_profiler["Profile"] = False
separate_profiler["pyinstrument"] = False
separate_profiler["line_profiler"] = False
separate_profiler["yappi_cputime"] = False
separate_profiler["yappi_wallclock"] = False
separate_profiler["pprofile_deterministic"] = False
separate_profiler["pprofile_statistical"] = False
separate_profiler["memory_profiler"] = False
separate_profiler["scalene_cpu"] = True
separate_profiler["scalene_cpu_memory"] = True

memory_profiler["baseline"] = None
memory_profiler["cProfile"] = False
memory_profiler["Profile"] = False
memory_profiler["pyinstrument"] = False
memory_profiler["line_profiler"] = False
memory_profiler["yappi_cputime"] = False
memory_profiler["yappi_wallclock"] = False
memory_profiler["pprofile_deterministic"] = False
memory_profiler["pprofile_statistical"] = False
memory_profiler["memory_profiler"] = True
memory_profiler["scalene_cpu"] = False
memory_profiler["scalene_cpu_memory"] = True

unmodified_code["baseline"] = None
unmodified_code["cProfile"] = True
unmodified_code["Profile"] = True
unmodified_code["pyinstrument"] = True
unmodified_code["line_profiler"] = False
unmodified_code["yappi_cputime"] = True
unmodified_code["yappi_wallclock"] = True
unmodified_code["pprofile_deterministic"] = True
unmodified_code["pprofile_statistical"] = True
unmodified_code["memory_profiler"] = False
unmodified_code["scalene_cpu"] = True
unmodified_code["scalene_cpu_memory"] = True

# Command lines for the various tools.

baseline = f"{python} {progname}"
cprofile = f"{python} -m cProfile {progname}"
profile = f"{python} -m profile {progname}"
pyinstrument = f"pyinstrument {progname}"
line_profiler = f"{python} -m kernprof -l -v {progname}"
pprofile_deterministic = f"pprofile {progname}"
pprofile_statistical = f"pprofile --statistic 0.001 {progname}" # Same as Scalene
yappi_cputime = f"yappi {progname}"
yappi_wallclock = f"yappi -c wall {progname}"
scalene_cpu = f"{python} -m scalene {progname}"
scalene_cpu_memory = f"{python} -m scalene {progname}" # see below for environment variables

benchmarks = [(baseline, "baseline", "_original program_"), (cprofile, "cProfile", "`cProfile`"), (profile, "Profile", "`Profile`"), (pyinstrument, "pyinstrument", "`pyinstrument`"), (line_profiler, "line_profiler", "`line_profiler`"), (pprofile_deterministic, "pprofile_deterministic", "`pprofile` _(deterministic)_"), (pprofile_statistical, "pprofile_statistical", "`pprofile` _(statistical)_"), (yappi_cputime, "yappi_cputime", "`yappi` _(CPU)_"), (yappi_wallclock, "yappi_wallclock", "`yappi` _(wallclock)_"), (scalene_cpu, "scalene_cpu", "`scalene` _(CPU only)_"), (scalene_cpu_memory, "scalene_cpu_memory", "`scalene` _(CPU + memory)_")]

# benchmarks = [(baseline, "baseline", "_original program_"), (pprofile_deterministic, "`pprofile` _(deterministic)_")]
# benchmarks = [(baseline, "baseline", "_original program_"), (pprofile_statistical, "pprofile_statistical", "`pprofile` _(statistical)_")]

average_time = {}
check = ":heavy_check_mark:"

print("|                            | Time (seconds) | Slowdown | Line-level?    | CPU? | Python vs. C? | Memory? | Unmodified code? |")
print("| :--- | ---: | ---: | :---: | :---: | :---: | :---: | :---: |")

for bench in benchmarks:
    # print(bench)
    times = []
    for i in range(0, number_of_runs):
        my_env = os.environ.copy()
        if bench[1] == "scalene_cpu_memory":
            my_env["PYTHONMALLOC"] = "malloc"
            if sys.platform == 'darwin':
                my_env["DYLD_INSERT_LIBRARIES"] = "./libscalene.dylib"
            if sys.platform == 'linux':
                my_env["LD_PRELOAD"] = "./libscalene.so"
        result = subprocess.run(bench[0].split(), env = my_env, stdout = subprocess.PIPE)
        output = result.stdout.decode('utf-8')
        match = result_regexp.search(output)
        if match is not None:
            times.append(round(100 * float(match.group(1))) / 100.0)
        else:
            print("failed run")
    average_time[bench[1]] = statistics.mean(times) # sum_time / (number_of_runs * 1.0)
    print(str(average_time[bench[1]]))
    if bench[1] == "baseline":
        print(f"| {bench[2]} | {average_time[bench[1]]}s | 1.0x | | | | | |")
        print("|               |     |        |                    | |")
    else:
        try:
            if bench[1].find("scalene") >= 0:
                if bench[1].find("scalene_cpu") >= 0:
                    print("|               |     |        |                    | |")
                print(f"| {bench[2]} | {average_time[bench[1]]}s | **{round(100 * average_time[bench[1]] / average_time['baseline']) / 100}x** | {check if line_level[bench[1]] else 'function-level'} | {check if cpu_profiler[bench[1]] else ''} | {check if separate_profiler[bench[1]] else ''} | {check if memory_profiler[bench[1]] else ''} | {check if unmodified_code[bench[1]] else 'needs `@profile` decorators'} |")
            else:
                print(f"| {bench[2]} | {average_time[bench[1]]}s | {round(100 * average_time[bench[1]] / average_time['baseline']) / 100}x | {check if line_level[bench[1]] else 'function-level'} | {check if cpu_profiler[bench[1]] else ''} | {check if separate_profiler[bench[1]] else ''} | {check if memory_profiler[bench[1]] else ''} | {check if unmodified_code[bench[1]] else 'needs `@profile` decorators'} |")
        except Exception as err:
            traceback.print_exc()
            print("err = " + str(err))
            print("WOOPS")
#    print(bench[1] + " = " + str(sum_time / 5.0))
    
