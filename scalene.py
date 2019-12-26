"""

  Scalene: a high-performance sampling CPU *and* memory profiler for Python.

  Scalene uses interrupt-driven sampling for CPU profiling. For memory
  profiling, it uses a similar mechanism but with interrupts generated
  by a "sampling memory allocator" that produces signals everytime the
  heap grows by a certain amount. See libcheaper.cpp for details.

  by Emery Berger
  https://emeryberger.com

  usage: # for CPU profiling only
         python -m scalene test/testme.py  
         # for CPU and memory profiling (Mac OS X)
         DYLD_INSERT_LIBRARIES=$PWD/libcheaper.dylib PYTHONMALLOC=malloc python -m scalene test/testme.py
         # for CPU and memory profiling (Linux)
         LD_PRELOAD=$PWD/libcheaper.dylib PYTHONMALLOC=malloc python -m scalene test/testme.py

"""

import sys
import atexit
import signal
import os
from collections import defaultdict

assert sys.version_info[0] == 3 and sys.version_info[1] >= 7, "This tool requires Python version 3.7 or above."

class scalene_profiler:

    # CPU samples (key = filename+':'+function+':'+lineno)
    cpu_samples = defaultdict(lambda: 0)
    
    # same format but for memory usage
    mem_samples = defaultdict(lambda: 0)
    
    total_cpu_samples = 0       # how many samples have been collected.
    total_mem_samples = 0       # how many memory usage samples have been collected.
    signal_interval = 0.01      # seconds between interrupts for CPU sampling.
    
    def __init__(self):
        # Set up the signal handler to handle periodic timer interrupts (for CPU).
        signal.signal(signal.SIGPROF, self.cpu_signal_handler)
        # Set up the signal handler to handle malloc interrupts (for memory allocations).
        signal.signal(signal.SIGVTALRM, self.malloc_signal_handler)
        # Turn on the timer.
        signal.setitimer(signal.ITIMER_PROF, self.signal_interval, self.signal_interval)
        pass

    @staticmethod
    def make_key(frame):
        """Returns a key for tracking where this interrupt came from. Returns None for code we are not tracing."""
        co = frame.f_code
        func_name = co.co_name
        line_no = frame.f_lineno
        filename = co.co_filename
        key = filename + '\t' + func_name + '\t' + str(line_no)
        if not scalene_profiler.should_trace(filename):
            return None
        return key
        
    @staticmethod
    def cpu_signal_handler(sig, frame):
        # Increase the signal interval geometrically until we hit once
        # per second.  This approach means we can successfully profile
        # even quite short lived programs.
        if scalene_profiler.signal_interval < 1:
            scalene_profiler.signal_interval *= 1.2
            # Reset the timer for the new interval.
            signal.setitimer(signal.ITIMER_PROF, scalene_profiler.signal_interval, scalene_profiler.signal_interval)
        key = scalene_profiler.make_key(frame)
        if key is None:
            return
        scalene_profiler.cpu_samples[key] += 1
        scalene_profiler.total_cpu_samples += 1
        return

    @staticmethod
    def malloc_signal_handler(sig, frame):
        key = scalene_profiler.make_key(frame)
        if key is None:
            return
        scalene_profiler.mem_samples[key] += 1
        scalene_profiler.total_mem_samples += 1
        return

    @staticmethod
    def should_trace(filename):
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
        atexit.register(scalene_profiler.exit_handler)


    @staticmethod
    def exit_handler():
        # Turn off the profiling signals.
        signal.signal(signal.ITIMER_PROF, signal.SIG_IGN)
        signal.signal(signal.SIGVTALRM, signal.SIG_IGN)
        signal.setitimer(signal.ITIMER_PROF, 0)
        # If we've collected any samples, dump them.
        print("CPU usage:")
        if scalene_profiler.total_cpu_samples > 0:
            # Sort the samples in descending order by number of samples.
            scalene_profiler.cpu_samples = { k: v for k, v in sorted(scalene_profiler.cpu_samples.items(), key=lambda item: item[1], reverse=True) }
            for key in scalene_profiler.cpu_samples:
                print(key + " : " + str(scalene_profiler.cpu_samples[key] * 100 / scalene_profiler.total_cpu_samples) + "%" + " (" + str(scalene_profiler.cpu_samples[key]) + " total samples)")
        else:
            print("(did not run long enough to profile)")
        # If we've collected any samples, dump them.
        print("")
        print("Memory usage:")
        if scalene_profiler.total_mem_samples > 0:
            # Sort the samples in descending order by number of samples.
            scalene_profiler.mem_samples = { k: v for k, v in sorted(scalene_profiler.mem_samples.items(), key=lambda item: item[1], reverse=True) }
            for key in scalene_profiler.mem_samples:
                print(key + " : " + str(scalene_profiler.mem_samples[key] * 100 / scalene_profiler.total_mem_samples) + "%" + " (" + str(scalene_profiler.mem_samples[key]) + " total samples)")
        else:
            print("(did not allocate enough memory to profile)")
        
       

if __name__ == "__main__":
    assert len(sys.argv) >= 2, "Usage example: python -m scalene test.py"
    profiler = scalene_profiler()
    with open(sys.argv[1], 'rb') as fp:
        code = compile(fp.read(), sys.argv[1], "exec")
    profiler.start()
    
    exec(code)

