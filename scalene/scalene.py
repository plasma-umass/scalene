"""Scalene: a high-performance, high-precision CPU *and* memory profiler for Python.

    Scalene uses interrupt-driven sampling for CPU profiling. For memory
    profiling, it uses a similar mechanism but with interrupts generated
    by a "sampling memory allocator" that produces signals everytime the
    heap grows or shrinks by a certain amount. See libscalene.cpp for
    details (sampling logic is in include/sampleheap.hpp).

    by Emery Berger
    https://emeryberger.com

    usage: # for CPU profiling only
            scalene test/testme.py
            # for CPU and memory profiling (Mac OS X)
            DYLD_INSERT_LIBRARIES=$PWD/libscalene.dylib PYTHONMALLOC=malloc scalene test/testme.py
            # for CPU and memory profiling (Linux)
            LD_PRELOAD=$PWD/libscalene.so PYTHONMALLOC=malloc python scalene test/testme.py

"""

import argparse
import atexit

import builtins
import contextlib
import dis
import os
import signal
import sys
import threading
import time
import traceback
from collections import defaultdict
from contextlib import contextmanager
from functools import lru_cache
from signal import Handlers, Signals
from textwrap import dedent
from types import CodeType, FrameType
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    IO,
    Iterator,
    List,
    NewType,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
    cast,
)

from . import adaptive
from . import sparkline

# Logic to ignore @profile decorators.
try:
    builtins.profile  # type: ignore
except AttributeError:

    def profile(func: Any) -> Any:
        """No line profiler; we provide a pass-through version."""
        return func

    builtins.profile = profile  # type: ignore


assert (
    sys.version_info[0] == 3 and sys.version_info[1] >= 5
), "Scalene requires Python version 3.5 or above."


# Scalene currently only supports Unix-like operating systems; in
# particular, Linux, Mac OS X, and WSL 2 (Windows Subsystem for Linux 2 = Ubuntu)
if sys.platform == "win32":
    print(
        "Scalene currently does not support Windows, "
        + "but works on Windows Subsystem for Linux 2, Linux, Mac OS X."
    )
    sys.exit(-1)


Filename = NewType("Filename", str)
LineNumber = NewType("LineNumber", int)
ByteCodeIndex = NewType("ByteCodeIndex", int)


class Scalene:
    """The Scalene profiler itself."""

    # We use these in is_call_function to determine whether a
    # particular bytecode is a function call.  We use this to
    # distinguish between Python and native code execution when
    # running in threads.
    __call_opcodes: FrozenSet[int] = frozenset(
        {
            dis.opmap[op_name]
            for op_name in dis.opmap
            if op_name.startswith("CALL_FUNCTION")
        }
    )

    # Cache the original thread join function, which we replace with our own version.
    __original_thread_join: Callable[
        [threading.Thread, Union[builtins.float, None]], None
    ] = threading.Thread.join

    # Statistics counters:
    #
    #   CPU samples for each location in the program
    #   spent in the interpreter
    __cpu_samples_python: Dict[Filename, Dict[LineNumber, float]] = defaultdict(
        lambda: defaultdict(float)
    )

    #   CPU samples for each location in the program
    #   spent in C / libraries / system calls
    __cpu_samples_c: Dict[Filename, Dict[LineNumber, float]] = defaultdict(
        lambda: defaultdict(float)
    )

    # Below are indexed by [filename][line_no][bytecode_index]:
    #

    # malloc samples for each location in the program
    __memory_malloc_samples: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, float]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    # number of times samples were added for the above
    __memory_malloc_count: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, int]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    # free samples for each location in the program
    __memory_free_samples: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, float]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    # number of times samples were added for the above
    __memory_free_count: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, int]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    # memcpy samples for each location in the program
    __memcpy_samples: Dict[Filename, Dict[LineNumber, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    # how many CPU samples have been collected
    __total_cpu_samples: float = 0.0

    # "   "    malloc "       "    "    "
    __total_memory_malloc_samples: float = 0.0

    # "   "    free   "       "    "    "
    __total_memory_free_samples: float = 0.0

    # the current memory footprint
    __current_footprint: float = 0.0

    # the peak memory footprint
    __max_footprint: float = 0.0

    # mean seconds between interrupts for CPU sampling.
    __mean_signal_interval: float = 0.01

    # last num seconds between interrupts for CPU sampling.
    __last_signal_interval: float = __mean_signal_interval

    # when did we last receive a signal?
    __last_signal_time: float = 0

    # memory footprint samples (time, footprint), using 'adaptive' sampling.
    __memory_footprint_samples = adaptive.adaptive(27)

    # same, but per line
    __per_line_footprint_samples: Dict[str, Dict[int, adaptive.adaptive]] = defaultdict(
        lambda: defaultdict(lambda: adaptive.adaptive(9))
    )

    # original working directory
    __original_path: str = ""
    # path for the program being profiled
    __program_path: str = ""
    # where we write profile info
    __output_file: str = ""
    # how long between outputting stats during execution
    __output_profile_interval: float = float("inf")
    # when we output the next profile
    __next_output_time: float = float("inf")
    # when we started
    __start_time: float = 0
    # total time spent in program being profiled
    __elapsed_time: float = 0

    # maps byte indices to line numbers (collected at runtime)
    # [filename][lineno] -> set(byteindex)
    __bytei_map: Dict[Filename, Dict[LineNumber, Set[ByteCodeIndex]]] = defaultdict(
        lambda: defaultdict(lambda: set())
    )

    # Things that need to be in sync with include/sampleheap.hpp:
    #
    #   file to communicate the number of malloc/free samples (+ PID)
    __malloc_signal_filename = Filename("/tmp/scalene-malloc-signal")
    #   file to communicate the number of memcpy samples (+ PID)
    __memcpy_signal_filename = Filename("/tmp/scalene-memcpy-signal")

    # The specific signals we use.
    # Malloc and free signals are generated by include/sampleheap.hpp.

    __cpu_signal = signal.SIGVTALRM
    __cpu_timer_signal = signal.ITIMER_REAL
    __malloc_signal = signal.SIGXCPU
    __free_signal = signal.SIGXFSZ
    __memcpy_signal = signal.SIGPROF

    # Whether we are in a signal handler or not (to make things properly re-entrant).
    __in_signal_handler = 0

    # We cache the previous signal handlers so we can play nice with
    # apps that might already have handlers for these signals.
    __old_malloc_signal_handler: Union[
        Callable[[Signals, FrameType], None], int, Handlers, None
    ] = signal.SIG_IGN
    __old_free_signal_handler: Union[
        Callable[[Signals, FrameType], None], int, Handlers, None
    ] = signal.SIG_IGN
    __old_memcpy_signal_handler: Union[
        Callable[[Signals, FrameType], None], int, Handlers, None
    ] = signal.SIG_IGN

    # Program-specific information:
    #   the name of the program being profiled
    __program_being_profiled = Filename("")

    @staticmethod
    @lru_cache(maxsize=None)
    def is_call_function(code: CodeType, bytei: ByteCodeIndex) -> bool:
        """Returns true iff the bytecode at the given index is a function call."""
        for ins in dis.get_instructions(code):
            if ins.offset == bytei and ins.opcode in Scalene.__call_opcodes:
                return True
        return False

    @staticmethod
    def thread_join_replacement(
        self: threading.Thread, timeout: Optional[float] = None
    ) -> None:
        """We replace threading.Thread.join with this method which always
periodically yields."""
        start_time = Scalene.gettime()
        interval = sys.getswitchinterval()
        while self.is_alive():
            Scalene.__original_thread_join(self, interval)
            # If a timeout was specified, check to see if it's expired.
            if timeout:
                end_time = Scalene.gettime()
                if end_time - start_time >= timeout:
                    return None
        return None

    @staticmethod
    def set_timer_signal(use_wallclock_time: bool = False) -> None:
        """Set up timer signals for CPU profiling."""
        if use_wallclock_time:
            Scalene.__cpu_timer_signal = signal.ITIMER_REAL
        else:
            Scalene.__cpu_timer_signal = signal.ITIMER_VIRTUAL

        # Now set the appropriate timer signal.
        if Scalene.__cpu_timer_signal == signal.ITIMER_REAL:
            Scalene.__cpu_signal = signal.SIGALRM
        elif Scalene.__cpu_timer_signal == signal.ITIMER_VIRTUAL:
            Scalene.__cpu_signal = signal.SIGVTALRM
        elif Scalene.__cpu_timer_signal == signal.ITIMER_PROF:
            # NOT SUPPORTED
            assert False, "ITIMER_PROF is not currently supported."

    @staticmethod
    def enable_signals() -> None:
        """Set up the signal handlers to handle interrupts for profiling and
start the timer interrupts."""
        # CPU
        signal.signal(Scalene.__cpu_signal, Scalene.cpu_signal_handler)
        # Set signal handlers for memory allocation and memcpy events.
        # Save the previous signal handlers, if any.
        Scalene.__old_malloc_signal_handler = signal.signal(
            Scalene.__malloc_signal, Scalene.malloc_signal_handler
        )
        Scalene.__old_free_signal_handler = signal.signal(
            Scalene.__free_signal, Scalene.free_signal_handler
        )
        Scalene.__old_memcpy_signal_handler = signal.signal(
            Scalene.__memcpy_signal, Scalene.memcpy_event_signal_handler
        )
        # Turn on the CPU profiling timer to run every signal_interval seconds.
        signal.setitimer(
            Scalene.__cpu_timer_signal,
            Scalene.__mean_signal_interval,
            Scalene.__mean_signal_interval,
        )
        Scalene.__last_signal_time = Scalene.gettime()

    @staticmethod
    def gettime() -> float:
        """High-precision timer of time spent running in or on behalf of this
process."""
        if Scalene.__cpu_timer_signal == signal.ITIMER_VIRTUAL:
            # Using virtual time
            return time.process_time()
        else:
            # Using wall clock time
            return time.perf_counter()

    def __init__(self, program_being_profiled: Optional[Filename] = None):
        # Hijack join.
        threading.Thread.join = Scalene.thread_join_replacement  # type: ignore
        # Build up signal filenames (adding PID to each).
        Scalene.__malloc_signal_filename = Filename(
            Scalene.__malloc_signal_filename + str(os.getpid())
        )
        Scalene.__memcpy_signal_filename = Filename(
            Scalene.__memcpy_signal_filename + str(os.getpid())
        )
        # Register the exit handler to run when the program terminates or we quit.
        atexit.register(Scalene.exit_handler)
        # Store relevant names (program, path).
        if program_being_profiled:
            Scalene.__program_being_profiled = Filename(
                os.path.abspath(program_being_profiled)
            )
            Scalene.__program_path = os.path.dirname(Scalene.__program_being_profiled)

    @staticmethod
    def cpu_signal_handler(
        _signum: Union[Callable[[Signals, FrameType], None], int, Handlers, None],
        this_frame: FrameType,
    ) -> None:
        """Handle interrupts for CPU profiling."""
        # Record how long it has been since we received a timer
        # before.  See the logic below.
        if Scalene.__in_signal_handler > 0:
            return
        Scalene.__in_signal_handler += 1
        now = Scalene.gettime()
        # If it's time to print some profiling info, do so.
        if now >= Scalene.__next_output_time:
            # Print out the profile. Set the next output time, stop
            # signals, print the profile, and then start signals
            # again.
            Scalene.__next_output_time += Scalene.__output_profile_interval
            Scalene.stop()
            Scalene.output_profiles()
            Scalene.start()
        # Here we take advantage of an ostensible limitation of Python:
        # it only delivers signals after the interpreter has given up
        # control. This seems to mean that sampling is limited to code
        # running purely in the interpreter, and in fact, that was a limitation
        # of the first version of Scalene, meaning that native code was entirely ignored.
        #
        # (cf. https://docs.python.org/3.9/library/signal.html#execution-of-python-signal-handlers)
        #
        # However: lemons -> lemonade: this "problem" is in fact
        # an effective way to separate out time spent in
        # Python vs. time spent in native code "for free"!  If we get
        # the signal immediately, we must be running in the
        # interpreter. On the other hand, if it was delayed, that means
        # we are running code OUTSIDE the interpreter, e.g.,
        # native code (be it inside of Python or in a library). We
        # account for this time by tracking the elapsed (process) time
        # and compare it to the interval, and add any computed delay
        # (as if it were sampled) to the C counter.
        elapsed = now - Scalene.__last_signal_time
        python_time = Scalene.__last_signal_interval
        c_time = elapsed - python_time
        if c_time < 0:
            c_time = 0
        # Update counters for every running thread.

        new_frames = Scalene.compute_frames_to_record(this_frame)

        # Now update counters (weighted) for every frame we are tracking.
        total_time = python_time + c_time

        for frame in new_frames:
            fname = Filename(frame.f_code.co_filename)
            lineno = LineNumber(frame.f_lineno)
            if frame == this_frame:
                # Main thread.
                Scalene.__cpu_samples_python[fname][lineno] += python_time / len(
                    new_frames
                )
                Scalene.__cpu_samples_c[fname][lineno] += c_time / len(new_frames)
            else:
                # We can't play the same game here of attributing
                # time, because we are in a thread, and threads don't
                # get signals in Python. Instead, we check if the
                # bytecode instruction being executed is a function
                # call.  If so, we attribute all the time to native.
                normalized_time = total_time / len(new_frames)
                if Scalene.is_call_function(frame.f_code, ByteCodeIndex(frame.f_lasti)):
                    # Attribute time to native.
                    Scalene.__cpu_samples_c[fname][lineno] += normalized_time
                else:
                    # Not in a call function so we attribute the time to Python.
                    Scalene.__cpu_samples_python[fname][lineno] += normalized_time

        del new_frames

        Scalene.__total_cpu_samples += total_time

        # disabled randomness for now
        # if False:
        #    # Pick a random interval, uniformly from m/2 to 3m/2 (so the mean is m)
        #    mean = Scalene.__mean_signal_interval
        #    Scalene.__last_signal_interval = random.uniform(mean / 2, mean * 3 / 2)
        #    signal.setitimer(
        #        Scalene.cpu_timer_signal,
        #        Scalene.__last_signal_interval,
        #        Scalene.__last_signal_interval,
        #    )
        Scalene.__last_signal_time = Scalene.gettime()
        Scalene.__in_signal_handler -= 1

    @staticmethod
    def compute_frames_to_record(this_frame: FrameType) -> List[FrameType]:
        """Collects all stack frames that Scalene actually processes."""
        frames: List[Optional[FrameType]] = [
            sys._current_frames().get(cast(int, t.ident), None)
            for t in threading.enumerate()
        ]
        # Process all the frames to remove ones we aren't going to track.
        new_frames: List[FrameType] = []
        for frame in frames:
            if not frame:
                continue
            fname = frame.f_code.co_filename
            # Record samples only for files we care about.
            if not fname:
                # 'eval/compile' gives no f_code.co_filename.  We have
                # to look back into the outer frame in order to check
                # the co_filename.
                back = cast(FrameType, frame.f_back)
                fname = Filename(back.f_code.co_filename)
            while not Scalene.should_trace(fname):
                # Walk the stack backwards until we hit a frame that
                # IS one we should trace (if there is one).  i.e., if
                # it's in the code being profiled, and it is just
                # calling stuff deep in libraries.
                if frame:
                    frame = cast(FrameType, frame.f_back)
                    if frame:
                        fname = frame.f_code.co_filename
            if frame:
                new_frames.append(frame)
        return new_frames

    @staticmethod
    def malloc_signal_handler(
        signum: Union[Callable[[Signals, FrameType], None], int, Handlers, None],
        this_frame: FrameType,
    ) -> None:
        """Handle malloc events."""
        Scalene.allocation_handler(signum, this_frame)

    @staticmethod
    def free_signal_handler(
        signum: Union[Callable[[Signals, FrameType], None], int, Handlers, None],
        this_frame: FrameType,
    ) -> None:
        """Handle free events."""
        Scalene.allocation_handler(signum, this_frame)

    @staticmethod
    def allocation_handler(
        signum: Union[Callable[[Signals, FrameType], None], int, Handlers, None],
        this_frame: FrameType,
    ) -> None:
        if Scalene.__in_signal_handler > 0:
            return
        Scalene.__in_signal_handler += 1

        """Handle interrupts for memory profiling (mallocs and frees)."""
        new_frames = Scalene.compute_frames_to_record(this_frame)

        if not new_frames:
            Scalene.__in_signal_handler -= 1
            return

        # Process the input array.
        arr: List[Tuple[int, str, float]] = []
        try:
            with open(Scalene.__malloc_signal_filename, "r") as mfile:
                for count_str in mfile:
                    # for _, count_str in enumerate(mfile, 1):
                    count_str = count_str.rstrip()
                    (action, alloc_time_str, count_str) = count_str.split(",")
                    arr.append((int(alloc_time_str), action, float(count_str)))
        except FileNotFoundError:
            pass
        try:
            os.remove(Scalene.__malloc_signal_filename)
        except FileNotFoundError:
            pass
        
        arr.sort()

        # Iterate through the array to compute the new current footprint.
        # and update the global __memory_footprint_samples.
        before = Scalene.__current_footprint
        for item in arr:
            alloc_time, action, count = item
            # print(fname,line_no,action, alloc_time, count)
            count /= 1024 * 1024
            is_malloc = action == "M"
            if is_malloc:
                Scalene.__current_footprint += count
                if Scalene.__current_footprint > Scalene.__max_footprint:
                    Scalene.__max_footprint = Scalene.__current_footprint
            else:
                Scalene.__current_footprint -= count
            Scalene.__memory_footprint_samples.add(Scalene.__current_footprint)
        after = Scalene.__current_footprint

        # Now update the memory footprint for every running frame.
        # This is a pain, since we don't know to whom to attribute memory,
        # so we may overcount.

        for frame in new_frames:
            fname = Filename(frame.f_code.co_filename)
            line_no = LineNumber(frame.f_lineno)
            bytei = ByteCodeIndex(frame.f_lasti)
            # Add the byte index to the set for this line (if it's not there already).
            Scalene.__bytei_map[fname][line_no].add(bytei)
            curr = before
            # Go through the array again and add each updated current footprint.
            for item in arr:
                alloc_time, action, count = item
                count /= 1024 * 1024
                is_malloc = action == "M"
                if is_malloc:
                    curr += count
                else:
                    curr -= count
                Scalene.__per_line_footprint_samples[fname][line_no].add(curr)
            assert curr == after
            # If there was a net increase in memory, treat it as if it
            # was a malloc; otherwise, treat it as if it was a
            # free. This is for later reporting of net memory gain /
            # loss per line of code.
            if after > before:
                Scalene.__memory_malloc_samples[fname][line_no][bytei] += after - before
                Scalene.__memory_malloc_count[fname][line_no][bytei] += 1
                Scalene.__total_memory_malloc_samples += after - before
            else:
                Scalene.__memory_free_samples[fname][line_no][bytei] += before - after
                Scalene.__memory_free_count[fname][line_no][bytei] += 1
                Scalene.__total_memory_free_samples += before - after
        Scalene.__in_signal_handler -= 1

    @staticmethod
    def memcpy_event_signal_handler(
        signum: Union[Callable[[Signals, FrameType], None], int, Handlers, None],
        frame: FrameType,
    ) -> None:
        """Handles memcpy events."""
        if Scalene.__in_signal_handler > 0:
            return
        Scalene.__in_signal_handler += 1
        new_frames = Scalene.compute_frames_to_record(frame)
        if not new_frames:
            Scalene.__in_signal_handler -= 1
            return

        # Process the input array.
        arr: List[Tuple[int, int]] = []
        try:
            with open(Scalene.__memcpy_signal_filename, "r") as mfile:
                for count_str in mfile:
                    count_str = count_str.rstrip()
                    (memcpy_time_str, count_str2) = count_str.split(",")
                    arr.append((int(memcpy_time_str), int(count_str2)))
        except FileNotFoundError:
            pass
        try:
            os.remove(Scalene.__memcpy_signal_filename)
        except FileNotFoundError:
            pass
        arr.sort()

        for item in arr:
            memcpy_time, count = item
            for the_frame in new_frames:
                fname = Filename(the_frame.f_code.co_filename)
                line_no = LineNumber(the_frame.f_lineno)
                bytei = ByteCodeIndex(the_frame.f_lasti)
                # Add the byte index to the set for this line.
                Scalene.__bytei_map[fname][line_no].add(bytei)
                Scalene.__memcpy_samples[fname][line_no] += count

        Scalene.__in_signal_handler -= 1

    @staticmethod
    @lru_cache(None)
    def should_trace(filename: str) -> bool:
        """Return true if the filename is one we should trace."""
        # Profile anything in the program's directory or a child directory,
        # but nothing else.
        if filename[0] == "<":
            return False
        if "site-packages" in filename or "/usr/lib/python" in filename:
            # Don't profile Python internals.
            return False
        if "scalene.py" in filename or "adaptive.py" in filename:
            # Don't profile the profiler.
            return False
        filename = os.path.abspath(filename)
        return Scalene.__program_path in filename

    @staticmethod
    def start() -> None:
        """Initiate profiling."""
        os.chdir(Scalene.__program_path)
        Scalene.enable_signals()
        Scalene.__start_time = Scalene.gettime()

    @staticmethod
    def stop() -> None:
        """Complete profiling."""
        Scalene.disable_signals()
        Scalene.__elapsed_time += Scalene.gettime() - Scalene.__start_time
        os.chdir(Scalene.__original_path)

    # from https://stackoverflow.com/questions/9836370/fallback-to-stdout-if-no-file-name-provided
    @staticmethod
    @contextmanager
    def file_or_stdout(file_name: Optional[str]) -> Iterator[IO[str]]:
        """Returns a file handle for writing; if no argument is passed, returns stdout."""
        if file_name is None:
            yield sys.stdout
        else:
            with open(file_name, "w") as out_file:
                yield out_file

    @staticmethod
    def generate_sparkline(
        arr: List[float], minimum: float = -1, maximum: float = -1
    ) -> Tuple[float, float, str]:
        """Produces a sparkline, as in ▁▁▁▁▁▂▃▂▄▅▄▆█▆█▆"""
        iterations = len(arr)
        all_zeros = all(i == 0 for i in arr)
        if all_zeros:
            return 0, 0, ""
        # Prevent negative memory output due to sampling error.
        samples = [i if i > 0 else 0 for i in arr]
        minval, maxval, sp_line = sparkline.sparkline(
            samples[0:iterations], minimum, maximum
        )
        return minval, maxval, sp_line

    @staticmethod
    def output_profile_line(
        fname: Filename, line_no: LineNumber, line: str, out: IO[str]
    ) -> None:
        """Print exactly one line of the profile to out."""
        current_max = Scalene.__max_footprint
        did_sample_memory: bool = (
            Scalene.__total_memory_free_samples + Scalene.__total_memory_malloc_samples
        ) > 0
        line = line.rstrip()  # Strip newline
        # Prepare output values.
        n_cpu_samples_c = Scalene.__cpu_samples_c[fname][line_no]
        # Correct for negative CPU sample counts. This can happen
        # because of floating point inaccuracies, since we perform
        # subtraction to compute it.
        if n_cpu_samples_c < 0:
            n_cpu_samples_c = 0
        n_cpu_samples_python = Scalene.__cpu_samples_python[fname][line_no]

        # Compute percentages of CPU time.
        if Scalene.__total_cpu_samples != 0:
            n_cpu_percent_c = n_cpu_samples_c * 100 / Scalene.__total_cpu_samples
            n_cpu_percent_python = (
                n_cpu_samples_python * 100 / Scalene.__total_cpu_samples
            )
        else:
            n_cpu_percent_c = 0
            n_cpu_percent_python = 0

        # Now, memory stats.
        # Accumulate each one from every byte index.
        n_malloc_mb = 0.0
        n_free_mb = 0.0
        n_avg_malloc_mb = 0.0
        n_avg_free_mb = 0.0
        n_malloc_count = 0
        n_free_count = 0
        for index in Scalene.__bytei_map[fname][line_no]:
            # print(fname,line_no,index)
            mallocs = Scalene.__memory_malloc_samples[fname][line_no][index]
            n_malloc_mb += mallocs
            n_malloc_count += Scalene.__memory_malloc_count[fname][line_no][index]
            frees = Scalene.__memory_free_samples[fname][line_no][index]
            n_free_mb += frees
            n_free_count += Scalene.__memory_free_count[fname][line_no][index]

            if n_malloc_count > 0:
                n_avg_malloc_mb += mallocs / n_malloc_count
            if n_free_count > 0:
                n_avg_free_mb += frees / n_free_count

        n_growth_mb = n_malloc_mb - n_free_mb
        if -1 < n_growth_mb < 0:
            # Don't print out "-0".
            n_growth_mb = 0
        n_usage_fraction = (
            0
            if not Scalene.__total_memory_malloc_samples
            else n_malloc_mb / Scalene.__total_memory_malloc_samples
        )

        # Finally, print results.
        n_cpu_percent_c_str: str = (
            "" if not n_cpu_percent_c else "%6.2f%%" % n_cpu_percent_c
        )
        n_cpu_percent_python_str: str = (
            "" if not n_cpu_percent_python else "%6.2f%%" % n_cpu_percent_python
        )
        n_growth_mb_str: str = (
            "" if (not n_growth_mb and not n_usage_fraction) else "%5.0f" % n_growth_mb
        )
        n_usage_fraction_str: str = (
            "" if not n_usage_fraction else "%3.0f%%" % (100 * n_usage_fraction)
        )
        n_copy_b = Scalene.__memcpy_samples[fname][line_no]
        n_copy_mb_s = n_copy_b / (1024 * 1024 * Scalene.__elapsed_time)
        n_copy_mb_s_str: str = "" if n_copy_mb_s < 0.1 else "%6.0f" % n_copy_mb_s

        if did_sample_memory:
            spark_str: str = ""
            # Scale the sparkline by the usage fraction.
            samples = Scalene.__per_line_footprint_samples[fname][line_no]
            for i in range(0, len(samples.get())):
                samples.get()[i] *= n_usage_fraction
            if samples.get():
                _, _, spark_str = Scalene.generate_sparkline(
                    samples.get()[0 : samples.len()], 0, current_max
                )
            print(
                "%6d |%9s |%9s | %5s | %-9s %-4s |%-6s | %s"
                % (
                    line_no,
                    n_cpu_percent_python_str,
                    n_cpu_percent_c_str,
                    n_growth_mb_str,
                    spark_str,
                    n_usage_fraction_str,
                    n_copy_mb_s_str,
                    line,
                ),
                file=out,
            )
        else:
            print(
                "%6d |%9s |%9s | %s"
                % (line_no, n_cpu_percent_python_str, n_cpu_percent_c_str, line),
                file=out,
            )

    @staticmethod
    def output_profiles() -> bool:
        """Write the profile out (currently to stdout)."""
        current_max: float = Scalene.__max_footprint
        # If we've collected any samples, dump them.
        if (
            not Scalene.__total_cpu_samples
            and not Scalene.__total_memory_malloc_samples
            and not Scalene.__total_memory_free_samples
        ):
            # Nothing to output.
            return False
        # Collect all instrumented filenames.
        all_instrumented_files: List[str] = list(
            set(
                list(Scalene.__cpu_samples_python.keys())
                + list(Scalene.__cpu_samples_c.keys())
                + list(Scalene.__memory_free_samples.keys())
                + list(Scalene.__memory_malloc_samples.keys())
            )
        )
        if not all_instrumented_files:
            # We didn't collect samples in source files.
            return False
        # If I have at least one memory sample, then we are profiling memory.
        did_sample_memory: bool = (
            Scalene.__total_memory_free_samples + Scalene.__total_memory_malloc_samples
        ) > 0
        with Scalene.file_or_stdout(Scalene.__output_file) as out:
            if did_sample_memory:
                samples = Scalene.__memory_footprint_samples
                if len(samples.get()) > 0:
                    # Output a sparkline as a summary of memory usage over time.
                    _, _, spark_str = Scalene.generate_sparkline(
                        samples.get()[0 : samples.len()], 0, current_max
                    )
                    print(
                        "Memory usage: " + spark_str + " (max: %6.2fMB)" % current_max,
                        file=out,
                    )

            for fname in sorted(all_instrumented_files):

                fname = Filename(fname)
                this_cpu_samples = sum(Scalene.__cpu_samples_c[fname].values()) + sum(
                    Scalene.__cpu_samples_python[fname].values()
                )

                try:
                    percent_cpu_time = (
                        100 * this_cpu_samples / Scalene.__total_cpu_samples
                    )
                except ZeroDivisionError:
                    percent_cpu_time = 0

                # Ignore files responsible for less than 1% of execution time,
                # as long as we aren't profiling memory consumption.
                if not did_sample_memory and percent_cpu_time < 1:
                    continue

                # Print header.
                print(
                    "%s: %% of CPU time = %6.2f%% out of %6.2fs."
                    % (fname, percent_cpu_time, Scalene.__elapsed_time),
                    file=out,
                )

                print(
                    "       |%9s |%9s | %s %s %s"
                    % (
                        "CPU %",
                        "CPU %",
                        " Net  |" if did_sample_memory else "",
                        "Memory usage   |" if did_sample_memory else "",
                        "Copy  |" if did_sample_memory else "",
                    ),
                    file=out,
                )
                print(
                    "  Line |%9s |%9s | %s %s %s [%s]"
                    % (
                        "(Python)",
                        "(native)",
                        " (MB) |" if did_sample_memory else "",
                        "over time /  % |" if did_sample_memory else "",
                        "(MB/s)|" if did_sample_memory else "",
                        fname,
                    ),
                    file=out,
                )
                print("-" * 80, file=out)

                with open(fname, "r") as source_file:
                    for line_no, line in enumerate(source_file, 1):
                        Scalene.output_profile_line(
                            fname, LineNumber(line_no), line, out
                        )
                    print("", file=out)
        return True

    @staticmethod
    def disable_signals() -> None:
        """Turn off the profiling signals."""
        signal.setitimer(Scalene.__cpu_timer_signal, 0)
        signal.signal(Scalene.__malloc_signal, Scalene.__old_malloc_signal_handler)
        signal.signal(Scalene.__free_signal, Scalene.__old_free_signal_handler)
        signal.signal(Scalene.__memcpy_signal, Scalene.__old_memcpy_signal_handler)

    @staticmethod
    def exit_handler() -> None:
        """When we exit, disable all signals."""
        Scalene.disable_signals()

    @contextlib.contextmanager
    def scalene_profiler(_):  # type: ignore  ### TODO add memory stuff
        """A profiler function, work in progress."""
        # In principle, this would let people use Scalene as follows:
        # with scalene_profiler:
        #   ...
        profiler = Scalene(None)
        profiler.start()
        yield
        profiler.stop()
        profiler.output_profiles()  # though this needs to be constrained

    @staticmethod
    def main() -> None:
        """Invokes the profiler from the command-line."""
        usage = dedent(
            """Scalene: a high-precision CPU and memory profiler.
            https://github.com/emeryberger/Scalene

                for CPU profiling only:
            % python -m scalene yourprogram.py
                for CPU and memory profiling (Mac OS X):
            % DYLD_INSERT_LIBRARIES=$PWD/libscalene.dylib PYTHONMALLOC=malloc python -m scalene yourprogram.py
                for CPU and memory profiling (Linux):
            % LD_PRELOAD=$PWD/libscalene.so PYTHONMALLOC=malloc python -m scalene yourprogram.py
            """
        )
        parser = argparse.ArgumentParser(
            prog="scalene",
            description=usage,
            formatter_class=argparse.RawTextHelpFormatter,
        )
        parser.add_argument("prog", type=str, help="program to be profiled")
        parser.add_argument(
            "-o",
            "--outfile",
            type=str,
            default=None,
            help="file to hold profiler output (default: stdout)",
        )
        parser.add_argument(
            "--profile-interval",
            type=float,
            default=float("inf"),
            help="output profiles every so many seconds.",
        )
        parser.add_argument(
            "--wallclock",
            dest="wallclock",
            action="store_const",
            const=True,
            default=False,
            help="use wall clock time (default: virtual time)",
        )
        # Parse out all Scalene arguments and jam the remaining ones into argv.
        # https://stackoverflow.com/questions/35733262/is-there-any-way-to-instruct-argparse-python-2-7-to-remove-found-arguments-fro
        args, left = parser.parse_known_args()
        sys.argv = sys.argv[:1] + left
        Scalene.set_timer_signal(args.wallclock)
        Scalene.__output_profile_interval = args.profile_interval
        Scalene.__next_output_time = (
            Scalene.gettime() + Scalene.__output_profile_interval
        )
        try:
            with open(args.prog, "rb") as prog_being_profiled:
                Scalene.__original_path = os.getcwd()
                # Read in the code and compile it.
                code = compile(prog_being_profiled.read(), args.prog, "exec")
                # Push the program's path.
                program_path = os.path.dirname(os.path.abspath(args.prog))
                sys.path.insert(0, program_path)
                Scalene.__program_path = program_path
                # Grab local and global variables.
                import __main__

                the_locals = __main__.__dict__
                the_globals = __main__.__dict__
                # Splice in the name of the file being executed instead of the profiler.
                the_globals["__file__"] = os.path.basename(args.prog)
                # Start the profiler.
                Scalene.__output_file = args.outfile
                fullname = os.path.join(program_path, os.path.basename(args.prog))
                profiler = Scalene(Filename(fullname))
                try:
                    profiler.start()
                    # Run the code being profiled.
                    try:
                        exec(code, the_globals, the_locals)
                    except BaseException:  # as be
                        # Intercept sys.exit.
                        # print(traceback.format_exc())
                        pass
                    profiler.stop()
                    # If we've collected any samples, dump them.
                    if profiler.output_profiles():
                        pass
                    else:
                        print(
                            "Scalene: Program did not run for long enough to profile."
                        )
                except Exception as ex:
                    template = (
                        "Scalene: An exception of type {0} occurred. Arguments:\n{1!r}"
                    )
                    message = template.format(type(ex).__name__, ex.args)
                    print(message)
                    print(traceback.format_exc())
        except (FileNotFoundError, IOError):
            print("Scalene: could not find input file.")


if __name__ == "__main__":
    Scalene.main()
