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
from time import perf_counter
import json
from collections import defaultdict

assert sys.version_info[0] == 3 and sys.version_info[1] >= 7, "This tool requires Python version 3.7 or above."

class scalene_profiler:

    # CPU samples (key = filename+':'+function+':'+lineno)
    cpu_samples = defaultdict(lambda: 0)
    
    # same format but for memory usage
    mem_samples = defaultdict(lambda: 0)
    
    total_cpu_samples = 0       # how many samples have been collected.
    total_mem_samples = 0       # how many memory usage samples have been collected.
    signal_interval   = 0.01    # seconds between interrupts for CPU sampling.
    elapsed_time      = 0       # measures total elapsed time of client execution.
    
    def __init__(self):
        atexit.register(scalene_profiler.exit_handler)
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
        if not scalene_profiler.should_trace(filename):
            return None
        key = json.dumps({'filename' : filename,
                          'func_name' : func_name,
                          'line_no' : line_no })
        # key = filename + '\t' + func_name + '\t' + str(line_no)
        return key

    @staticmethod
    def extract_from_key(key):
        return json.loads(key)
        
    @staticmethod
    def cpu_signal_handler(sig, frame):
        # Increase the signal interval geometrically until we hit once
        # per second.  This approach means we can successfully profile
        # even quite short lived programs.
#        if scalene_profiler.signal_interval < 1:
#            scalene_profiler.signal_interval *= 1.2
#            # Reset the timer for the new interval.
#            signal.setitimer(signal.ITIMER_PROF, scalene_profiler.signal_interval, scalene_profiler.signal_interval)
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
        scalene_profiler.elapsed_time = perf_counter()

    def print_profile(samples, total_samples):
        print("{}\t{:20}\t{}\t{}" .format("Filename", "Function","Line","Percent"))
        if total_samples > 0:
            # Sort the samples in descending order by number of samples.
            samples = { k: v for k, v in sorted(samples.items(), key=lambda item: item[1], reverse=True) }
            for key in samples:
                frac = samples[key] / total_samples
                if frac < 0.01:
                    break
                percent = frac * 100
                dict = scalene_profiler.extract_from_key(key)
                print("{}\t{:20}\t{}\t{:6.2f}%" .format(dict['filename'], dict['func_name'], dict['line_no'], percent))
#                print("{} : {:6.2f}% ({:6.2f}s)" .format(key, percent, frac * scalene_profiler.elapsed_time))
        else:
            print("(Not enough samples collected.)")
        
    @staticmethod
    def exit_handler():
        # Get elapsed time.
        scalene_profiler.elapsed_time = perf_counter() - scalene_profiler.elapsed_time
        
        # Turn off the profiling signals.
        signal.signal(signal.ITIMER_PROF, signal.SIG_IGN)
        signal.signal(signal.SIGVTALRM, signal.SIG_IGN)
        signal.setitimer(signal.ITIMER_PROF, 0)
        # If we've collected any samples, dump them.
        print("CPU usage:")
        scalene_profiler.print_profile(scalene_profiler.cpu_samples, scalene_profiler.total_cpu_samples)
        print("")
        print("Memory usage:")
        scalene_profiler.print_profile(scalene_profiler.mem_samples, scalene_profiler.total_mem_samples)
        
       

if __name__ == "__main__":
    assert len(sys.argv) >= 2, "Usage example: python -m scalene test.py"
    try:
        with open(sys.argv[1], 'rb') as fp:
            code = compile(fp.read(), sys.argv[1], "exec")
            profiler = scalene_profiler()
            profiler.start()
            exec(code)
    except (FileNotFoundError, IOError):
        print("scalene: could not find input file.")
        

