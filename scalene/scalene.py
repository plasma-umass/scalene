"""Scalene: a high-performance sampling CPU *and* memory profiler for Python.

  Scalene uses interrupt-driven sampling for CPU profiling. For memory
  profiling, it uses a similar mechanism but with interrupts generated
  by a "sampling memory allocator" that produces signals everytime the
  heap grows or shrinks by a certain amount. See libcheaper.cpp for
  details.

  by Emery Berger
  https://emeryberger.com

  usage: # for CPU profiling only
         python -m scalene test/testme.py  
         # for CPU and memory profiling (Mac OS X)
         DYLD_INSERT_LIBRARIES=$PWD/libcheaper.dylib PYTHONMALLOC=malloc python -m scalene test/testme.py
         # for CPU and memory profiling (Linux)
         LD_PRELOAD=$PWD/libcheaper.dylib PYTHONMALLOC=malloc python -m scalene test/testme.py

"""

the_globals = {
    '__name__': '__main__',
    '__doc__': None,
    '__package__': None,
    '__loader__': globals()['__loader__'],
    '__spec__': None,
    '__annotations__': {},
    '__builtins__': globals()['__builtins__'],
    '__file__': None,
    '__cached__': None,
}

import sys
import atexit
import signal
import json
import linecache
import math
from collections import defaultdict
import time
from pathlib import Path
import os
import traceback

assert sys.version_info[0] == 3 and sys.version_info[1] >= 6, "This tool requires Python version 3.6 or above."

class scalene(object):

    cpu_samples    = defaultdict(lambda: defaultdict(int))        # CPU    samples for each location in the program.
    malloc_samples = defaultdict(lambda: defaultdict(int))        # malloc "       "   "    "        "   "  "
    free_samples   = defaultdict(lambda: defaultdict(int))        # free   "       "   "    "        "   "  "
    total_cpu_samples      = 0           # how many CPU    samples have been collected.
    total_malloc_samples   = 0           # "   "    malloc "       "    "    "
    total_free_samples     = 0           # "   "    free   "       "    "    "
    signal_interval        = 0.01        # seconds between interrupts for CPU sampling.
    elapsed_time           = 0           # total time spent in program being profiled.
    memory_sampling_rate   = 64 * 1024  # we get signals after this many bytes are allocated/freed. 
                                         # NB: MUST BE IN SYNC WITH include/sampleheap.cpp!
    current_footprint      = 0           # current memory footprint
    program_being_profiled = ""          # name of program being profiled.
    program_path           = ""          # path "  "       "     "
    
    def __init__(self, program_being_profiled):
        # Register the exit handler to run when the program terminates or we quit.
        atexit.register(scalene.exit_handler)
        # Store relevant names (program, path).
        scalene.program_being_profiled = os.path.abspath(program_being_profiled)
        scalene.program_path = os.path.dirname(scalene.program_being_profiled)
        # Set up the signal handler to handle periodic timer interrupts (for CPU).
        signal.signal(signal.SIGPROF, self.cpu_signal_handler)
        # Set up the signal handler to handle malloc interrupts (for memory allocations).
        signal.signal(signal.SIGVTALRM, self.malloc_signal_handler)
        signal.signal(signal.SIGXCPU, self.free_signal_handler)
        # Turn on the CPU profiling timer to run every signal_interval seconds.
        signal.setitimer(signal.ITIMER_PROF, self.signal_interval, self.signal_interval)

   
    @staticmethod
    def cpu_signal_handler(sig, frame):
        """Handle interrupts for CPU profiling."""
        fname = frame.f_code.co_filename
        # Record samples only for files we care about.
        if not scalene.should_trace(fname):
            return
        scalene.cpu_samples[fname][frame.f_lineno] += 1
        scalene.total_cpu_samples += 1
        return

    @staticmethod
    def malloc_signal_handler(sig, frame):
        """Handle interrupts for memory profiling (mallocs)."""
        fname = frame.f_code.co_filename
        # Record samples only for files we care about.
        if not scalene.should_trace(fname):
            return
        scalene.malloc_samples[fname][frame.f_lineno] += 1
        scalene.total_malloc_samples += 1
        scalene.current_footprint += 1
        return

    @staticmethod
    def free_signal_handler(sig, frame):
        """Handle interrupts for memory profiling (frees)."""
        fname = frame.f_code.co_filename
        # Record samples only for files we care about.
        if not scalene.should_trace(fname):
            return
        scalene.free_samples[fname][frame.f_lineno] += 1
        scalene.total_free_samples += 1
        scalene.current_footprint -= 1
        return
    
    @staticmethod
    def should_trace(filename):
        """Return true if the filename is one we should trace."""
        # Profile anything in the program's directory or a child directory,
        # but nothing else.
        if filename[0] == '<':
            # Don't profile Python internals.
            return False
        if 'scalene.py' in filename:
            # Don't profile the profiler.
            return False
        filename = os.path.abspath(filename)
        return scalene.program_path in filename

    @staticmethod
    def start():
        scalene.elapsed_time = time.perf_counter()
    
    @staticmethod
    def stop():
        scalene.disable_signals()
        scalene.elapsed_time = time.perf_counter() - scalene.elapsed_time

    @staticmethod
    def output_profiles():
        total_mem_samples = scalene.total_malloc_samples + scalene.total_free_samples # use + scalene.total_free_samples for churn.
        # Collect all instrumented filenames.
        all_instrumented_files = list(set(list(scalene.cpu_samples.keys()) + list(scalene.malloc_samples.keys()) + list(scalene.free_samples.keys())))
        for fname in sorted(all_instrumented_files):
            with open(fname, 'r') as fd:
                this_cpu_samples = sum(scalene.cpu_samples[fname].values())
                if this_cpu_samples == 0:
                    continue
                percent_cpu_time = 100 * this_cpu_samples * \
                    scalene.signal_interval / scalene.elapsed_time
                print(f"{fname}: % of CPU time = {percent_cpu_time:6.2f}% out of {scalene.elapsed_time:6.2f}s.")
                print(f"  Line\t | {'CPU %':9}| {'Memory (MB)|' if total_mem_samples != 0 else ''}\t[{fname}]")
                contents = fd.readlines()
                line_no = 1
                for line in contents:
                    line = line[:-1] # Strip newline
                    n_cpu_samples = scalene.cpu_samples[fname][line_no]
                    n_mem_mb = 0
                    n_mem_samples = scalene.malloc_samples[fname][line_no] - scalene.free_samples[fname][line_no]
                    if n_mem_samples != 0:
                        r = n_mem_samples * scalene.memory_sampling_rate
                        n_mem_mb = r / (1024 * 1024)
                    if scalene.total_cpu_samples != 0:
                        n_cpu_percent = n_cpu_samples * 100 / scalene.total_cpu_samples
                    # Print results.
                    n_cpu_percent_str = "" if n_cpu_percent == 0 else f'{n_cpu_percent:6.2f}%'
                    n_mem_mb_str      = "" if n_mem_mb == 0      else f'{n_mem_mb:>9.2f}'
                    if total_mem_samples != 0:
                        print(f"{line_no:6d}\t | {n_cpu_percent_str:9s}| {n_mem_mb_str:8s}\t |\t{line}")
                    else:
                        print(f"{line_no:6d}\t | {n_cpu_percent_str:9s}|\t{line}")
                    line_no += 1
                print("")


    @staticmethod
    def disable_signals():
        # Turn off the profiling signals.
        signal.signal(signal.ITIMER_PROF, signal.SIG_IGN)
        signal.signal(signal.SIGVTALRM, signal.SIG_IGN)
        signal.signal(signal.SIGXCPU, signal.SIG_IGN)
        signal.setitimer(signal.ITIMER_PROF, 0)
        
    @staticmethod
    def exit_handler():
        scalene.disable_signals()

    @staticmethod
    def main():
        assert len(sys.argv) >= 2, "Usage example: python -m scalene test.py"
        try:
            with open(sys.argv[1], 'rb') as fp:
                original_path = os.getcwd()
                # Read in the code and compile it.
                code = compile(fp.read(), sys.argv[1], "exec")
                # Remove the profiler from the args list.
                sys.argv.pop(0)
                # Push the program's path.
                program_path = os.path.dirname(os.path.abspath(sys.argv[0]))
                sys.path.insert(0, program_path)
                os.chdir(program_path)
                # Set the file being executed.
                the_globals['__file__'] = sys.argv[0]
                # Start the profiler.
                profiler = scalene(os.path.join(program_path, os.path.basename(sys.argv[0])))
                try:
                    profiler.start()
                    # Run the code being profiled.
                    exec(code, the_globals)
                    profiler.stop()
                    # Go back home.
                    os.chdir(original_path)
                    # If we've collected any samples, dump them.
                    if profiler.total_cpu_samples > 0:
                        profiler.output_profiles()
                    else:
                        print("scalene: Program did not run for long enough to profile.")
                except Exception as ex:
                    template = "scalene: An exception of type {0} occurred. Arguments:\n{1!r}"
                    message = template.format(type(ex).__name__, ex.args)
                    print(message)
                    print(traceback.format_exc())
        except (FileNotFoundError, IOError):
            print("scalene: could not find input file.")
    
scalene.main()
