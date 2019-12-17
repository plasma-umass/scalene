import sys
import atexit
import threading
import numpy as np
import signal

assert sys.version_info[0] == 3 and sys.version_info[1] >= 7, "This tool requires Python version 3.7 or above."

class amba:

    line_sampling_rate = 2
    current_clock = 0
    line_samples_remaining = line_sampling_rate
    function_sampling_rate = 100
    function_samples_remaining = function_sampling_rate
    samples = {}            # the samples themselves (key = filename+':'+function+':'+lineno)
    total_samples = 0       # how many samples have been collected.
    signal_interval = 0.01   # seconds
    sampling_triggered = 0  # how many times sampling has been triggered.

    def signal_handler(self, sig, frame):
        self.sampling_triggered += 1
        
    def __init__(self):
        signal.signal(signal.SIGPROF, self.signal_handler)
        signal.setitimer(signal.ITIMER_PROF, self.signal_interval, self.signal_interval)
        pass
    
    def line_next_sample_interval(self):
        z = np.random.geometric(p = 1 / self.line_sampling_rate, size=1)[0]
#        print(z)
        return z

    def function_next_sample_interval(self):
        z = np.random.geometric(p = 1 / self.function_sampling_rate, size=1)[0]
#        print(z)
        return z
#        return self.function_sampling_rate # FIXME should be random via geometric distribution

    def exit_handler(self):
        # Turn off the profiling signal.
        signal.setitimer(signal.ITIMER_PROF, 0)
        # Turn off tracing.
        sys.settrace(None)
        # Sort the samples in descending order by number of samples.
        self.samples = { k: v for k, v in sorted(self.samples.items(), key=lambda item: item[1], reverse=True) }
        for key in self.samples:
            print(key + " : " + str(self.samples[key] * 100 / self.total_samples) + "%" + " (" + str(self.samples[key]) + " total samples)")

    def trace_lines(self, frame, event, arg):
        if event != 'line':
            return
        self.line_samples_remaining -= 1
        if self.line_samples_remaining > 0:
            return
        self.total_samples += 1
        self.line_samples_remaining = self.line_next_sample_interval()
        co = frame.f_code
        func_name = co.co_name
        line_no = frame.f_lineno
        filename = co.co_filename
        key = filename + ':' + func_name + ':' + str(line_no)
        if key in self.samples:
            self.samples[key] += 1
        else:
            self.samples[key] = 1
            # print('  %s line %s' % (func_name, line_no))

    def trace_calls(self, frame, event, arg):
        if event != 'call':
            return
        if self.function_samples_remaining > 1:
            self.function_samples_remaining -= 1
            return
        self.function_samples_remaining = self.function_next_sample_interval()
        if self.sampling_triggered > 0:
            self.sampling_triggered -= 1
            return self.trace_lines
        #self.function_samples_remaining = self.function_next_sample_interval()
        #if self.sampling_triggered:
        #    self.sampling_triggered = False
        #
        # return
        #co = frame.f_code
        #func_name = co.co_name
        #if func_name == 'write':  # Ignore write() calls from print statements
        #    return
        #line_no = frame.f_lineno
        #filename = co.co_filename
        # print('Call to %s on line %s of %s' % (func_name, line_no, filename))
#        return self.trace_lines

if __name__ == "__main__":
    assert len(sys.argv) >= 2, "Usage example: python -mamba test.py"
    profiler = amba()
    with open(sys.argv[1], 'rb') as fp:
        code = compile(fp.read(), sys.argv[1], "exec")
    atexit.register(profiler.exit_handler)
    sys.settrace(profiler.trace_calls)
    threading.settrace(profiler.trace_calls)
    
    exec(code)

# import testme
