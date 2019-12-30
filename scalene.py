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
import json
import linecache
from collections import defaultdict
from time import perf_counter

assert sys.version_info[0] == 3 and sys.version_info[1] >= 7, "This tool requires Python version 3.7 or above."

class scalene_profiler:

    cpu_samples = defaultdict(lambda: 0) # Samples for each location in the program.
    mem_samples = defaultdict(lambda: 0) # Ibid, but for memory samples.
    total_cpu_samples = 0       # how many CPU samples have been collected.
    total_mem_samples = 0       # how many memory usage samples have been collected.
    signal_interval   = 0.01    # seconds between interrupts for CPU sampling.
    elapsed_time      = 0       # measures total elapsed time of client execution.
    reporting_threshold = 0.01  # stop reporting profiling below this fraction.
    program_being_profiled = "" # program being profiled.
    
    def __init__(self, program_being_profiled):
        scalene_profiler.program_being_profiled = program_being_profiled
        atexit.register(scalene_profiler.exit_handler)
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
        if not scalene_profiler.should_trace(filename):
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
        """Handle interrupts for memory profiling (mallocs)."""
        key = scalene_profiler.make_key(frame)
        if key is None:
            # We aren't profiling memory from this file.
            return
        scalene_profiler.mem_samples[key] += 1
        scalene_profiler.total_mem_samples += 1
        # print("MALLOC {} {}".format(scalene_profiler.mem_samples[key], scalene_profiler.total_mem_samples))
        return

    @staticmethod
    def free_signal_handler(sig, frame):
        """Handle interrupts for memory profiling (frees)."""
        key = scalene_profiler.make_key(frame)
        if key is None:
            # We aren't profiling memory from this file.
            return
        scalene_profiler.mem_samples[key] -= 1
        scalene_profiler.total_mem_samples += 1
        # print("FREE {} {}".format(scalene_profiler.mem_samples[key], scalene_profiler.total_mem_samples))
        return
    
    @staticmethod
    def should_trace(filename):
        """Return true if the filename is one we should trace."""
        # For now, only profile the program being profiled.
        if scalene_profiler.program_being_profiled == filename:
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
        scalene_profiler.elapsed_time = perf_counter()


    @staticmethod
    def dump_code():
        print(json.dumps(scalene_profiler.mem_samples))
        print("{:6s}\t | {:6s}\t |".format("CPU", "Memory"))
        with open(scalene_profiler.program_being_profiled, 'r') as fd:
            contents = fd.readlines()
            line_no = 1
            total_cpu_samples = scalene_profiler.total_cpu_samples
            total_mem_samples = scalene_profiler.total_mem_samples
            for line in contents:
                line = line[:-1] # Strip newline
                key = (scalene_profiler.program_being_profiled, line_no)
                key = json.dumps({'filename' : scalene_profiler.program_being_profiled,
                                  'line_no' : line_no })
                n_cpu_samples = scalene_profiler.cpu_samples[key]
                n_mem_samples = scalene_profiler.mem_samples[key]
                if n_cpu_samples > 1 and n_mem_samples != 0:
                    n_cpu_percent = n_cpu_samples * 100 / total_cpu_samples
                    n_mem_percent = n_mem_samples * 100 / total_mem_samples
                    print("{:6.2f}%\t | {:6.2f}%\t | \t{}".format(n_cpu_percent, n_mem_percent, line))
                elif n_cpu_samples > 1:
                    n_cpu_percent = n_cpu_samples * 100 / total_cpu_samples
                    print("{:6.2f}%\t | {:6s}\t | \t{}".format(n_cpu_percent, "", line))
                elif n_mem_samples != 0:
                    n_mem_percent = n_mem_samples * 100 / total_mem_samples
                    print("{:6s}\t | {:6.2f}%\t | \t{}".format("", n_mem_percent, line))
                else:
                    print("{:6s}\t | {:6s}\t | \t{}".format("", "", line))
                line_no += 1
        
    @staticmethod
    def print_profile(samples, total_samples):
        # print("{}\t{:20}\t{}\t{}" .format("Filename", "Function","Line","Percent"))
        print("{:20s}\t{:>9s}\t{}" .format("Filename", "Line", "Percent"))
        # Sort the samples in descending order by number of samples.
        samples = { k: v for k, v in sorted(samples.items(), key=lambda item: item[1], reverse=True) }
        for key in samples:
            if samples[key] < 0:
                continue
            frac = samples[key] / total_samples
            if frac < scalene_profiler.reporting_threshold:
                break
            percent = frac * 100
            dict = scalene_profiler.extract_from_key(key)
            print("{:20s}\t{:9d}\t{:6.2f}%" .format(dict['filename'], dict['line_no'], percent))
            # print("{}\t{:20}\t{}\t{:6.2f}%" .format(dict['filename'], dict['func_name'], dict['line_no'], percent))
            #                print("{} : {:6.2f}% ({:6.2f}s)" .format(key, percent, frac * scalene_profiler.elapsed_time))
        
    @staticmethod
    def exit_handler():
        # Get elapsed time.
        scalene_profiler.elapsed_time = perf_counter() - scalene_profiler.elapsed_time
        
        # Turn off the profiling signals.
        signal.signal(signal.ITIMER_PROF, signal.SIG_IGN)
        signal.signal(signal.SIGVTALRM, signal.SIG_IGN)
        signal.signal(signal.SIGXCPU, signal.SIG_IGN)
        signal.setitimer(signal.ITIMER_PROF, 0)
        # If we've collected any samples, dump them.
        scalene_profiler.dump_code()
        if False:
            print("CPU usage:")
            if scalene_profiler.total_cpu_samples > 0:
                scalene_profiler.print_profile(scalene_profiler.cpu_samples, scalene_profiler.total_cpu_samples)
            else:
                print("(Program did not run for long enough to collect samples.)")
            print("")
            print("Memory usage:")
            if scalene_profiler.total_mem_samples > 0:
                scalene_profiler.print_profile(scalene_profiler.mem_samples, scalene_profiler.total_mem_samples)
            else:
                print("(Either the program did not allocate enough memory or the malloc replacement library was not specified.)")
            
       

if __name__ == "__main__":
    assert len(sys.argv) >= 2, "Usage example: python -m scalene test.py"
    try:
        with open(sys.argv[1], 'rb') as fp:
            code = compile(fp.read(), sys.argv[1], "exec")
            profiler = scalene_profiler(sys.argv[1])
            profiler.start()
            exec(code)
    except (FileNotFoundError, IOError):
        print("scalene: could not find input file.")
        

