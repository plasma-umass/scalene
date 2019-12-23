import sys
import atexit
import threading
import numpy as np
import signal
import time

# time.perf_counter()

assert sys.version_info[0] == 3 and sys.version_info[1] >= 7, "This tool requires Python version 3.7 or above."

class scalene_stats:
    samples = {}            # the samples themselves (key = filename+':'+function+':'+lineno)
    total_samples = 0       # how many samples have been collected.
    signal_interval = 0.01  # seconds
    sampling_triggered = 0  # how many times sampling has been triggered.

    def __init__(self):
        pass

    
class scalene_profiler:

    def __init__(self):
        self.stats = scalene_stats()
        # Set up the signal handler to handle periodic timer interrupts (used for sampling).
        signal.signal(signal.SIGPROF, self.signal_handler)
        signal.setitimer(signal.ITIMER_PROF, self.stats.signal_interval, self.stats.signal_interval)
        pass
    
    def signal_handler(self, sig, frame):
        # Every time we get a signal, we increase the count of the
        # number of times sampling has been triggered. It's the job of
        # the profiler to decrement this count.
        self.stats.sampling_triggered += 1
        return
    
    def exit_handler(self):
        # Turn off the profiling signal.
        signal.setitimer(signal.ITIMER_PROF, 0)
        # Turn off tracing.
        sys.setprofile(None)
        threading.setprofile(None)
        sys.settrace(None)
        threading.settrace(None)
        # If we've collected any samples, dump them.
        if self.stats.total_samples > 0:
            # Sort the samples in descending order by number of samples.
            self.stats.samples = { k: v for k, v in sorted(self.stats.samples.items(), key=lambda item: item[1], reverse=True) }
            for key in self.stats.samples:
                print(key + " : " + str(self.stats.samples[key] * 100 / self.stats.total_samples) + "%" + " (" + str(self.stats.samples[key]) + " total samples)")
        else:
            print("The program did not run long enough to profile.")

    def trace_lines(self, frame, event, arg):
        # Ignore the line if there has not yet been a sample triggered (the common case).
        if self.stats.sampling_triggered == 0:
            return
        # Only trace lines.
        if event != 'line':
            return
        self.stats.sampling_triggered -= 1
        self.stats.total_samples += 1
        co = frame.f_code
        func_name = co.co_name
        line_no = frame.f_lineno
        filename = co.co_filename
        key = filename + '\t' + func_name + '\t' + str(line_no)
        # print("line = " + key)
        self.last_line_executed = line_no
        if key in self.stats.samples:
            self.stats.samples[key] += 1
        else:
            self.stats.samples[key] = 1
        return

        
    def trace_calls(self, frame, event, arg):
        # Only trace Python functions.
        if event != 'call':
            return
        # Don't trace the profiler itself.
        co = frame.f_code
        filename = co.co_filename
        if 'scalene.py' in filename:
            return
        # Trace lines in the function.
        return self.trace_lines

    def start(self):
        atexit.register(self.exit_handler)
        sys.setprofile(self.trace_calls)
        threading.setprofile(self.trace_calls)
        sys.settrace(self.trace_calls)
        threading.settrace(self.trace_calls)
        
       

if __name__ == "__main__":
    assert len(sys.argv) >= 2, "Usage example: python -m scalene test.py"
    profiler = scalene_profiler()
    with open(sys.argv[1], 'rb') as fp:
        code = compile(fp.read(), sys.argv[1], "exec")
    profiler.start()
    
    exec(code)

