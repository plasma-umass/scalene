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

GLOBALS = globals().copy()

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

import os
import traceback

assert sys.version_info[0] == 3 and sys.version_info[1] >= 7, "This tool requires Python version 3.7 or above."

class scalene(object):

    cpu_samples = defaultdict(lambda: 0) # Samples for each location in the program.
    malloc_samples = defaultdict(lambda: 0) # Ibid, but for malloc.
    free_samples = defaultdict(lambda: 0)   # Ibid, but for free.
    total_cpu_samples      = 0           # how many CPU samples have been collected.
    total_malloc_samples   = 0           # how many malloc samples have been collected.
    total_free_samples     = 0           # how many free samples have been collected.
    signal_interval        = 0.001       # seconds between interrupts for CPU sampling.
    elapsed_time           = 0           # time spent in program being profiled.
    program_being_profiled = ""          # name of program being profiled.
    memory_sampling_rate   = 128 * 1024  # must be in sync with include/sampleheap.cpp
    current_footprint      = 0           # current memory footprint
    
    def __init__(self, program_being_profiled):
        scalene.program_being_profiled = program_being_profiled
        atexit.register(scalene.exit_handler)
        # Set up the signal handler to handle periodic timer interrupts (for CPU).
        signal.signal(signal.SIGPROF, self.cpu_signal_handler)
        # Set up the signal handler to handle malloc interrupts (for memory allocations).
        signal.signal(signal.SIGVTALRM, self.malloc_signal_handler)
        signal.signal(signal.SIGXCPU, self.free_signal_handler)
        # Turn on the timer.
        signal.setitimer(signal.ITIMER_PROF, self.signal_interval, self.signal_interval)
        pass

    @staticmethod
    def make_key(frame):
        """Returns a key for tracking where this interrupt came from. Returns None for code we are not tracing. See extract_from_key."""
        co = frame.f_code
        filename = co.co_filename
        if not scalene.should_trace(filename):
            return None
        # func_name = co.co_name
        line_no = frame.f_lineno
        key = json.dumps({'filename' : filename,
                          # 'func_name' : func_name,
                          'line_no' : line_no })
        return key

   
    @staticmethod
    def extract_from_key(key):
        """Get the original payload data structure from the key."""
        return json.loads(key)
        
    @staticmethod
    def cpu_signal_handler(sig, frame):
        """Handle interrupts for CPU profiling."""
        key = scalene.make_key(frame)
        if key is None:
            return
        scalene.cpu_samples[key] += 1
        scalene.total_cpu_samples += 1
        return

    @staticmethod
    def malloc_signal_handler(sig, frame):
        """Handle interrupts for memory profiling (mallocs)."""
        key = scalene.make_key(frame)
        if key is None:
            # We aren't profiling memory from this file.
            return
        scalene.malloc_samples[key] += 1
        scalene.total_malloc_samples += 1
        scalene.current_footprint += scalene.memory_sampling_rate
        # print("MALLOC: footprint now = {}".format(scalene.current_footprint / (1024*1024)))
        return

    @staticmethod
    def free_signal_handler(sig, frame):
        """Handle interrupts for memory profiling (frees)."""
        key = scalene.make_key(frame)
        if key is None:
            # We aren't profiling memory from this file.
            return
        scalene.free_samples[key] += 1
        scalene.total_free_samples += 1
        scalene.current_footprint -= scalene.memory_sampling_rate
        # print("FREE: footprint now = {}".format(scalene.current_footprint / (1024*1024)))
        return
    
    @staticmethod
    def should_trace(filename):
        """Return true if the filename is one we should trace."""
        # For now, only profile the program being profiled.
        if scalene.program_being_profiled == filename:
            return True
        return False
   
        # Don't trace the profiler itself.
        if 'scalene.py' in filename:
            return False
        # Don't trace Python builtins.
        if '<frozen importlib._bootstrap>' in filename:
            return False
        if '<frozen importlib._bootstrap_external>' in filename:
            return False
        return True

    @staticmethod
    def start():
        scalene.elapsed_time = time.perf_counter() # time.process_time() # perf_counter()

    @staticmethod
    def margin_of_error(prop, nsamples):
        return 1.96 * math.sqrt(prop * (1-prop) / nsamples)

    @staticmethod
    def dump_code():
        max_moe_cpu = 0 # Maximum 95% confidence interval for margin of error (for CPU %).
        max_moe_mem = 0 # Maximum 95% confidence interval for margin of error (for memory %).
        mallocs = sum(scalene.malloc_samples.values())
        frees   = sum(scalene.free_samples.values())
        average_footprint_mb = (mallocs - frees) * scalene.memory_sampling_rate / (1024 * 1024)
        total_cpu_samples = scalene.total_cpu_samples
        total_mem_samples = scalene.total_malloc_samples # use + scalene.total_free_samples for churn.
        if total_cpu_samples + total_mem_samples == 0:
            print("scalene: no samples collected.")
            return
        if total_mem_samples > 0:
            # Malloc tracking is on.
            print("  Line\t | {:9}| {:26s} |  {:6s}".format("CPU", "Memory", ""))
        else:
            print("  Line\t | {:9}| {:6s}".format("CPU", ""))
        with open(scalene.program_being_profiled, 'r') as fd:
            contents = fd.readlines()
            line_no = 1
            for line in contents:
                line = line[:-1] # Strip newline
                key = (scalene.program_being_profiled, line_no)
                key = json.dumps({'filename' : scalene.program_being_profiled,
                                  'line_no' : line_no })
                n_cpu_samples = scalene.cpu_samples[key]
                n_mem_samples = scalene.malloc_samples[key] - scalene.free_samples[key] # + for delta, - for churn.
                n_cpu_percent = 0
                n_mem_percent = 0
                # Update margins of error.
                if total_cpu_samples != 0 and n_cpu_samples != 0:
                    n_cpu_percent = n_cpu_samples * 100 / total_cpu_samples
                    moe_cpu = scalene.margin_of_error(n_cpu_samples / total_cpu_samples, total_cpu_samples)
                    max_moe_cpu = max(moe_cpu, max_moe_cpu)
                if total_mem_samples != 0 and n_mem_samples != 0:
                    n_mem_percent = n_mem_samples * 100 / total_mem_samples
                    moe_mem = scalene.margin_of_error(abs(n_mem_samples) / total_mem_samples, total_mem_samples)
                    max_moe_mem = max(moe_mem, max_moe_mem)
                # Print results.
                if total_mem_samples != 0:
                    if n_mem_percent != 0 and n_cpu_percent != 0:
                        print("{:6d}\t | {:6.2f}%  | {:6.2f}% ({:6.2f}MB)\t | \t{}".format(line_no, n_cpu_percent, n_mem_percent, n_mem_percent / 100 * average_footprint_mb, line))
                    elif n_mem_percent != 0 and n_cpu_percent == 0:
                        print("{:6d}\t | {:9}| {:6.2f}% ({:6.2f}MB)\t | \t{}".format(line_no, "", n_mem_percent, n_mem_percent / 100 * average_footprint_mb, line))
                    elif n_mem_percent == 0 and n_cpu_percent != 0:
                        print("{:6d}\t | {:6.2f}%  | {:9}  {:9}\t | \t{}".format(line_no, n_cpu_percent, "", "", line))
                    else:
                        print("{:6d}\t | {:9}| {:9}  {:9}\t | \t{}".format(line_no, "", "", "", line))
                else:
                    if n_cpu_percent != 0:
                        print("{:6d}\t | {:6.2f}%  | \t{}".format(line_no, n_cpu_percent, line))
                    else:
                        print("{:6d}\t | {:9}| \t{}".format(line_no, "", line))
                line_no += 1
            print("Maximum margin of error for CPU measurements: +/-{:6.2f}% (95% confidence).".format(max_moe_cpu * 100))
            if total_mem_samples > 0:
                print("Maximum margin of error for memory measurements: +/-{:6.2f}% (95% confidence).".format(max_moe_mem * 100))
            print("% of CPU time in program under profile: {:6.2f}% out of {:6.2f}s.".format(100 * total_cpu_samples * scalene.signal_interval / scalene.elapsed_time, scalene.elapsed_time))
       
        
    @staticmethod
    def exit_handler():
        # Turn off the profiling signals.
        signal.signal(signal.ITIMER_PROF, signal.SIG_IGN)
        signal.signal(signal.SIGVTALRM, signal.SIG_IGN)
        signal.signal(signal.SIGXCPU, signal.SIG_IGN)
        signal.setitimer(signal.ITIMER_PROF, 0)

    @staticmethod
    def main():
        assert len(sys.argv) >= 2, "Usage example: python -m scalene test.py"
        try:
            with open(sys.argv[1], 'rb') as fp:
                # Read in the code and compile it.
                code = compile(fp.read(), sys.argv[1], "exec")
                # Remove the profiler from the args list.
                sys.argv.pop(0)
                # Start the profiler.
                profiler = scalene(sys.argv[0])
                profiler.start()
                try:
                    # Run the code being profiled.
                    exec(code, the_globals)
                    # Get elapsed time.
                    scalene.elapsed_time = time.perf_counter() - scalene.elapsed_time
                    # If we've collected any samples, dump them.
                    if profiler.total_cpu_samples > 0:
                        profiler.dump_code()
                except Exception as ex:
                    template = "scalene: An exception of type {0} occurred. Arguments:\n{1!r}"
                    message = template.format(type(ex).__name__, ex.args)
                    print(message)
                    print(traceback.format_exc())
        except (FileNotFoundError, IOError):
            print("scalene: could not find input file.")
    
scalene.main()
