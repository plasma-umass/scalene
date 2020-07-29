"""Scalene: a high-performance, high-precision CPU *and* memory profiler for Python.

    https://github.com/emeryberger/scalene

    Scalene uses interrupt-driven sampling for CPU profiling. For memory
    profiling, it uses a similar mechanism but with interrupts generated
    by a "sampling memory allocator" that produces signals everytime the
    heap grows or shrinks by a certain amount. See libscalene.cpp for
    details (sampling logic is in include/sampleheap.hpp).

    by Emery Berger
    https://emeryberger.com

    usage: scalene test/testme.py

"""

import argparse
import atexit
import builtins
import cloudpickle
import dis
import os
import pathlib
import pickle
import platform
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections import defaultdict
from functools import lru_cache
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich import box
from signal import Handlers, Signals
from textwrap import dedent
from types import CodeType, FrameType
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    List,
    NewType,
    Optional,
    Set,
    Tuple,
    Union,
    cast,
)

from scalene.adaptive import Adaptive
from scalene.sparkline import SparkLine


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


def debug_print(message: str) -> None:
    import sys
    import inspect

    callerframerecord = inspect.stack()[1]
    frame = callerframerecord[0]
    info = inspect.getframeinfo(frame)
    print(info.filename, "func=%s" % info.function, "line=%s:" % info.lineno, message)


def parse_args() -> Tuple[argparse.Namespace, List[str]]:
    usage = dedent(
        """Scalene: a high-precision CPU and memory profiler.
        https://github.com/emeryberger/scalene
        % scalene yourprogram.py
        """
    )
    parser = argparse.ArgumentParser(
        prog="scalene",
        description=usage,
        formatter_class=argparse.RawTextHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        "--outfile",
        type=str,
        default=None,
        help="file to hold profiler output (default: stdout)",
    )
    parser.add_argument(
        "--html",
        dest="html",
        action="store_const",
        const=True,
        default=False,
        help="output as HTML (default: text)",
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
    parser.add_argument(
        "--cpu-only",
        dest="cpuonly",
        action="store_const",
        const=True,
        default=False,
        help="only profile CPU time (default: profile CPU, memory, and copying)",
    )
    parser.add_argument(
        "--profile-all",
        dest="profile_all",
        action="store_const",
        const=True,
        default=False,
        help="profile all executed code, not just the target program (default: only the target program)",
    )
    parser.add_argument(
        "--cpu-percent-threshold",
        dest="cpu_percent_threshold",
        type=int,
        default=1,
        help="only report profiles with at least this percent of CPU time (default: 1%%)",
    )
    parser.add_argument(
        "--malloc-threshold",
        dest="malloc_threshold",
        type=int,
        default=100,
        help="only report profiles with at least this many allocations (default: 100)",
    )
    # the PID of the profiling process (for internal use only)
    parser.add_argument("--pid", type=int, default=0, help=argparse.SUPPRESS)
    # Parse out all Scalene arguments and jam the remaining ones into argv.
    # https://stackoverflow.com/questions/35733262/is-there-any-way-to-instruct-argparse-python-2-7-to-remove-found-arguments-fro
    args, left = parser.parse_known_args()
    return args, left


arguments, left = parse_args()

# Load shared objects unless the user specifies "--cpu-only" at the command-line.
# (x86-64 only for now.)

if not arguments.cpuonly and (
    platform.machine() != "x86_64" or struct.calcsize("P") * 8 != 64
):
    arguments.cpuonly = True
    print(
        "scalene warning: currently only 64-bit x86-64 platforms are supported for memory and copy profiling."
    )

if (
    not arguments.cpuonly
    and platform.machine() == "x86_64"
    and struct.calcsize("P") * 8 == 64
):
    # Load the shared object on Linux.
    if sys.platform == "linux":
        if ("LD_PRELOAD" not in os.environ) and ("PYTHONMALLOC" not in os.environ):
            os.environ["LD_PRELOAD"] = os.path.join(
                os.path.dirname(__file__), "libscalene.so"
            )
            os.environ["PYTHONMALLOC"] = "malloc"
            args = sys.argv[1:]
            args = [os.path.basename(sys.executable), "-m", "scalene"] + args
            result = subprocess.run(args)
            sys.exit(result.returncode)

    # Similar logic, but for Mac OS X.
    if sys.platform == "darwin":
        if ("DYLD_INSERT_LIBRARIES" not in os.environ) and (
            "PYTHONMALLOC" not in os.environ
        ):
            env = os.environ
            env["DYLD_INSERT_LIBRARIES"] = os.path.join(
                os.path.dirname(__file__), "libscalene.dylib"
            )
            env["PYTHONMALLOC"] = "malloc"
            args = sys.argv[1:]
            args = [os.path.basename(sys.executable), "-m", "scalene"] + args
            result = subprocess.run(args, env=env, close_fds=True, shell=False)
            sys.exit(result.returncode)

Filename = NewType("Filename", str)
LineNumber = NewType("LineNumber", int)
ByteCodeIndex = NewType("ByteCodeIndex", int)


class Scalene:
    """The Scalene profiler itself."""

    # Debugging flag, for internal use only.
    __debug = False

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

    __original_lock = threading.Lock

    @staticmethod
    def get_original_lock() -> threading.Lock:
        return Scalene.__original_lock()

    # Likely names for the Python interpreter (assuming it's the same version as this one).
    __all_python_names = [
        "python",
        "python" + str(sys.version_info.major),
        "python" + str(sys.version_info.major) + "." + str(sys.version_info.minor),
    ]

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

    # Running count of total CPU samples per file. Used to prune reporting.
    __cpu_samples: Dict[Filename, float] = defaultdict(float)

    # Running count of malloc samples per file. Used to prune reporting.
    __malloc_samples: Dict[Filename, float] = defaultdict(float)

    # Below are indexed by [filename][line_no][bytecode_index]:
    #

    # malloc samples for each location in the program
    __memory_malloc_samples: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, float]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    # mallocs attributable to Python, for each location in the program
    __memory_python_samples: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, float]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

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

    # memory footprint samples (time, footprint), using 'Adaptive' sampling.
    __memory_footprint_samples = Adaptive(27)

    # same, but per line
    __per_line_footprint_samples: Dict[str, Dict[int, Adaptive]] = defaultdict(
        lambda: defaultdict(lambda: Adaptive(9))
    )

    # path for the program being profiled
    __program_path: str = ""
    # temporary directory to hold aliases to Python
    __python_alias_dir: Any = tempfile.TemporaryDirectory(prefix="scalene")
    # and its name
    __python_alias_dir_name: Any = __python_alias_dir.name
    # where we write profile info
    __output_file: str = ""
    # if we output HTML or not
    __html: bool = False
    # if we profile all code or just target code and code in its child directories
    __profile_all: bool = False
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
    __in_signal_handler = threading.Lock()

    # We cache the previous signal handlers so we can play nice with
    # apps that might already have handlers for these signals.
    __original_malloc_signal_handler: Union[
        Callable[[Signals, FrameType], None], int, Handlers, None
    ] = signal.SIG_IGN
    __original_free_signal_handler: Union[
        Callable[[Signals, FrameType], None], int, Handlers, None
    ] = signal.SIG_IGN
    __original_memcpy_signal_handler: Union[
        Callable[[Signals, FrameType], None], int, Handlers, None
    ] = signal.SIG_IGN

    # Program-specific information:
    #   the name of the program being profiled
    __program_being_profiled = Filename("")

    # Is the thread sleeping? (We use this in to properly attribute CPU time.)
    __is_thread_sleeping: Dict[int, bool] = defaultdict(bool)  # False by default

    # Threshold for highlighting lines of code in red.
    __highlight_percentage = 33

    # Default threshold for percent of CPU time to report a file.
    __cpu_percent_threshold = 1

    # Default threshold for number of mallocs to report a file.
    __malloc_threshold = 100

    @staticmethod
    def set_thread_sleeping(tid: int) -> None:
        Scalene.__is_thread_sleeping[tid] = True

    @staticmethod
    def reset_thread_sleeping(tid: int) -> None:
        Scalene.__is_thread_sleeping[tid] = False

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
            Scalene.__is_thread_sleeping[threading.get_ident()] = True
            Scalene.__original_thread_join(self, interval)
            Scalene.__is_thread_sleeping[threading.get_ident()] = False
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
        Scalene.__original_malloc_signal_handler = signal.signal(
            Scalene.__malloc_signal, Scalene.malloc_signal_handler
        )
        Scalene.__original_free_signal_handler = signal.signal(
            Scalene.__free_signal, Scalene.free_signal_handler
        )
        Scalene.__original_memcpy_signal_handler = signal.signal(
            Scalene.__memcpy_signal, Scalene.memcpy_event_signal_handler
        )
        # Turn on the CPU profiling timer to run every mean_signal_interval seconds.
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

    class ReplacementLock(object):
        """Replace lock with a version that periodically yields and updates sleeping status."""

        def __init__(self) -> None:
            self.__lock: threading.Lock = Scalene.get_original_lock()

        def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
            tident = threading.get_ident()
            if blocking == 0:
                blocking = False
            start_time = Scalene.gettime()
            if blocking:
                if timeout < 0:
                    interval = sys.getswitchinterval()
                else:
                    interval = min(timeout, sys.getswitchinterval())
            else:
                interval = -1
            while True:
                Scalene.set_thread_sleeping(tident)
                acquired_lock = self.__lock.acquire(blocking, interval)
                Scalene.reset_thread_sleeping(tident)
                if acquired_lock:
                    return True
                if not blocking:
                    return False
                # If a timeout was specified, check to see if it's expired.
                if timeout != -1:
                    end_time = Scalene.gettime()
                    if end_time - start_time >= timeout:
                        return False

        def release(self) -> None:
            self.__lock.release()

        def locked(self) -> bool:
            return self.__lock.locked()

        def __enter__(self) -> None:
            self.acquire()

        def __exit__(self, type: str, value: str, traceback: Any) -> None:
            self.release()

    def __init__(self, program_being_profiled: Optional[Filename] = None):
        # Hijack join.
        threading.Thread.join = Scalene.thread_join_replacement  # type: ignore
        # Hijack lock.
        threading.Lock = Scalene.ReplacementLock  # type: ignore
        # Build up signal filenames (adding PID to each).
        Scalene.__malloc_signal_filename = Filename(
            Scalene.__malloc_signal_filename + str(os.getpid())
        )
        Scalene.__memcpy_signal_filename = Filename(
            Scalene.__memcpy_signal_filename + str(os.getpid())
        )
        if "cpu_percent_threshold" in arguments:
            Scalene.__cpu_percent_threshold = int(arguments.cpu_percent_threshold)
        if "malloc_threshold" in arguments:
            Scalene.__malloc_threshold = int(arguments.malloc_threshold)

        if arguments.pid:
            # Child process.
            # We need to use the same directory as the parent.
            # The parent always puts this directory as the first entry in the PATH.
            # Extract the alias directory from the path.
            dirname = os.environ["PATH"].split(os.pathsep)[0]
            Scalene.__python_alias_dir = None
            Scalene.__python_alias_dir_name = dirname

        else:
            # Parent process.
            # Create a temporary directory to hold aliases to the Python
            # executable, so scalene can handle multiple proceses; each
            # one is a shell script that redirects to Scalene.
            cmdline = ""
            # Pass along commands from the invoking command line.
            if arguments.cpuonly:
                cmdline += " --cpu-only"
            # Add the --pid field so we can propagate it to the child.
            cmdline += " --pid=" + str(os.getpid())
            payload = """#!/bin/bash
    echo $$
    %s -m scalene %s $@
    """ % (
                sys.executable,
                cmdline,
            )
            # Now create all the files.
            for name in Scalene.__all_python_names:
                fname = os.path.join(Scalene.__python_alias_dir_name, name)
                with open(fname, "w") as file:
                    file.write(payload)
                os.chmod(fname, stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR)
            # Finally, insert this directory into the path.
            sys.path.insert(0, Scalene.__python_alias_dir_name)
            os.environ["PATH"] = (
                Scalene.__python_alias_dir_name + ":" + os.environ["PATH"]
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
        signum: Union[Callable[[Signals, FrameType], None], int, Handlers, None],
        this_frame: FrameType,
    ) -> None:
        if Scalene.__in_signal_handler.acquire(blocking=False):
            Scalene.cpu_signal_handler_helper(signum, this_frame)
            Scalene.__in_signal_handler.release()

    @staticmethod
    def cpu_signal_handler_helper(
        _signum: Union[Callable[[Signals, FrameType], None], int, Handlers, None],
        this_frame: FrameType,
    ) -> None:
        """Handle interrupts for CPU profiling."""
        # Record how long it has been since we received a timer
        # before.  See the logic below.
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

        # First, find out how many frames are not sleeping.  We need
        # to know this number so we can parcel out time appropriately
        # (equally to each running thread).
        total_frames = 0
        for (frame, tident, orig_frame) in new_frames:
            if not Scalene.__is_thread_sleeping[tident]:
                total_frames += 1
        if total_frames == 0:
            return
        normalized_time = total_time / total_frames

        # Now attribute execution time.
        for (frame, tident, orig_frame) in new_frames:
            fname = Filename(frame.f_code.co_filename)
            lineno = LineNumber(frame.f_lineno)
            if frame == new_frames[0][0]:
                # Main thread.
                if not Scalene.__is_thread_sleeping[tident]:
                    Scalene.__cpu_samples_python[fname][lineno] += (
                        python_time / total_frames
                    )
                    Scalene.__cpu_samples_c[fname][lineno] += c_time / total_frames
                    Scalene.__cpu_samples[fname] += (
                        python_time + c_time
                    ) / total_frames
            else:
                # We can't play the same game here of attributing
                # time, because we are in a thread, and threads don't
                # get signals in Python. Instead, we check if the
                # bytecode instruction being executed is a function
                # call.  If so, we attribute all the time to native.
                if not Scalene.__is_thread_sleeping[tident]:
                    # Check if the original caller is stuck inside a call.
                    if Scalene.is_call_function(
                        orig_frame.f_code, ByteCodeIndex(orig_frame.f_lasti)
                    ):
                        # It is. Attribute time to native.
                        Scalene.__cpu_samples_c[fname][lineno] += normalized_time
                    else:
                        # Not in a call function so we attribute the time to Python.
                        Scalene.__cpu_samples_python[fname][lineno] += normalized_time
                    Scalene.__cpu_samples[fname] += normalized_time

        del new_frames

        Scalene.__total_cpu_samples += total_time
        Scalene.__last_signal_time = Scalene.gettime()

    # Returns final frame (up to a line in a file we are profiling), the thread identifier, and the original frame.
    @staticmethod
    def compute_frames_to_record(
        this_frame: FrameType,
    ) -> List[Tuple[FrameType, int, FrameType]]:
        """Collects all stack frames that Scalene actually processes."""
        frames: List[Tuple[FrameType, int]] = [
            (
                cast(FrameType, sys._current_frames().get(cast(int, t.ident), None)),
                cast(int, t.ident),
            )
            for t in threading.enumerate()
            if t != threading.main_thread()
        ]
        # Put the main thread in the front.
        frames.insert(
            0,
            (
                sys._current_frames().get(
                    cast(int, threading.main_thread().ident), None
                ),
                cast(int, threading.main_thread().ident),
            ),
        )
        # Process all the frames to remove ones we aren't going to track.
        new_frames: List[Tuple[FrameType, int, FrameType]] = []
        for (frame, tident) in frames:
            orig_frame = frame
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
                        continue
            if frame:
                new_frames.append((frame, tident, orig_frame))
        return new_frames

    @staticmethod
    def malloc_signal_handler(
        signum: Union[Callable[[Signals, FrameType], None], int, Handlers, None],
        this_frame: FrameType,
    ) -> None:
        """Handle malloc events."""
        if Scalene.__in_signal_handler.acquire(blocking=False):
            Scalene.allocation_signal_handler(signum, this_frame)
            Scalene.__in_signal_handler.release()

    @staticmethod
    def free_signal_handler(
        signum: Union[Callable[[Signals, FrameType], None], int, Handlers, None],
        this_frame: FrameType,
    ) -> None:
        """Handle free events."""
        if Scalene.__in_signal_handler.acquire(blocking=False):
            Scalene.allocation_signal_handler(signum, this_frame)
            Scalene.__in_signal_handler.release()

    @staticmethod
    def allocation_signal_handler(
        signum: Union[Callable[[Signals, FrameType], None], int, Handlers, None],
        this_frame: FrameType,
    ) -> None:
        """Handle interrupts for memory profiling (mallocs and frees)."""
        new_frames = Scalene.compute_frames_to_record(this_frame)

        if not new_frames:
            return

        # Process the input array.
        arr: List[Tuple[int, str, float, float]] = []
        try:
            with open(Scalene.__malloc_signal_filename, "r") as mfile:
                for count_str in mfile:
                    count_str = count_str.rstrip()
                    (
                        action,
                        alloc_time_str,
                        count_str,
                        python_fraction_str,
                    ) = count_str.split(",")
                    arr.append(
                        (
                            int(alloc_time_str),
                            action,
                            float(count_str),
                            float(python_fraction_str),
                        )
                    )
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
            _alloc_time, action, count, python_fraction = item
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

        for (frame, _tident, _orig_frame) in new_frames:
            fname = Filename(frame.f_code.co_filename)
            line_no = LineNumber(frame.f_lineno)
            bytei = ByteCodeIndex(frame.f_lasti)
            # Add the byte index to the set for this line (if it's not there already).
            Scalene.__bytei_map[fname][line_no].add(bytei)
            curr = before
            python_frac = 0.0
            allocs = 0.0
            # Go through the array again and add each updated current footprint.
            for item in arr:
                _alloc_time, action, count, python_fraction = item
                count /= 1024 * 1024
                is_malloc = action == "M"
                if is_malloc:
                    allocs += count
                    curr += count
                    python_frac += python_fraction * count
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
                Scalene.__memory_python_samples[fname][line_no][bytei] += (
                    python_frac / allocs
                ) * (after - before)
                Scalene.__malloc_samples[fname] += 1
                Scalene.__total_memory_malloc_samples += after - before
            else:
                Scalene.__memory_free_samples[fname][line_no][bytei] += before - after
                Scalene.__memory_free_count[fname][line_no][bytei] += 1
                Scalene.__total_memory_free_samples += before - after

    @staticmethod
    def memcpy_event_signal_handler(
        signum: Union[Callable[[Signals, FrameType], None], int, Handlers, None],
        frame: FrameType,
    ) -> None:
        """Handles memcpy events."""
        if not Scalene.__in_signal_handler.acquire(blocking=False):
            return

        new_frames = Scalene.compute_frames_to_record(frame)
        if not new_frames:
            Scalene.__in_signal_handler.release()
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
            _memcpy_time, count = item
            for (the_frame, _tident, _orig_frame) in new_frames:
                fname = Filename(the_frame.f_code.co_filename)
                line_no = LineNumber(the_frame.f_lineno)
                bytei = ByteCodeIndex(the_frame.f_lasti)
                # Add the byte index to the set for this line.
                Scalene.__bytei_map[fname][line_no].add(bytei)
                Scalene.__memcpy_samples[fname][line_no] += count

        Scalene.__in_signal_handler.release()

    @staticmethod
    @lru_cache(None)
    def should_trace(filename: str) -> bool:
        """Return true if the filename is one we should trace."""
        if filename[0] == "<":
            # Not a real file.
            return False
        if "scalene.py" in filename or "scalene/__main__.py" in filename:
            # Don't profile the profiler.
            return False
        if Scalene.__profile_all:
            # Profile everything else.
            return True
        if "site-packages" in filename or "/usr/lib/python" in filename:
            # Don't profile Python internals.
            return False
        # Profile anything in the program's directory or a child directory,
        # but nothing else, unless otherwise specified.
        filename = os.path.abspath(filename)
        return Scalene.__program_path in filename

    @staticmethod
    def start() -> None:
        """Initiate profiling."""
        Scalene.enable_signals()
        Scalene.__start_time = Scalene.gettime()

    @staticmethod
    def stop() -> None:
        """Complete profiling."""
        Scalene.disable_signals()
        Scalene.__elapsed_time += Scalene.gettime() - Scalene.__start_time

    @staticmethod
    def output_profile_line(
        fname: Filename, line_no: LineNumber, line: str, console: Console, tbl: Table,
    ) -> None:
        """Print exactly one line of the profile."""
        current_max = Scalene.__max_footprint
        did_sample_memory: bool = (
            Scalene.__total_memory_free_samples + Scalene.__total_memory_malloc_samples
        ) > 0
        # Strip newline
        line = line.rstrip()
        # Generate syntax highlighted version.
        if Scalene.__html:
            syntax_highlighted = Syntax(
                line, "python", theme="default", line_numbers=False
            )
        else:
            syntax_highlighted = Syntax(line, "python", theme="vim", line_numbers=False)
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
        n_python_malloc_mb = 0.0
        n_free_mb = 0.0
        for index in Scalene.__bytei_map[fname][line_no]:
            mallocs = Scalene.__memory_malloc_samples[fname][line_no][index]
            n_malloc_mb += mallocs
            n_python_malloc_mb += Scalene.__memory_python_samples[fname][line_no][index]
            frees = Scalene.__memory_free_samples[fname][line_no][index]
            n_free_mb += frees

        n_growth_mb = n_malloc_mb - n_free_mb
        if -1 < n_growth_mb < 0:
            # Don't print out "-0".
            n_growth_mb = 0
        n_usage_fraction = (
            0
            if not Scalene.__total_memory_malloc_samples
            else n_malloc_mb / Scalene.__total_memory_malloc_samples
        )
        n_python_fraction = 0 if not n_malloc_mb else n_python_malloc_mb / n_malloc_mb
        # Finally, print results.
        n_cpu_percent_c_str: str = (
            "" if not n_cpu_percent_c else "%6.0f%%" % n_cpu_percent_c
        )
        n_cpu_percent_python_str: str = (
            "" if not n_cpu_percent_python else "%6.0f%%" % n_cpu_percent_python
        )
        n_growth_mb_str: str = (
            "" if (not n_growth_mb and not n_usage_fraction) else "%5.0f" % n_growth_mb
        )
        n_usage_fraction_str: str = (
            "" if not n_usage_fraction else "%3.0f%%" % (100 * n_usage_fraction)
        )
        n_python_fraction_str: str = (
            "" if not n_python_fraction else "%5.0f%%" % (100 * n_python_fraction)
        )
        n_copy_b = Scalene.__memcpy_samples[fname][line_no]
        n_copy_mb_s = n_copy_b / (1024 * 1024 * Scalene.__elapsed_time)
        n_copy_mb_s_str: str = "" if n_copy_mb_s < 0.5 else "%6.0f" % n_copy_mb_s

        if did_sample_memory:
            spark_str: str = ""
            # Scale the sparkline by the usage fraction.
            samples = Scalene.__per_line_footprint_samples[fname][line_no]
            for i in range(0, len(samples.get())):
                samples.get()[i] *= n_usage_fraction
            if samples.get():
                _, _, spark_str = SparkLine().generate(
                    samples.get()[0 : samples.len()], 0, current_max
                )

            # Red highlight
            ncpps: Any = ""
            ncpcs: Any = ""
            nufs: Any = ""
            if (
                n_usage_fraction >= Scalene.__highlight_percentage
                or (n_cpu_percent_c + n_cpu_percent_python)
                >= Scalene.__highlight_percentage
            ):
                ncpps = Text.assemble((n_cpu_percent_python_str, "bold red"))
                ncpcs = Text.assemble((n_cpu_percent_c_str, "bold red"))
                nufs = Text.assemble((spark_str + n_usage_fraction_str, "bold red"))
            else:
                ncpps = n_cpu_percent_python_str
                ncpcs = n_cpu_percent_c_str
                nufs = spark_str + n_usage_fraction_str

            tbl.add_row(
                str(line_no),
                ncpps,  # n_cpu_percent_python_str,
                ncpcs,  # n_cpu_percent_c_str,
                n_python_fraction_str,
                n_growth_mb_str,
                nufs,  # spark_str + n_usage_fraction_str,
                n_copy_mb_s_str,
                syntax_highlighted,
            )

        else:

            # Red highlight
            if (
                n_cpu_percent_c + n_cpu_percent_python
            ) >= Scalene.__highlight_percentage:
                ncpps = Text.assemble((n_cpu_percent_python_str, "bold red"))
                ncpcs = Text.assemble((n_cpu_percent_c_str, "bold red"))
            else:
                ncpps = n_cpu_percent_python_str
                ncpcs = n_cpu_percent_c_str

            tbl.add_row(
                str(line_no),
                ncpps,  # n_cpu_percent_python_str,
                ncpcs,  # n_cpu_percent_c_str,
                syntax_highlighted,
            )

    @staticmethod
    def output_stats(pid: int) -> None:
        payload: List[Any] = []
        payload = [
            Scalene.__max_footprint,
            Scalene.__elapsed_time,
            Scalene.__total_cpu_samples,
            Scalene.__cpu_samples_c,
            Scalene.__cpu_samples_python,
            Scalene.__bytei_map,
            Scalene.__cpu_samples,
            Scalene.__memory_malloc_samples,
            Scalene.__memory_python_samples,
            Scalene.__memory_free_samples,
            Scalene.__memcpy_samples,
            Scalene.__per_line_footprint_samples,
            Scalene.__total_memory_free_samples,
            Scalene.__total_memory_malloc_samples,
        ]
        # To be added: __malloc_samples

        # Create a file in the Python alias directory with the relevant info.
        out_fname = os.path.join(
            Scalene.__python_alias_dir_name,
            "scalene" + str(pid) + "-" + str(os.getpid()),
        )
        with open(out_fname, "wb") as out_file:
            cloudpickle.dump(payload, out_file)

    @staticmethod
    def merge_stats() -> None:
        the_dir = pathlib.Path(Scalene.__python_alias_dir_name)
        for f in list(the_dir.glob("**/scalene*")):
            # Skip empty files.
            if os.path.getsize(f) == 0:
                continue
            with open(f, "rb") as file:
                unpickler = pickle.Unpickler(file)
                value = unpickler.load()
                Scalene.__max_footprint = max(Scalene.__max_footprint, value[0])
                Scalene.__elapsed_time = max(Scalene.__elapsed_time, value[1])
                # Scalene.__total_cpu_samples += value[2]
                del value[:3]
                for dict, index in [
                    (Scalene.__cpu_samples_c, 0),
                    (Scalene.__cpu_samples_python, 1),
                    (Scalene.__memcpy_samples, 7),
                    (Scalene.__per_line_footprint_samples, 8),
                ]:
                    for fname in value[index]:
                        for lineno in value[index][fname]:
                            v = value[index][fname][lineno]
                            dict[fname][lineno] += v  # type: ignore
                for dict, index in [
                    (Scalene.__memory_malloc_samples, 4),
                    (Scalene.__memory_python_samples, 5),
                    (Scalene.__memory_free_samples, 6),
                ]:
                    for fname in value[index]:
                        for lineno in value[index][fname]:
                            for ind in value[index][fname][lineno]:
                                dict[fname][lineno][ind] += value[index][fname][lineno][
                                    ind
                                ]
                for fname in value[2]:
                    for lineno in value[2][fname]:
                        v = value[2][fname][lineno]
                        Scalene.__bytei_map[fname][lineno] |= v
                for fname in value[3]:
                    Scalene.__cpu_samples[fname] += value[3][fname]
                Scalene.__total_memory_free_samples += value[9]
                Scalene.__total_memory_malloc_samples += value[10]

    @staticmethod
    def output_profiles() -> bool:
        """Write the profile out."""
        # Get the children's stats, if any.
        if not arguments.pid:
            Scalene.merge_stats()
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
        title = Text()
        mem_usage_line: Union[Text, str] = ""
        if did_sample_memory:
            samples = Scalene.__memory_footprint_samples
            if len(samples.get()) > 0:
                # Output a sparkline as a summary of memory usage over time.
                _, _, spark_str = SparkLine().generate(
                    samples.get()[0 : samples.len()], 0, current_max
                )
                mem_usage_line = Text.assemble(
                    "Memory usage: ",
                    ((spark_str, "blue")),
                    (" (max: %6.2fMB)\n" % current_max),
                )
                title.append(mem_usage_line)

        null = open("/dev/null", "w")
        console = Console(width=132, record=True, force_terminal=True, file=null)
        # Build a list of files we will actually report on.
        report_files = []
        for fname in sorted(all_instrumented_files):
            fname = Filename(fname)
            try:
                percent_cpu_time = (
                    100 * Scalene.__cpu_samples[fname] / Scalene.__total_cpu_samples
                )
            except ZeroDivisionError:
                percent_cpu_time = 0

            debug_print(Scalene.__cpu_samples[fname])
            # Ignore files responsible for less than some percent of execution time and fewer than a threshold # of mallocs.
            if (
                Scalene.__malloc_samples[fname] < Scalene.__malloc_threshold
                and percent_cpu_time < Scalene.__cpu_percent_threshold
            ):
                continue
            report_files.append(fname)

        # Don't actually output the profile if we are a child process.
        # Instead, write info to disk for the main process to collect.
        if arguments.pid:
            Scalene.output_stats(arguments.pid)
            return True

        for fname in report_files:
            # Print header.
            new_title = mem_usage_line + (
                "%s: %% of CPU time = %6.2f%% out of %6.2fs."
                % (fname, percent_cpu_time, Scalene.__elapsed_time)
            )
            # Only display total memory usage once.
            mem_usage_line = ""

            tbl = Table(
                box=box.MINIMAL_HEAVY_HEAD, title=new_title, collapse_padding=True
            )

            tbl.add_column("Line", justify="right", no_wrap=True)
            tbl.add_column("CPU %\nPython", no_wrap=True)
            tbl.add_column("CPU %\nnative", no_wrap=True)
            if did_sample_memory:
                tbl.add_column("Mem %\nPython", no_wrap=True)
                tbl.add_column("Net\n(MB)", no_wrap=True)
                tbl.add_column("Memory usage\nover time / %", no_wrap=True)
                tbl.add_column("Copy\n(MB/s)", no_wrap=True)
            tbl.add_column("\n" + fname, width=66)

            with open(fname, "r") as source_file:
                for line_no, line in enumerate(source_file, 1):
                    Scalene.output_profile_line(
                        fname, LineNumber(line_no), line, console, tbl
                    )
            console.print(tbl)

        if Scalene.__html:
            # Write HTML file.
            if not Scalene.__output_file:
                Scalene.__output_file = "/dev/stdout"
            md = Markdown(
                "generated by the [scalene](https://github.com/emeryberger/scalene) profiler"
            )
            console.print(md)
            console.save_html(Scalene.__output_file, clear=False)
        else:
            if not Scalene.__output_file:
                # No output file specified: write to stdout.
                sys.stdout.write(console.export_text(styles=True))
            else:
                # Don't output styles to text file.
                console.save_text(Scalene.__output_file, styles=False, clear=False)
        return True

    @staticmethod
    def disable_signals() -> None:
        """Turn off the profiling signals."""
        signal.setitimer(Scalene.__cpu_timer_signal, 0)
        signal.signal(Scalene.__malloc_signal, Scalene.__original_malloc_signal_handler)
        signal.signal(Scalene.__free_signal, Scalene.__original_free_signal_handler)
        signal.signal(Scalene.__memcpy_signal, Scalene.__original_memcpy_signal_handler)

    @staticmethod
    def exit_handler() -> None:
        """When we exit, disable all signals."""
        Scalene.disable_signals()
        # Delete the temporary directory.
        try:
            Scalene.__python_alias_dir.cleanup()
        except BaseException:
            pass

    @staticmethod
    def main() -> None:
        """Invokes the profiler from the command-line."""
        args, left = parse_args()  # We currently do this twice, but who cares.
        sys.argv = left
        Scalene.set_timer_signal(args.wallclock)
        Scalene.__output_profile_interval = args.profile_interval
        Scalene.__next_output_time = (
            Scalene.gettime() + Scalene.__output_profile_interval
        )
        Scalene.__html = args.html
        Scalene.__output_file = args.outfile
        Scalene.__profile_all = args.profile_all
        try:
            with open(sys.argv[0], "rb") as prog_being_profiled:
                # Read in the code and compile it.
                code = compile(prog_being_profiled.read(), sys.argv[0], "exec")
                # Push the program's path.
                program_path = os.path.dirname(os.path.abspath(sys.argv[0]))
                sys.path.insert(0, program_path)
                Scalene.__program_path = program_path
                # Grab local and global variables.
                import __main__

                the_locals = __main__.__dict__
                the_globals = __main__.__dict__
                # Splice in the name of the file being executed instead of the profiler.
                the_globals["__file__"] = os.path.basename(sys.argv[0])
                # Start the profiler.
                fullname = os.path.join(program_path, os.path.basename(sys.argv[0]))
                profiler = Scalene(Filename(fullname))
                try:
                    # We exit with this status (returning error code as appropriate).
                    exit_status = 0
                    profiler.start()
                    # Run the code being profiled.
                    try:
                        exec(code, the_globals, the_locals)
                    except SystemExit as se:
                        # Intercept sys.exit and propagate the error code.
                        exit_status = se.code
                    except BaseException:
                        if Scalene.__debug:
                            print(traceback.format_exc())  # for debugging only
                        pass
                    profiler.stop()
                    # If we've collected any samples, dump them.
                    if profiler.output_profiles():
                        pass
                    else:
                        print(
                            "Scalene: Program did not run for long enough to profile."
                        )
                    sys.exit(exit_status)
                except Exception as ex:
                    template = (
                        "Scalene: An exception of type {0} occurred. Arguments:\n{1!r}"
                    )
                    message = template.format(type(ex).__name__, ex.args)
                    print(message)
                    print(traceback.format_exc())
        except (FileNotFoundError, IOError):
            print("Scalene: could not find input file " + sys.argv[0])
            sys.exit(-1)


if __name__ == "__main__":
    Scalene.main()
