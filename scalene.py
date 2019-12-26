import sys
import atexit
import threading
import signal
import time
import os
# import tracemalloc

# time.perf_counter()

assert sys.version_info[0] == 3 and sys.version_info[1] >= 7, "This tool requires Python version 3.7 or above."

class scalene_profiler:

    samples = {}            # the samples themselves (key = filename+':'+function+':'+lineno)
    mem_samples = {}        # same format but for memory usage
    total_cpu_samples = 0       # how many samples have been collected.
    total_mem_samples = 0   # how many memory usage samples have been collected.
    signal_interval = 0.01  # seconds
    cpu_sampling_triggered = 0  # how many times sampling has been triggered.
    
    def __init__(self):
        # self.stats = scalene_stats()
        # Set up the signal handler to handle periodic timer interrupts (for CPU).
        signal.signal(signal.SIGPROF, self.cpu_signal_handler)
        # Set up the signal handler to handle malloc interrupts (for memory allocations).
        signal.signal(signal.SIGVTALRM, self.malloc_signal_handler)
        signal.setitimer(signal.ITIMER_PROF, self.signal_interval, self.signal_interval)
        #os.environ["PYTHONMALLOC"] = "malloc"
        # This is for Mac; fix for UNIX.
        #os.environ["DYLD_INSERT_LIBRARIES"] = "/Users/emery/git/scalene/libsamplemalloc.dylib"
        pass

    @staticmethod
    def cpu_signal_handler(sig, frame):
        # Every time we get a signal, we increase the count of the
        # number of times sampling has been triggered. It's the job of
        # the profiler to decrement this count.
        scalene_profiler.cpu_sampling_triggered += 1
        # Increase the signal interval geometrically until we hit once
        # per second.  This approach means we can successfully profile
        # even quite short lived programs.
        if scalene_profiler.signal_interval < 1:
            scalene_profiler.signal_interval *= 1.2
        return

    @staticmethod
    def malloc_signal_handler(sig, frame):
        co = frame.f_code
        func_name = co.co_name
        line_no = frame.f_lineno
        filename = co.co_filename
        if not scalene_profiler.should_trace(filename):
            return
        key = filename + '\t' + func_name + '\t' + str(line_no)
        if key in scalene_profiler.mem_samples:
            scalene_profiler.mem_samples[key] += 1
        else:
            scalene_profiler.mem_samples[key] =1
        scalene_profiler.total_mem_samples += 1
        # print("filename = " + filename + ", line_no = " + str(line_no))
        # print("malloc signal!")
        return

    @staticmethod
    def trace_lines(frame, event, arg):
        # Ignore the line if there has not yet been a sample triggered (the common case).
        if scalene_profiler.cpu_sampling_triggered == 0:
            return
        # Only trace lines.
        if event != 'line':
            return
#        (curr, peak) = tracemalloc.get_traced_memory()
#        tracemalloc.stop()
        
        scalene_profiler.cpu_sampling_triggered -= 1
        scalene_profiler.total_cpu_samples += 1
        co = frame.f_code
        func_name = co.co_name
        line_no = frame.f_lineno
        filename = co.co_filename
        key = filename + '\t' + func_name + '\t' + str(line_no)
        # print("line = " + key)
        scalene_profiler.last_line_executed = line_no
#        print("mem so far = curr: " + str(curr) + ", peak: " + str(peak) + " on line " + str(line_no))
        if key in scalene_profiler.samples:
            scalene_profiler.samples[key] += 1
        else:
            scalene_profiler.samples[key] = 1
            
#        tracemalloc.start()
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
    def trace_calls(frame, event, arg):
        # Only trace Python functions.
        if event != 'call':
            return
        co = frame.f_code
        filename = co.co_filename
        if not scalene_profiler.should_trace(filename):
            return
        # Trace lines in the function.
        return scalene_profiler.trace_lines

    @staticmethod
    def start():
        atexit.register(scalene_profiler.exit_handler)
        #        sys.setprofile(scalene_profiler.trace_calls)
        #        threading.setprofile(scalene_profiler.trace_calls)
        sys.settrace(scalene_profiler.trace_calls)
        threading.settrace(scalene_profiler.trace_calls)
        #        tracemalloc.start()


    @staticmethod
    def exit_handler():
        # Turn off malloc tracing.
#        tracemalloc.stop()
        # Turn off the profiling signals.
        signal.signal(signal.ITIMER_PROF, signal.SIG_IGN)
        signal.signal(signal.SIGVTALRM, signal.SIG_IGN)
        signal.setitimer(signal.ITIMER_PROF, 0)
        # Turn off tracing.
        sys.setprofile(None)
        threading.setprofile(None)
        sys.settrace(None)
        threading.settrace(None)
        # If we've collected any samples, dump them.
        if scalene_profiler.total_cpu_samples > 0:
            print("CPU usage:")
            # Sort the samples in descending order by number of samples.
            scalene_profiler.samples = { k: v for k, v in sorted(scalene_profiler.samples.items(), key=lambda item: item[1], reverse=True) }
            for key in scalene_profiler.samples:
                print(key + " : " + str(scalene_profiler.samples[key] * 100 / scalene_profiler.total_cpu_samples) + "%" + " (" + str(scalene_profiler.samples[key]) + " total samples)")
        else:
            print("The program did not run long enough to profile.")
        # If we've collected any samples, dump them.
        print("")
        if scalene_profiler.total_mem_samples > 0:
            print("Memory usage:")
            # Sort the samples in descending order by number of samples.
            scalene_profiler.mem_samples = { k: v for k, v in sorted(scalene_profiler.mem_samples.items(), key=lambda item: item[1], reverse=True) }
            for key in scalene_profiler.mem_samples:
                print(key + " : " + str(scalene_profiler.mem_samples[key] * 100 / scalene_profiler.total_mem_samples) + "%" + " (" + str(scalene_profiler.mem_samples[key]) + " total samples)")
        else:
            print("The program did not allocate enough memory to profile.")
        
       

if __name__ == "__main__":
    assert len(sys.argv) >= 2, "Usage example: python -m scalene test.py"
    profiler = scalene_profiler()
    with open(sys.argv[1], 'rb') as fp:
        code = compile(fp.read(), sys.argv[1], "exec")
    profiler.start()
    
    exec(code)

