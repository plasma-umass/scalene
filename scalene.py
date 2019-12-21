import sys
import atexit
import threading
import numpy as np
import signal
import time

assert sys.version_info[0] == 3 and sys.version_info[1] >= 7, "This tool requires Python version 3.7 or above."

class scalene_stats:
    line_sampling_rate = 2
    current_clock = 0
    line_samples_remaining = line_sampling_rate
    function_sampling_rate = 1000
    function_samples_remaining = function_sampling_rate
    last_function_sampling_interval = function_samples_remaining
    samples = {}            # the samples themselves (key = filename+':'+function+':'+lineno)
    total_samples = 0       # how many samples have been collected.
    signal_interval = 0.5   # seconds
    sampling_triggered = 0  # how many times sampling has been triggered.
    average_sampling_rate = 1
    count = 0
    triggered_sum = 0

    def __init__(self):
        pass

    
class scalene_profiler:

    def __init__(self):
        self.stats = scalene_stats()
        signal.signal(signal.SIGPROF, self.signal_handler)
        signal.setitimer(signal.ITIMER_PROF, self.stats.signal_interval) # self.stats.signal_interval)
        pass
    
    def signal_handler(self, sig, frame):
        self.stats.sampling_triggered += 1
        # Pick a random number whose mean is the desired signal interval.
        # We make this a normal distribution centered around the mean;
        # we iterate if it is 0 or negative.
        while True:
            next_timer = np.random.normal(self.stats.signal_interval, np.sqrt(self.stats.signal_interval))
            if next_timer > 0:
                break
        # print(str(next_timer))
        signal.setitimer(signal.ITIMER_PROF, next_timer)
    
    def line_next_sample_interval(self):
        z = np.random.geometric(p = 1 / self.stats.line_sampling_rate, size=1)[0]
        return z

    def function_next_sample_interval(self):
        z = np.random.geometric(p = 1 / self.stats.function_sampling_rate, size=1)[0]
        return z

    def exit_handler(self):
        # Turn off the profiling signal.
        signal.setitimer(signal.ITIMER_PROF, 0)
        # Turn off tracing.
        sys.setprofile(None)
        threading.setprofile(None)
        sys.settrace(None)
        if self.stats.count > 0:
            # Sort the samples in descending order by number of samples.
            self.stats.samples = { k: v for k, v in sorted(self.stats.samples.items(), key=lambda item: item[1], reverse=True) }
            for key in self.stats.samples:
                print(key + " : " + str(self.stats.samples[key] * 100 / self.stats.total_samples) + "%" + " (" + str(self.stats.samples[key]) + " total samples)")
            print(str(self.stats.triggered_sum / self.stats.count))
        else:
            print("The program did not run long enough to profile.")

    def trace_lines(self, frame, event, arg):
        if event != 'line':
            return
        self.stats.total_samples += 1
        co = frame.f_code
        func_name = co.co_name
        line_no = frame.f_lineno
        filename = co.co_filename
        key = filename + '\t' + func_name + '\t' + str(line_no)
        if key in self.stats.samples:
            self.stats.samples[key] += 1
        else:
            self.stats.samples[key] = 1

    def trace_calls(self, frame, event, arg):
        if event != 'call':
            return
        if self.stats.function_samples_remaining > 1:
            self.stats.function_samples_remaining -= 1
            return
        self.stats.count += 1
        self.stats.triggered_sum += self.stats.sampling_triggered
        print("samples triggered = " + str(self.stats.sampling_triggered) + ", exp average = " + str(self.stats.average_sampling_rate) + ", real average = " + str(self.stats.triggered_sum / self.stats.count))
        # self.stats.average_sampling_rate = 0.2 * self.stats.average_sampling_rate + 0.8 * self.stats.triggered_sum / self.stats.count
        self.stats.average_sampling_rate = 0.9 * self.stats.average_sampling_rate + 0.1 * self.stats.sampling_triggered

        # Average rate is too high (too many samples per function call) => lower interval
        if self.stats.average_sampling_rate > 1.1:
            self.stats.last_function_sampling_interval *= 0.9
        # Average rate is too low => increase the interval
        elif self.stats.average_sampling_rate < 0.9:
            self.stats.last_function_sampling_interval *= 1.2
        self.stats.sampling_triggered = 0
        self.stats.function_samples_remaining = self.stats.last_function_sampling_interval
        return self.trace_lines
        if False:
            if self.stats.sampling_triggered == 0:
                self.stats.last_function_sampling_interval *= 2
                self.stats.function_samples_remaining = self.stats.last_function_sampling_interval #  np.random.geometric(p = 1 / self.last_function_sampling_interval, size=1)[0]
                return
            if self.stats.sampling_triggered > 0:
                # Goal is to keep function sampling at the same rate as signals.
                alpha = 0.2
                self.stats.last_function_sampling_interval = alpha * self.stats.last_function_sampling_interval + (1 - alpha) * (1 / self.stats.sampling_triggered) * self.stats.last_function_sampling_interval
                self.stats.function_samples_remaining = self.stats.last_function_sampling_interval
                self.stats.sampling_triggered = 0 # -= 1
                return self.trace_lines
        

if __name__ == "__main__":
    assert len(sys.argv) >= 2, "Usage example: python -m scalene test.py"
    profiler = scalene_profiler()
    with open(sys.argv[1], 'rb') as fp:
        code = compile(fp.read(), sys.argv[1], "exec")
    atexit.register(profiler.exit_handler)
#    sys.setprofile(profiler.trace_calls)
#    threading.setprofile(profiler.trace_calls)
    sys.settrace(profiler.trace_calls)
    threading.settrace(profiler.trace_calls)
    
    exec(code)

