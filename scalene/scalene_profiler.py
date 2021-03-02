"""Scalene: a scripting-language aware profiler for Python.

    https://github.com/emeryberger/scalene

    See the paper "scalene-paper.pdf" in this repository for technical
    details on an earlier version of Scalene's design; note that a
    number of these details have changed.

    by Emery Berger
    https://emeryberger.com

    usage: scalene test/testme.py
    usage help: scalene --help

"""
import argparse
import atexit
import builtins
import cloudpickle
import dis
import functools
import get_line_atomic
import inspect
import mmap
import multiprocessing
import os
import pathlib
import pickle
import platform
import random
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections import defaultdict, OrderedDict
from functools import lru_cache, wraps
from operator import itemgetter
from rich.console import Console
from rich.markdown import Markdown
from rich.segment import Segment
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich import box
from shutil import rmtree
from signal import Handlers, Signals
from textwrap import dedent
from types import CodeType, FrameType
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    List,
    Optional,
    Tuple,
    Union,
    cast,
)
from multiprocessing.process import BaseProcess

from scalene.leak_analysis import (
    outliers,
    multinomial_pvalue,
    one_sided_binomial_test_lt,
)
from scalene import sparkline
from scalene.syntaxline import SyntaxLine
from scalene.scalene_statistics import *

assert (
    sys.version_info[0] == 3 and sys.version_info[1] >= 6
), "Scalene requires Python version 3.6 or above."


# Scalene currently only supports Unix-like operating systems; in
# particular, Linux, Mac OS X, and WSL 2 (Windows Subsystem for Linux 2 = Ubuntu)
if sys.platform == "win32":
    print(
        "Scalene currently does not support Windows, "
        + "but works on Windows Subsystem for Linux 2, Linux, Mac OS X."
    )
    sys.exit(-1)

# Install our profile decorator.


def scalene_redirect_profile(func: Any) -> Any:
    return Scalene.profile(func)


builtins.profile = scalene_redirect_profile  # type: ignore


class Scalene:
    """The Scalene profiler itself."""

    # Debugging flag, for internal use only.
    __debug: bool = False

    # Whether the current profiler is a child
    __is_child = -1
    # the pid of the primary profiler
    __parent_pid = -1
    # Support for @profile
    # decorated files
    __files_to_profile: Dict[Filename, bool] = defaultdict(bool)
    # decorated functions
    __functions_to_profile: Dict[Filename, Dict[Any, bool]] = defaultdict(
        lambda: {}
    )

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

    # As above; we'll cache the original thread and replace it.
    __original_lock = threading.Lock

    __stats = ScaleneStatistics()

    @staticmethod
    def get_original_lock() -> threading.Lock:
        return Scalene.__original_lock()

    # Likely names for the Python interpreter.
    __all_python_names = [
        os.path.basename(sys.executable),
        os.path.basename(sys.executable) + str(sys.version_info.major),
        os.path.basename(sys.executable)
        + str(sys.version_info.major)
        + "."
        + str(sys.version_info.minor),
    ]

    # mean seconds between interrupts for CPU sampling.
    __mean_cpu_sampling_rate: float = 0.01

    # last num seconds between interrupts for CPU sampling.
    __last_cpu_sampling_rate: float = __mean_cpu_sampling_rate

    # when did we last receive a signal?
    __last_signal_time_virtual: float = 0
    __last_signal_time_wallclock: float = 0

    # do we use wallclock time (capturing system time and blocking) or not?
    __use_wallclock_time: bool = True

    # path for the program being profiled
    __program_path: str = ""
    # temporary directory to hold aliases to Python
    __python_alias_dir: Any = tempfile.mkdtemp(prefix="scalene")
    # and its name
    __python_alias_dir_name: Any = __python_alias_dir
    # where we write profile info
    __output_file: str = ""
    # if we output HTML or not
    __html: bool = False
    # if we profile all code or just target code and code in its child directories
    __profile_all: bool = False
    # what function pathnames must contain to be output during profiling
    __profile_only: str = ""
    # how long between outputting stats during execution
    __output_profile_interval: float = float("inf")
    # when we output the next profile
    __next_output_time: float = float("inf")
    # when we started
    __start_time: float = 0
    # pid for tracking child processes
    __pid: int = 0
    # reduced profile?
    __reduced_profile: bool = False

    # Things that need to be in sync with include/sampleheap.hpp:
    #
    #   file to communicate the number of malloc/free samples (+ PID)
    __malloc_signal_filename = Filename(
        "/tmp/scalene-malloc-signal" + str(os.getpid())
    )
    __malloc_lock_filename = Filename(
        "/tmp/scalene-malloc-lock" + str(os.getpid())
    )
    __malloc_signal_position = 0
    __malloc_lastpos = bytearray(8)
    try:
        __malloc_signal_fd = open(__malloc_signal_filename, "x")
        __malloc_lock_fd = open(__malloc_lock_filename, "x")
    except BaseException as exc:
        pass
    try:
        __malloc_signal_fd = open(__malloc_signal_filename, "r")
        __malloc_lock_fd = open(__malloc_lock_filename, "r+")
        __malloc_signal_mmap = mmap.mmap(
            __malloc_signal_fd.fileno(),
            0,
            mmap.MAP_SHARED,
            mmap.PROT_READ,
        )
        __malloc_lock_mmap = mmap.mmap(
            __malloc_lock_fd.fileno(),
            0,
            mmap.MAP_SHARED,
            mmap.PROT_READ | mmap.PROT_WRITE,
        )
    except BaseException as exc:
        # Ignore if we aren't profiling memory.
        pass

    #   file to communicate the number of memcpy samples (+ PID)
    __memcpy_signal_filename = Filename(
        "/tmp/scalene-memcpy-signal" + str(os.getpid())
    )
    __memcpy_lock_filename = Filename(
        "/tmp/scalene-memcpy-lock" + str(os.getpid())
    )
    __memcpy_signal_fd = None
    __memcpy_lock_fd = None
    try:
        __memcpy_signal_fd = open(__memcpy_signal_filename, "r")
        __memcpy_lock_fd = open(__memcpy_lock_filename, "r+")
        __memcpy_signal_mmap = mmap.mmap(
            __memcpy_signal_fd.fileno(),
            0,
            mmap.MAP_SHARED,
            mmap.PROT_READ,
        )
        __memcpy_lock_mmap = mmap.mmap(
            __memcpy_lock_fd.fileno(),
            0,
            mmap.MAP_SHARED,
            mmap.PROT_READ | mmap.PROT_WRITE,
        )

    except BaseException:
        pass
    __memcpy_signal_position = 0
    __memcpy_lastpos = bytearray(8)
    # The specific signals we use.
    # Malloc and free signals are generated by include/sampleheap.hpp.

    __cpu_signal = signal.SIGVTALRM
    __cpu_timer_signal = signal.ITIMER_REAL
    __malloc_signal = signal.SIGXCPU
    __free_signal = signal.SIGXFSZ
    __memcpy_signal = signal.SIGPROF
    fork_signal = signal.SIGTSTP
    # Whether we are in a signal handler or not (to make things properly re-entrant).
    __in_signal_handler = threading.Lock()

    # Program-specific information:
    #   the name of the program being profiled
    __program_being_profiled = Filename("")

    # Is the thread sleeping? (We use this to properly attribute CPU time.)
    __is_thread_sleeping: Dict[int, bool] = defaultdict(
        bool
    )  # False by default

    # Threshold for highlighting lines of code in red.
    __highlight_percentage = 33

    # Default threshold for percent of CPU time to report a file.
    __cpu_percent_threshold = 1

    # Default threshold for number of mallocs to report a file.
    __malloc_threshold = 100

    @classmethod
    def clear_metrics(cls) -> None:
        """
        Clears the various states so that each forked process
        can start with a clean slate
        """
        cls.__stats.clear()

    @staticmethod
    def build_function_stats(
        stats: ScaleneStatistics, fname: Filename
    ) -> ScaleneStatistics:
        fn_stats = ScaleneStatistics()  # copy.deepcopy(stats)
        fn_stats.elapsed_time = stats.elapsed_time
        fn_stats.total_cpu_samples = stats.total_cpu_samples
        fn_stats.total_memory_malloc_samples = (
            stats.total_memory_malloc_samples
        )
        first_line_no = LineNumber(1)
        for line_no in stats.function_map[fname]:
            fn_name = stats.function_map[fname][line_no]
            if fn_name == "<module>":
                continue
            fn_stats.cpu_samples_c[fn_name][
                first_line_no
            ] += stats.cpu_samples_c[fname][line_no]
            fn_stats.cpu_samples_python[fn_name][
                first_line_no
            ] += stats.cpu_samples_python[fname][line_no]
            fn_stats.per_line_footprint_samples[fn_name][
                first_line_no
            ] += stats.per_line_footprint_samples[fname][line_no]
            for index in stats.bytei_map[fname][line_no]:
                fn_stats.bytei_map[fn_name][first_line_no].add(
                    ByteCodeIndex(0)
                )
                fn_stats.memory_malloc_count[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += stats.memory_malloc_count[fname][line_no][index]
                fn_stats.memory_free_count[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += stats.memory_free_count[fname][line_no][index]
                fn_stats.memory_malloc_samples[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += stats.memory_malloc_samples[fname][line_no][index]
                fn_stats.memory_python_samples[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += stats.memory_python_samples[fname][line_no][index]
                fn_stats.memory_free_samples[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += stats.memory_free_samples[fname][line_no][index]
            fn_stats.memcpy_samples[fn_name][
                first_line_no
            ] += stats.memcpy_samples[fname][line_no]
            fn_stats.leak_score[fn_name][first_line_no] = (
                fn_stats.leak_score[fn_name][first_line_no][0]
                + stats.leak_score[fname][line_no][0],
                fn_stats.leak_score[fn_name][first_line_no][1]
                + stats.leak_score[fname][line_no][1],
            )
        return fn_stats

    # Replacement @profile decorator function.
    # We track which functions - in which files - have been decorated,
    # and only report stats for those.
    @staticmethod
    def profile(func: Any) -> Any:
        # Record the file and function name
        Scalene.__files_to_profile[func.__code__.co_filename] = True
        Scalene.__functions_to_profile[func.__code__.co_filename][func] = True

        @functools.wraps(func)
        def wrapper_profile(*args: Any, **kwargs: Any) -> Any:
            value = func(*args, **kwargs)
            return value

        return wrapper_profile

    @staticmethod
    def shim(func: Callable[[Any], Any]) -> Any:
        """
        Provides a decorator that, when used, calls the wrapped function with the Scalene type

        Wrapped function must be of type (s: Scalene) -> Any

        This decorator allows for marking a function in a separate file as a drop-in replacement for an existing
        library function. The intention is for these functions to replace a function that indefinitely blocks (which
        interferes with Scalene) with a function that awakens periodically to allow for signals to be delivered
        """
        func(Scalene)
        # Returns the function itself to the calling file for the sake
        # of not displaying unusual errors if someone attempts to call
        # it
        @functools.wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)  # type: ignore

        return wrapped

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
    def set_timer_signals() -> None:
        """Set up timer signals for CPU profiling."""
        if Scalene.__use_wallclock_time:
            Scalene.__cpu_timer_signal = signal.ITIMER_REAL
        else:
            Scalene.__cpu_timer_signal = signal.ITIMER_VIRTUAL

        # Now set the appropriate timer signal.
        if Scalene.__cpu_timer_signal == signal.ITIMER_REAL:
            Scalene.__cpu_signal = signal.SIGALRM
        elif Scalene.__cpu_timer_signal == signal.ITIMER_VIRTUAL:
            Scalene.__cpu_signal = signal.SIGVTALRM
        elif Scalene.__cpu_timer_signal == signal.ITIMER_PROF:
            Scalene.__cpu_signal = signal.SIGPROF
            # NOT SUPPORTED
            assert False, "ITIMER_PROF is not currently supported."

    @staticmethod
    def enable_signals() -> None:
        """Set up the signal handlers to handle interrupts for profiling and start the
        timer interrupts."""
        Scalene.set_timer_signals()
        # CPU
        signal.signal(Scalene.__cpu_signal, Scalene.cpu_signal_handler)
        # Set signal handlers for memory allocation and memcpy events.
        signal.signal(Scalene.__malloc_signal, Scalene.malloc_signal_handler)
        signal.signal(Scalene.__free_signal, Scalene.free_signal_handler)
        signal.signal(Scalene.fork_signal, Scalene.fork_signal_handler)
        signal.signal(
            Scalene.__memcpy_signal,
            Scalene.memcpy_event_signal_handler,
        )
        # Set every signal to restart interrupted system calls.
        signal.siginterrupt(Scalene.__cpu_signal, False)
        signal.siginterrupt(Scalene.__malloc_signal, False)
        signal.siginterrupt(Scalene.__free_signal, False)
        signal.siginterrupt(Scalene.__memcpy_signal, False)
        signal.siginterrupt(Scalene.fork_signal, False)
        # Turn on the CPU profiling timer to run every mean_cpu_sampling_rate seconds.
        signal.setitimer(
            Scalene.__cpu_timer_signal,
            Scalene.__mean_cpu_sampling_rate,
            Scalene.__mean_cpu_sampling_rate,
        )
        Scalene.__last_signal_time_virtual = Scalene.get_process_time()

    @staticmethod
    def get_process_time() -> float:
        """Time spent on the CPU."""
        return time.process_time()

    @staticmethod
    def get_wallclock_time() -> float:
        """Wall-clock time."""
        return time.perf_counter()

    def __init__(
        self,
        arguments: argparse.Namespace,
        program_being_profiled: Optional[Filename] = None,
    ):
        import scalene.replacement_pjoin

        # Hijack lock, poll, thread_join, fork, and exit.
        import scalene.replacement_lock
        import scalene.replacement_poll_selector
        import scalene.replacement_thread_join
        import scalene.replacement_fork
        import scalene.replacement_exit

        if "cpu_percent_threshold" in arguments:
            Scalene.__cpu_percent_threshold = int(
                arguments.cpu_percent_threshold
            )
        if "malloc_threshold" in arguments:
            Scalene.__malloc_threshold = int(arguments.malloc_threshold)
        if "cpu_sampling_rate" in arguments:
            Scalene.__mean_cpu_sampling_rate = float(
                arguments.cpu_sampling_rate
            )
        if arguments.use_virtual_time:
            Scalene.__use_wallclock_time = False

        if arguments.pid:
            # Child process.
            # We need to use the same directory as the parent.
            # The parent always puts this directory as the first entry in the PATH.
            # Extract the alias directory from the path.
            dirname = os.environ["PATH"].split(os.pathsep)[0]
            Scalene.__python_alias_dir = None
            Scalene.__python_alias_dir_name = dirname
            Scalene.__pid = arguments.pid

        else:
            # Parent process.
            # Create a temporary directory to hold aliases to the Python
            # executable, so scalene can handle multiple processes; each
            # one is a shell script that redirects to Scalene.
            Scalene.__pid = 0
            cmdline = ""
            preface = ""
            # Pass along commands from the invoking command line.
            cmdline += " --cpu-sampling-rate=" + str(
                arguments.cpu_sampling_rate
            )
            if arguments.use_virtual_time:
                cmdline += " --use-virtual-time"
            if arguments.cpu_only:
                cmdline += " --cpu-only"
            else:
                preface = "PYTHONMALLOC=malloc "
                if sys.platform == "linux":
                    shared_lib = os.path.join(
                        os.path.dirname(__file__), "libscalene.so"
                    )
                    preface += "LD_PRELOAD=" + shared_lib
                else:
                    shared_lib = os.path.join(
                        os.path.dirname(__file__), "libscalene.dylib"
                    )
                    preface += "DYLD_INSERT_LIBRARIES=" + shared_lib
            # Add the --pid field so we can propagate it to the child.
            cmdline += " --pid=" + str(os.getpid())
            payload = """#!/bin/bash
    echo $$
    %s %s -m scalene %s $@
    """ % (
                preface,
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
            # Force the executable (if anyone invokes it later) to point to one of our aliases.
            sys.executable = Scalene.__all_python_names[0]

        # Register the exit handler to run when the program terminates or we quit.
        atexit.register(Scalene.exit_handler)
        # Store relevant names (program, path).
        if program_being_profiled:
            Scalene.__program_being_profiled = Filename(
                os.path.abspath(program_being_profiled)
            )
            Scalene.__program_path = os.path.dirname(
                Scalene.__program_being_profiled
            )

    @staticmethod
    def cpu_signal_handler(
        signum: Union[
            Callable[[Signals, FrameType], None], int, Handlers, None
        ],
        this_frame: FrameType,
    ) -> None:
        """Wrapper for CPU signal handlers that locks access to the signal handler itself."""

        if Scalene.__in_signal_handler.acquire(blocking=False):
            Scalene.cpu_signal_handler_helper(signum, this_frame)
            Scalene.__in_signal_handler.release()

    @staticmethod
    def profile_this_code(fname: Filename, lineno: LineNumber) -> bool:
        """When using @profile, only profile files & lines that have been decorated."""
        if not Scalene.__files_to_profile:
            return True
        if fname not in Scalene.__files_to_profile:
            return False
        # Now check to see if it's the right line range.
        for fn in Scalene.__functions_to_profile[fname]:
            lines, line_start = inspect.getsourcelines(fn)
            if lineno >= line_start and lineno < line_start + len(lines):
                # Yes, it's in range.
                return True
        return False

    @staticmethod
    def cpu_signal_handler_helper(
        _signum: Union[
            Callable[[Signals, FrameType], None], int, Handlers, None
        ],
        this_frame: FrameType,
    ) -> None:
        """Handle interrupts for CPU profiling."""
        # Record how long it has been since we received a timer
        # before.  See the logic below.
        now_virtual = Scalene.get_process_time()
        now_wallclock = Scalene.get_wallclock_time()
        # If it's time to print some profiling info, do so.
        if now_virtual >= Scalene.__next_output_time:
            # Print out the profile. Set the next output time, stop
            # signals, print the profile, and then start signals
            # again.
            Scalene.__next_output_time += Scalene.__output_profile_interval
            Scalene.stop()
            stats = Scalene.__stats
            Scalene.output_profiles(stats)
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
        elapsed_virtual = now_virtual - Scalene.__last_signal_time_virtual
        elapsed_wallclock = (
            now_wallclock - Scalene.__last_signal_time_wallclock
        )
        # CPU utilization is the fraction of time spent on the CPU
        # over the total wallclock time.
        cpu_utilization = elapsed_virtual / elapsed_wallclock
        if cpu_utilization > 1.0:
            # Sometimes, for some reason, virtual time exceeds
            # wallclock time, which makes no sense...
            cpu_utilization = 1.0
        if cpu_utilization < 0.0:
            cpu_utilization = 0.0
        python_time = Scalene.__last_cpu_sampling_rate
        c_time = elapsed_virtual - python_time
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
            Scalene.__stats.function_map[fname][lineno] = Filename(
                frame.f_code.co_name
            )
            if frame == new_frames[0][0]:
                # Main thread.
                if not Scalene.__is_thread_sleeping[tident]:
                    Scalene.__stats.cpu_samples_python[fname][lineno] += (
                        python_time / total_frames
                    )
                    Scalene.__stats.cpu_samples_c[fname][lineno] += (
                        c_time / total_frames
                    )
                    Scalene.__stats.cpu_samples[fname] += (
                        python_time + c_time
                    ) / total_frames
                    Scalene.__stats.cpu_utilization[fname][lineno].push(
                        cpu_utilization
                    )
            else:
                # We can't play the same game here of attributing
                # time, because we are in a thread, and threads don't
                # get signals in Python. Instead, we check if the
                # bytecode instruction being executed is a function
                # call.  If so, we attribute all the time to native.
                if not Scalene.__is_thread_sleeping[tident]:
                    # Check if the original caller is stuck inside a call.
                    if Scalene.is_call_function(
                        orig_frame.f_code,
                        ByteCodeIndex(orig_frame.f_lasti),
                    ):
                        # It is. Attribute time to native.
                        Scalene.__stats.cpu_samples_c[fname][
                            lineno
                        ] += normalized_time
                    else:
                        # Not in a call function so we attribute the time to Python.
                        Scalene.__stats.cpu_samples_python[fname][
                            lineno
                        ] += normalized_time
                    Scalene.__stats.cpu_samples[fname] += normalized_time
                    Scalene.__stats.cpu_utilization[fname][lineno].push(
                        cpu_utilization
                    )

        del new_frames

        Scalene.__stats.total_cpu_samples += total_time
        # Pick a new random interval, distributed around the mean.
        next_interval = 0.0
        while next_interval <= 0.0:
            # Choose a normally distributed random number around the
            # mean for the next interval. By setting the standard
            # deviation to a fraction of the mean, we know by
            # properties of the normal distribution that the
            # likelihood of iterating this loop more than once is
            # low. For a fraction 1/f, the probability is
            # p = 1-(math.erf(f/math.sqrt(2)))/2
            next_interval = random.normalvariate(
                Scalene.__mean_cpu_sampling_rate,
                Scalene.__mean_cpu_sampling_rate / 3.0,
            )
        Scalene.__last_cpu_sampling_rate = next_interval
        Scalene.__last_signal_time_wallclock = Scalene.get_wallclock_time()
        Scalene.__last_signal_time_virtual = Scalene.get_process_time()
        signal.setitimer(
            Scalene.__cpu_timer_signal, next_interval, next_interval
        )

    # Returns final frame (up to a line in a file we are profiling), the thread identifier, and the original frame.
    @staticmethod
    def compute_frames_to_record(
        this_frame: FrameType,
    ) -> List[Tuple[FrameType, int, FrameType]]:
        """Collects all stack frames that Scalene actually processes."""
        if threading._active_limbo_lock.locked():  # type: ignore
            # Avoids deadlock where a Scalene signal occurs
            # in the middle of a critical section of the
            # threading library
            return []
        frames: List[Tuple[FrameType, int]] = [
            (
                cast(
                    FrameType,
                    sys._current_frames().get(cast(int, t.ident), None),
                ),
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
                else:
                    break
            if frame:
                new_frames.append((frame, tident, orig_frame))
        return new_frames

    @staticmethod
    def malloc_signal_handler(
        signum: Union[
            Callable[[Signals, FrameType], None], int, Handlers, None
        ],
        this_frame: FrameType,
    ) -> None:
        """Handle malloc events."""

        if Scalene.__in_signal_handler.acquire(blocking=False):
            Scalene.allocation_signal_handler(signum, this_frame, "malloc")
            Scalene.__in_signal_handler.release()

    @staticmethod
    def free_signal_handler(
        signum: Union[
            Callable[[Signals, FrameType], None], int, Handlers, None
        ],
        this_frame: FrameType,
    ) -> None:
        """Handle free events."""
        if Scalene.__in_signal_handler.acquire(blocking=False):
            Scalene.allocation_signal_handler(signum, this_frame, "free")
            Scalene.__in_signal_handler.release()

    @staticmethod
    def allocation_signal_handler(
        signum: Union[
            Callable[[Signals, FrameType], None], int, Handlers, None
        ],
        this_frame: FrameType,
        event: str,
    ) -> None:
        """Handle interrupts for memory profiling (mallocs and frees)."""
        stats = Scalene.__stats
        new_frames = Scalene.compute_frames_to_record(this_frame)
        if not new_frames:
            return
        curr_pid = os.getpid()
        # Process the input array from where we left off reading last time.
        arr: List[Tuple[int, str, float, float, str]] = []
        buf = bytearray(256)  # Must match SampleFile::MAX_BUFSIZE
        try:
            buf = bytearray(128)

            while True:
                if not get_line_atomic.get_line_atomic(
                    Scalene.__malloc_lock_mmap,
                    Scalene.__malloc_signal_mmap,
                    buf,
                    Scalene.__malloc_lastpos,
                ):
                    break
                count_str = buf.rstrip(b"\x00").split(b"\n")[0].decode("ascii")
                if count_str.strip() == "":
                    break
                (
                    action,
                    alloc_time_str,
                    count_str,
                    python_fraction_str,
                    pid,
                    pointer,
                ) = count_str.split(",")
                if int(curr_pid) == int(pid):
                    arr.append(
                        (
                            int(alloc_time_str),
                            action,
                            float(count_str),
                            float(python_fraction_str),
                            pointer,
                        )
                    )

        except FileNotFoundError:
            pass

        arr.sort()
        # Iterate through the array to compute the new current footprint.
        # and update the global __memory_footprint_samples.
        before = stats.current_footprint
        prevmax = stats.max_footprint
        freed_last_trigger = 0
        for item in arr:
            _alloc_time, action, count, python_fraction, pointer = item
            count /= 1024 * 1024
            is_malloc = action == "M"
            if is_malloc:
                stats.current_footprint += count
                if stats.current_footprint > stats.max_footprint:
                    stats.max_footprint = stats.current_footprint
            else:
                stats.current_footprint -= count
                if action == "f":
                    # Check if pointer actually matches
                    if stats.last_malloc_triggered[2] == pointer:
                        freed_last_trigger += 1
            stats.memory_footprint_samples.add(stats.current_footprint)
        after = stats.current_footprint

        if freed_last_trigger:
            if freed_last_trigger > 1:
                # Ignore the case where we have multiple last triggers in the sample file,
                # since this can lead to false positives.
                pass
            else:
                # We freed the last allocation trigger. Adjust scores.
                this_fn = stats.last_malloc_triggered[0]
                this_ln = stats.last_malloc_triggered[1]
                this_ptr = stats.last_malloc_triggered[2]
                if this_ln != 0:
                    stats.leak_score[this_fn][this_ln] = (
                        LineNumber(stats.leak_score[this_fn][this_ln][0]),
                        stats.leak_score[this_fn][this_ln][1] + 1,
                    )
            stats.last_malloc_triggered = (
                Filename(""),
                LineNumber(0),
                Address("0x0"),
            )

        # Now update the memory footprint for every running frame.
        # This is a pain, since we don't know to whom to attribute memory,
        # so we may overcount.

        for (frame, _tident, _orig_frame) in new_frames:
            fname = Filename(frame.f_code.co_filename)
            lineno = LineNumber(frame.f_lineno)
            stats.function_map[fname][lineno] = Filename(frame.f_code.co_name)
            bytei = ByteCodeIndex(frame.f_lasti)
            # Add the byte index to the set for this line (if it's not there already).
            stats.bytei_map[fname][lineno].add(bytei)
            curr = before
            python_frac = 0.0
            allocs = 0.0
            last_malloc = (Filename(""), LineNumber(0), Address("0x0"))
            malloc_pointer = "0x0"
            # Go through the array again and add each updated current footprint.
            for item in arr:
                _alloc_time, action, count, python_fraction, pointer = item
                count /= 1024 * 1024
                is_malloc = action == "M"
                if is_malloc:
                    allocs += count
                    curr += count
                    python_frac += python_fraction * count
                    malloc_pointer = pointer
                else:
                    curr -= count
                stats.per_line_footprint_samples[fname][lineno].add(curr)
            assert curr == after
            # If we allocated anything and this was a malloc event, then mark this as the last triggering malloc
            if event == "malloc" and allocs > 0:
                last_malloc = (
                    Filename(fname),
                    LineNumber(lineno),
                    Address(malloc_pointer),
                )
            # If there was a net increase in memory, treat it as if it
            # was a malloc; otherwise, treat it as if it was a
            # free. This is for later reporting of net memory gain /
            # loss per line of code.
            if after > before:
                stats.memory_malloc_samples[fname][lineno][bytei] += (
                    after - before
                )
                stats.memory_python_samples[fname][lineno][bytei] += (
                    python_frac / allocs
                ) * (after - before)
                stats.malloc_samples[fname] += 1
                stats.memory_malloc_count[fname][lineno][bytei] += 1
                stats.total_memory_malloc_samples += after - before
            else:
                stats.memory_free_samples[fname][lineno][bytei] += (
                    before - after
                )
                stats.memory_free_count[fname][lineno][bytei] += 1
                stats.total_memory_free_samples += before - after
            stats.allocation_velocity = (
                stats.allocation_velocity[0] + (after - before),
                stats.allocation_velocity[1] + allocs,
            )
            # Update leak score if we just increased the max footprint (starting at a fixed threshold, currently 100MB, FIXME).
            if prevmax < stats.max_footprint and stats.max_footprint > 100:
                stats.last_malloc_triggered = last_malloc
                stats.leak_score[fname][lineno] = (
                    stats.leak_score[fname][lineno][0] + 1,
                    stats.leak_score[fname][lineno][1],
                )

    @staticmethod
    def fork_signal_handler(
        signum: Union[
            Callable[[Signals, FrameType], None], int, Handlers, None
        ],
        frame: FrameType,
    ) -> None:
        """
        Receives a signal sent by a child process (0 return code) after a fork and mutates
        current profiler into a child.
        """
        Scalene.__is_child = True
        Scalene.clear_metrics()
        # Note-- __parent_pid of the topmost process is its own pid
        Scalene.__pid = Scalene.__parent_pid
        signal.signal(Scalene.__malloc_signal, Scalene.malloc_signal_handler)
        signal.signal(Scalene.__free_signal, Scalene.free_signal_handler)
        signal.signal(
            Scalene.__memcpy_signal,
            Scalene.memcpy_event_signal_handler,
        )
        signal.setitimer(
            Scalene.__cpu_timer_signal,
            Scalene.__mean_cpu_sampling_rate,
            Scalene.__mean_cpu_sampling_rate,
        )

    @staticmethod
    def memcpy_event_signal_handler(
        signum: Union[
            Callable[[Signals, FrameType], None], int, Handlers, None
        ],
        frame: FrameType,
    ) -> None:
        """Handles memcpy events."""
        if not Scalene.__in_signal_handler.acquire(blocking=False):
            return
        curr_pid = os.getpid()
        new_frames = Scalene.compute_frames_to_record(frame)
        if not new_frames:
            Scalene.__in_signal_handler.release()
            return
        arr: List[Tuple[int, int]] = []
        # Process the input array.
        try:
            mfile = Scalene.__memcpy_signal_mmap
            if mfile:
                mfile.seek(Scalene.__memcpy_signal_position)
                buf = bytearray(128)
                while True:
                    if not get_line_atomic.get_line_atomic(
                        Scalene.__memcpy_lock_mmap,
                        Scalene.__memcpy_signal_mmap,
                        buf,
                        Scalene.__memcpy_lastpos,
                    ):
                        break
                    count_str = buf.split(b"\n")[0].decode("ascii")

                    (memcpy_time_str, count_str2, pid) = count_str.split(",")
                    if int(curr_pid) == int(pid):
                        arr.append((int(memcpy_time_str), int(count_str2)))
                Scalene.__memcpy_signal_position = mfile.tell() - 1
        except Exception:
            pass
        arr.sort()

        stats = Scalene.__stats
        for item in arr:
            _memcpy_time, count = item
            for (the_frame, _tident, _orig_frame) in new_frames:
                fname = Filename(the_frame.f_code.co_filename)
                line_no = LineNumber(the_frame.f_lineno)
                bytei = ByteCodeIndex(the_frame.f_lasti)
                # Add the byte index to the set for this line.
                stats.bytei_map[fname][line_no].add(bytei)
                stats.memcpy_samples[fname][line_no] += count

        Scalene.__in_signal_handler.release()

    @staticmethod
    @lru_cache(None)
    def should_trace(filename: str) -> bool:
        """Return true if the filename is one we should trace."""
        # If the @profile decorator has been used,
        # we restrict profiling to files containing decorated functions.
        if Scalene.__files_to_profile:
            return filename in Scalene.__files_to_profile
        # Generic handling follows (when no @profile decorator has been used).
        if not filename:
            return False
        if filename[0] == "<":
            # Not a real file.
            return False
        if (
            "scalene/"
            in filename
            # or "scalene/__main__.py" in filename
        ):
            # Don't profile the profiler.
            return False
        if not Scalene.__profile_only in filename:
            return False
        if Scalene.__profile_all:
            # Profile everything else, except for "only" choices.
            if Scalene.__profile_only in filename:
                return True
            else:
                return False
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
        Scalene.__start_time = Scalene.get_wallclock_time()

    @staticmethod
    def stop() -> None:
        """Complete profiling."""
        Scalene.disable_signals()
        stats = Scalene.__stats
        stats.elapsed_time += (
            Scalene.get_wallclock_time() - Scalene.__start_time
        )

    @staticmethod
    def output_profile_line(
        fname: Filename,
        line_no: LineNumber,
        line: SyntaxLine,
        console: Console,
        tbl: Table,
        stats: ScaleneStatistics,
        force_print: bool = False,
        suppress_lineno_print: bool = False,
    ) -> bool:
        """Print at most one line of the profile (true == printed one)."""
        if not force_print and not Scalene.profile_this_code(fname, line_no):
            return False
        current_max = stats.max_footprint
        did_sample_memory: bool = (
            stats.total_memory_free_samples + stats.total_memory_malloc_samples
        ) > 0
        # Prepare output values.
        n_cpu_samples_c = stats.cpu_samples_c[fname][line_no]
        # Correct for negative CPU sample counts. This can happen
        # because of floating point inaccuracies, since we perform
        # subtraction to compute it.
        if n_cpu_samples_c < 0:
            n_cpu_samples_c = 0
        n_cpu_samples_python = stats.cpu_samples_python[fname][line_no]

        # Compute percentages of CPU time.
        if stats.total_cpu_samples != 0:
            n_cpu_percent_c = n_cpu_samples_c * 100 / stats.total_cpu_samples
            n_cpu_percent_python = (
                n_cpu_samples_python * 100 / stats.total_cpu_samples
            )
        else:
            n_cpu_percent_c = 0
            n_cpu_percent_python = 0

        # Now, memory stats.
        # Accumulate each one from every byte index.
        n_malloc_mb = 0.0
        n_python_malloc_mb = 0.0
        n_free_mb = 0.0
        for index in stats.bytei_map[fname][line_no]:
            mallocs = stats.memory_malloc_samples[fname][line_no][index]
            n_malloc_mb += mallocs
            n_python_malloc_mb += stats.memory_python_samples[fname][line_no][
                index
            ]
            frees = stats.memory_free_samples[fname][line_no][index]
            n_free_mb += frees

        n_usage_fraction = (
            0
            if not stats.total_memory_malloc_samples
            else n_malloc_mb / stats.total_memory_malloc_samples
        )
        n_python_fraction = (
            0
            if not n_malloc_mb
            else n_python_malloc_mb
            / stats.total_memory_malloc_samples  # was / n_malloc_mb
        )

        if False:
            # Currently disabled; possibly use in another column?
            # Correct for number of samples
            for bytei in stats.memory_malloc_count[fname][
                line_no
            ]:  # type : ignore
                n_malloc_mb /= stats.memory_malloc_count[fname][line_no][bytei]
                n_python_malloc_mb /= stats.memory_malloc_count[fname][
                    line_no
                ][bytei]
            for bytei in stats.memory_free_count[fname][line_no]:
                n_free_mb /= stats.memory_free_count[fname][line_no][bytei]

        n_growth_mb = n_malloc_mb - n_free_mb
        if -1 < n_growth_mb < 0:
            # Don't print out "-0".
            n_growth_mb = 0

        # Finally, print results.
        n_cpu_percent_c_str: str = (
            "" if n_cpu_percent_c < 1 else "%5.0f%%" % n_cpu_percent_c
        )
        n_cpu_percent_python_str: str = (
            ""
            if n_cpu_percent_python < 1
            else "%5.0f%%" % n_cpu_percent_python
        )
        n_growth_mb_str: str = (
            ""
            if (not n_growth_mb and not n_usage_fraction)
            else "%5.0f" % n_growth_mb
        )
        n_usage_fraction_str: str = (
            ""
            if n_usage_fraction < 0.01
            else "%3.0f%%" % (100 * n_usage_fraction)
        )
        n_python_fraction_str: str = (
            ""
            if n_python_fraction < 0.01
            else "%5.0f%%" % (100 * n_python_fraction)
        )
        n_copy_b = stats.memcpy_samples[fname][line_no]
        n_copy_mb_s = n_copy_b / (1024 * 1024 * stats.elapsed_time)
        n_copy_mb_s_str: str = (
            "" if n_copy_mb_s < 0.5 else "%6.0f" % n_copy_mb_s
        )

        n_cpu_percent = n_cpu_percent_c + n_cpu_percent_python
        # Only report utilization where there is more than 1% CPU total usage,
        # and the standard error of the mean is low (meaning it's an accurate estimate).
        sys_str: str = (
            ""
            if n_cpu_percent < 1
            or stats.cpu_utilization[fname][line_no].size() <= 1
            or stats.cpu_utilization[fname][line_no].sem() > 0.025
            or stats.cpu_utilization[fname][line_no].mean() > 0.99
            else "%3.0f%%"
            % (
                n_cpu_percent
                * (1.0 - (stats.cpu_utilization[fname][line_no].mean()))
            )
        )

        print_line_no = "" if suppress_lineno_print else str(line_no)

        if did_sample_memory:
            spark_str: str = ""
            # Scale the sparkline by the usage fraction.
            samples = stats.per_line_footprint_samples[fname][line_no]
            for i in range(0, len(samples.get())):
                samples.get()[i] *= n_usage_fraction
            if samples.get():
                _, _, spark_str = sparkline.generate(
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
                nufs = Text.assemble(
                    (spark_str + n_usage_fraction_str, "bold red")
                )
            else:
                ncpps = n_cpu_percent_python_str
                ncpcs = n_cpu_percent_c_str
                nufs = spark_str + n_usage_fraction_str

            if not Scalene.__reduced_profile or ncpps + ncpcs + nufs:
                tbl.add_row(
                    print_line_no,
                    ncpps,  # n_cpu_percent_python_str,
                    ncpcs,  # n_cpu_percent_c_str,
                    sys_str,
                    n_python_fraction_str,
                    n_growth_mb_str,
                    nufs,  # spark_str + n_usage_fraction_str,
                    n_copy_mb_s_str,
                    line,
                )
                return True
            else:
                return False

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

            if not Scalene.__reduced_profile or ncpps + ncpcs:
                tbl.add_row(
                    print_line_no,
                    ncpps,  # n_cpu_percent_python_str,
                    ncpcs,  # n_cpu_percent_c_str,
                    sys_str,
                    line,
                )
                return True
            else:
                return False

    @staticmethod
    def output_stats(pid: int) -> None:
        payload: List[Any] = []
        stats = Scalene.__stats
        payload = [
            stats.max_footprint,
            stats.elapsed_time,
            stats.total_cpu_samples,
            stats.cpu_samples_c,
            stats.cpu_samples_python,
            stats.bytei_map,
            stats.cpu_samples,
            stats.memory_malloc_samples,
            stats.memory_python_samples,
            stats.memory_free_samples,
            stats.memcpy_samples,
            stats.per_line_footprint_samples,
            stats.total_memory_free_samples,
            stats.total_memory_malloc_samples,
            stats.memory_footprint_samples,
            stats.function_map
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
        stats = Scalene.__stats
        for f in list(the_dir.glob("**/scalene*")):
            # Skip empty files.
            if os.path.getsize(f) == 0:
                continue
            with open(f, "rb") as file:
                unpickler = pickle.Unpickler(file)
                value = unpickler.load()
                stats.max_footprint = max(stats.max_footprint, value[0])
                stats.elapsed_time = max(stats.elapsed_time, value[1])
                stats.total_cpu_samples += value[2]
                del value[:3]
                for dict, index in [
                    (stats.cpu_samples_c, 0),
                    (stats.cpu_samples_python, 1),
                    (stats.memcpy_samples, 7),
                    (stats.per_line_footprint_samples, 8),
                ]:
                    for fname in value[index]:
                        for lineno in value[index][fname]:
                            v = value[index][fname][lineno]
                            dict[fname][lineno] += v  # type: ignore
                for dict, index in [
                    (stats.memory_malloc_samples, 4),
                    (stats.memory_python_samples, 5),
                    (stats.memory_free_samples, 6),
                ]:
                    for fname in value[index]:
                        for lineno in value[index][fname]:
                            for ind in value[index][fname][lineno]:
                                dict[fname][lineno][ind] += value[index][
                                    fname
                                ][lineno][ind]
                for fname in value[2]:
                    for lineno in value[2][fname]:
                        v = value[2][fname][lineno]
                        stats.bytei_map[fname][lineno] |= v
                for fname in value[3]:
                    stats.cpu_samples[fname] += value[3][fname]
                stats.total_memory_free_samples += value[9]
                stats.total_memory_malloc_samples += value[10]
                stats.memory_footprint_samples += value[11]
                for k, v in value[12].items():
                    if k in stats.function_map:
                        stats.function_map[k].update(v)
                    else:
                        stats.function_map[k] = v
                    pass
            os.remove(f)

    @staticmethod
    def output_profiles(stats: ScaleneStatistics) -> bool:
        """Write the profile out."""
        # Get the children's stats, if any.
        if not Scalene.__pid:
            Scalene.merge_stats()
            try:
                rmtree(Scalene.__python_alias_dir)
            except BaseException:
                pass
        current_max: float = stats.max_footprint
        # If we've collected any samples, dump them.
        if (
            not stats.total_cpu_samples
            and not stats.total_memory_malloc_samples
            and not stats.total_memory_free_samples
        ):
            # Nothing to output.
            return False
        # Collect all instrumented filenames.
        all_instrumented_files: List[Filename] = list(
            set(
                list(stats.cpu_samples_python.keys())
                + list(stats.cpu_samples_c.keys())
                + list(stats.memory_free_samples.keys())
                + list(stats.memory_malloc_samples.keys())
            )
        )
        if not all_instrumented_files:
            # We didn't collect samples in source files.
            return False
        # If I have at least one memory sample, then we are profiling memory.
        did_sample_memory: bool = (
            stats.total_memory_free_samples + stats.total_memory_malloc_samples
        ) > 0
        title = Text()
        mem_usage_line: Union[Text, str] = ""
        growth_rate = 0.0
        if did_sample_memory:
            samples = stats.memory_footprint_samples
            if len(samples.get()) > 0:
                # Output a sparkline as a summary of memory usage over time.
                _, _, spark_str = sparkline.generate(
                    samples.get()[0 : samples.len()], 0, current_max
                )
                # Compute growth rate (slope), between 0 and 1.
                if stats.allocation_velocity[1] > 0:
                    growth_rate = (
                        100.0
                        * stats.allocation_velocity[0]
                        / stats.allocation_velocity[1]
                    )
                # If memory used is > 1GB, use GB as the unit.
                if current_max > 1024:
                    mem_usage_line = Text.assemble(
                        "Memory usage: ",
                        ((spark_str, "blue")),
                        (
                            " (max: %6.2fGB, growth rate: %3.0f%%)\n"
                            % ((current_max / 1024), growth_rate)
                        ),
                    )
                else:
                    # Otherwise, use MB.
                    mem_usage_line = Text.assemble(
                        "Memory usage: ",
                        ((spark_str, "blue")),
                        (
                            " (max: %6.2fMB, growth rate: %3.0f%%)\n"
                            % (current_max, growth_rate)
                        ),
                    )

        null = open("/dev/null", "w")
        # Get column width of the terminal and adjust to fit.
        # Note that Scalene works best with at least 132 columns.
        if Scalene.__html:
            column_width = 132
        else:
            column_width = shutil.get_terminal_size().columns
        console = Console(
            width=column_width,
            record=True,
            force_terminal=True,
            file=null,
        )
        # Build a list of files we will actually report on.
        report_files: List[Filename] = []
        # Sort in descending order of CPU cycles, and then ascending order by filename
        for fname in sorted(
            all_instrumented_files,
            key=lambda f: (-(stats.cpu_samples[f]), f),
        ):
            fname = Filename(fname)
            try:
                percent_cpu_time = (
                    100 * stats.cpu_samples[fname] / stats.total_cpu_samples
                )
            except ZeroDivisionError:
                percent_cpu_time = 0

            # Ignore files responsible for less than some percent of execution time and fewer than a threshold # of mallocs.
            if (
                stats.malloc_samples[fname] < Scalene.__malloc_threshold
                and percent_cpu_time < Scalene.__cpu_percent_threshold
            ):
                continue
            report_files.append(fname)

        # Don't actually output the profile if we are a child process.
        # Instead, write info to disk for the main process to collect.
        if Scalene.__pid:
            Scalene.output_stats(Scalene.__pid)
            return True

        for fname in report_files:
            # Print header.
            percent_cpu_time = (
                100 * stats.cpu_samples[fname] / stats.total_cpu_samples
            )
            new_title = mem_usage_line + (
                "%s: %% of time = %6.2f%% out of %6.2fs."
                % (fname, percent_cpu_time, stats.elapsed_time)
            )
            # Only display total memory usage once.
            mem_usage_line = ""

            tbl = Table(
                box=box.MINIMAL_HEAVY_HEAD,
                title=new_title,
                collapse_padding=True,
                width=column_width - 1,
            )

            tbl.add_column("Line", justify="right", no_wrap=True)
            tbl.add_column("Time %\nPython", no_wrap=True)
            tbl.add_column("Time %\nnative", no_wrap=True)
            tbl.add_column("Sys\n%", no_wrap=True)

            other_columns_width = 0  # Size taken up by all columns BUT code

            if did_sample_memory:
                tbl.add_column("Mem %\nPython", no_wrap=True)
                tbl.add_column("Net\n(MB)", no_wrap=True)
                tbl.add_column("Memory usage\nover time / %", no_wrap=True)
                tbl.add_column("Copy\n(MB/s)", no_wrap=True)
                other_columns_width = 72
                tbl.add_column(
                    "\n" + fname,
                    width=column_width - other_columns_width,
                    no_wrap=True,
                )
            else:
                other_columns_width = 36
                tbl.add_column(
                    "\n" + fname,
                    width=column_width - other_columns_width,
                    no_wrap=True,
                )

            # Print out the the profile for the source, line by line.
            with open(fname, "r") as source_file:
                # We track whether we should put in ellipsis (for reduced profiles)
                # or not.
                did_print = True  # did we print a profile line last time?
                code_lines = source_file.read()
                # Generate syntax highlighted version for the whole file,
                # which we will consume a line at a time.
                # See https://github.com/willmcgugan/rich/discussions/965#discussioncomment-314233
                syntax_highlighted = None
                if Scalene.__html:
                    syntax_highlighted = Syntax(
                        code_lines,
                        "python",
                        theme="default",
                        line_numbers=False,
                        code_width=None,
                    )
                else:
                    syntax_highlighted = Syntax(
                        code_lines,
                        "python",
                        theme="vim",
                        line_numbers=False,
                        code_width=None,
                    )
                capture_console = Console(
                    width=column_width - other_columns_width,
                    force_terminal=True,
                )
                formatted_lines = [
                    SyntaxLine(segments)
                    for segments in capture_console.render_lines(
                        syntax_highlighted
                    )
                ]
                stats = Scalene.__stats
                for line_no, line in enumerate(formatted_lines, start=1):
                    old_did_print = did_print
                    did_print = Scalene.output_profile_line(
                        fname, LineNumber(line_no), line, console, tbl, stats
                    )
                    if old_did_print and not did_print:
                        # We are skipping lines, so add an ellipsis.
                        tbl.add_row("...")
                    old_did_print = did_print

            # Potentially print a function summary.
            fn_stats = Scalene.build_function_stats(stats, fname)
            print_fn_summary = False
            for fn_name in fn_stats.cpu_samples_python:
                if fn_name == fname:
                    continue
                print_fn_summary = True
                break

            if print_fn_summary:
                tbl.add_row(None, end_section=True)
                txt = Text.assemble("function summary", style="bold italic")
                if did_sample_memory:
                    tbl.add_row("", "", "", "", "", "", "", "", txt)
                else:
                    tbl.add_row("", "", "", "", txt)

                for fn_name in fn_stats.cpu_samples_python:
                    if fn_name == fname:
                        continue
                    if Scalene.__html:
                        syntax_highlighted = Syntax(
                            fn_name,
                            "python",
                            theme="default",
                            line_numbers=False,
                            code_width=None,
                        )
                    else:
                        syntax_highlighted = Syntax(
                            fn_name,
                            "python",
                            theme="vim",
                            line_numbers=False,
                            code_width=None,
                        )
                    Scalene.output_profile_line(
                        fn_name,
                        LineNumber(1),
                        syntax_highlighted,  # type: ignore
                        console,
                        tbl,
                        fn_stats,
                        True,
                        True,
                    )  # force print, suppress line numbers

            console.print(tbl)

            # Report top K lines (currently 5) in terms of net memory consumption.
            net_mallocs: Dict[LineNumber, float] = defaultdict(float)
            for line_no in stats.bytei_map[fname]:
                for bytecode_index in stats.bytei_map[fname][line_no]:
                    net_mallocs[line_no] += (
                        stats.memory_malloc_samples[fname][line_no][
                            bytecode_index
                        ]
                        - stats.memory_free_samples[fname][line_no][
                            bytecode_index
                        ]
                    )
            net_mallocs = OrderedDict(
                sorted(net_mallocs.items(), key=itemgetter(1), reverse=True)
            )
            if len(net_mallocs) > 0:
                console.print("Top net memory consumption, by line:")
                number = 1
                for net_malloc_lineno in net_mallocs:
                    if net_mallocs[net_malloc_lineno] <= 1:
                        break
                    if number > 5:
                        break
                    output_str = (
                        "("
                        + str(number)
                        + ") "
                        + ("%5.0f" % (net_malloc_lineno))
                        + ": "
                        + ("%5.0f" % (net_mallocs[net_malloc_lineno]))
                        + " MB"
                    )
                    console.print(output_str)
                    number += 1

            # Only report potential leaks if the allocation velocity (growth rate) is above some threshold
            # FIXME: fixed at 1% for now.
            # We only report potential leaks where the confidence interval is quite tight and includes 1.
            growth_rate_threshold = 0.01
            leak_reporting_threshold = 0.05
            leaks = []
            if growth_rate / 100 > growth_rate_threshold:
                vec = list(stats.leak_score[fname].values())
                keys = list(stats.leak_score[fname].keys())
                for index, item in enumerate(stats.leak_score[fname].values()):
                    # See https://en.wikipedia.org/wiki/Rule_of_succession
                    frees = item[1]
                    allocs = item[0]
                    expected_leak = (frees + 1) / (frees + allocs + 2)
                    if expected_leak <= leak_reporting_threshold:
                        leaks.append(
                            (
                                keys[index],
                                1 - expected_leak,
                                net_mallocs[keys[index]],
                            )
                        )
                if len(leaks) > 0:
                    # Report in descending order by least likelihood
                    for leak in sorted(leaks, key=itemgetter(1), reverse=True):
                        output_str = (
                            "Possible memory leak identified at line "
                            + str(leak[0])
                            + " (estimated likelihood: "
                            + ("%3.0f" % (leak[1] * 100))
                            + "%"
                            + ", velocity: "
                            + ("%3.0f MB/s" % (leak[2] / stats.elapsed_time))
                            + ")"
                        )
                        console.print(output_str)

        if Scalene.__html:
            # Write HTML file.
            md = Markdown(
                "generated by the [scalene](https://github.com/emeryberger/scalene) profiler"
            )
            console.print(md)
            if not Scalene.__output_file:
                Scalene.__output_file = "/dev/stdout"
            console.save_html(Scalene.__output_file, clear=False)
        else:
            if not Scalene.__output_file:
                # No output file specified: write to stdout.
                sys.stdout.write(console.export_text(styles=True))
            else:
                # Don't output styles to text file.
                console.save_text(
                    Scalene.__output_file, styles=False, clear=False
                )
        return True

    @staticmethod
    def disable_signals() -> None:
        """Turn off the profiling signals."""
        try:
            signal.setitimer(Scalene.__cpu_timer_signal, 0)
            signal.signal(Scalene.__malloc_signal, signal.SIG_IGN)
            signal.signal(Scalene.__free_signal, signal.SIG_IGN)
            signal.signal(Scalene.__memcpy_signal, signal.SIG_IGN)
        except BaseException:
            # Retry just in case we get interrupted by one of our own signals.
            Scalene.disable_signals()

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
    def termination_handler(
        signum: Union[
            Callable[[Signals, FrameType], None], int, Handlers, None
        ],
        this_frame: FrameType,
    ) -> None:
        sys.exit(-1)

    @staticmethod
    def debug_print(message: str) -> None:
        """Print a message accompanied by info about the file, line number, and caller."""
        import inspect

        callerframerecord = inspect.stack()[1]
        frame = callerframerecord[0]
        info = inspect.getframeinfo(frame)
        print(
            os.getpid(),
            info.filename,
            "func=%s" % info.function,
            "line=%s:" % info.lineno,
            message,
        )

    @staticmethod
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
            "--reduced-profile",
            dest="reduced_profile",
            action="store_const",
            const=True,
            default=False,
            help="generate a reduced profile, with non-zero lines only (default: False).",
        )
        parser.add_argument(
            "--profile-interval",
            type=float,
            default=float("inf"),
            help="output profiles every so many seconds.",
        )
        parser.add_argument(
            "--cpu-only",
            dest="cpu_only",
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
            "--profile-only",
            dest="profile_only",
            type=str,
            default="",
            help="profile only code in files that contain the given string (default: no restrictions)",
        )
        parser.add_argument(
            "--use-virtual-time",
            dest="use_virtual_time",
            action="store_const",
            const=True,
            default=False,
            help="measure only CPU time, not time spent in I/O or blocking (default: False)",
        )
        parser.add_argument(
            "--cpu-percent-threshold",
            dest="cpu_percent_threshold",
            type=int,
            default=1,
            help="only report profiles with at least this percent of CPU time (default: 1%%)",
        )
        parser.add_argument(
            "--cpu-sampling-rate",
            dest="cpu_sampling_rate",
            type=float,
            default=0.01,
            help="CPU sampling rate (default: every 0.01s)",
        )
        parser.add_argument(
            "--malloc-threshold",
            dest="malloc_threshold",
            type=int,
            default=100,
            help="only report profiles with at least this many allocations (default: 100)",
        )
        # the PID of the profiling process (for internal use only)
        parser.add_argument(
            "--pid", type=int, default=0, help=argparse.SUPPRESS
        )
        # Parse out all Scalene arguments and jam the remaining ones into argv.
        # https://stackoverflow.com/questions/35733262/is-there-any-way-to-instruct-argparse-python-2-7-to-remove-found-arguments-fro
        args, left = parser.parse_known_args()
        # If the user did not enter any commands (just `scalene` or `python3 -m scalene`),
        # print the usage information and bail.
        if len(sys.argv) == 1:
            parser.print_help(sys.stderr)
            sys.exit(-1)
        return args, left

    @staticmethod
    def setup_preload(args: argparse.Namespace) -> None:
        # First, check that we are on a supported platform.
        # (x86-64 and ARM only for now.)
        if not args.cpu_only and (
            (
                platform.machine() != "x86_64"
                and platform.machine() != "arm64"
                and platform.machine() != "aarch64"
            )
            or struct.calcsize("P") * 8 != 64
        ):
            args.cpu_only = True
            print(
                "Scalene warning: currently only 64-bit x86-64 and ARM platforms are supported for memory and copy profiling."
            )

        # Load shared objects (that is, interpose on malloc, memcpy and friends)
        # unless the user specifies "--cpu-only" at the command-line.
        if not args.cpu_only:
            # Load the shared object on Linux.
            if sys.platform == "linux":
                if ("LD_PRELOAD" not in os.environ) and (
                    "PYTHONMALLOC" not in os.environ
                ):
                    os.environ["LD_PRELOAD"] = os.path.join(
                        os.path.dirname(__file__), "libscalene.so"
                    )
                    os.environ["PYTHONMALLOC"] = "malloc"
                    new_args = [
                        os.path.basename(sys.executable),
                        "-m",
                        "scalene",
                    ] + sys.argv[1:]
                    result = subprocess.run(new_args)
                    if result.returncode < 0:
                        print(
                            "Scalene error: received signal",
                            signal.Signals(-result.returncode).name,
                        )

                    sys.exit(result.returncode)

            # Similar logic, but for Mac OS X.
            if sys.platform == "darwin":
                if (
                    (
                        ("DYLD_INSERT_LIBRARIES" not in os.environ)
                        and ("PYTHONMALLOC" not in os.environ)
                    )
                    or "OBJC_DISABLE_INITIALIZE_FORK_SAFETY" not in os.environ
                ):
                    os.environ["DYLD_INSERT_LIBRARIES"] = os.path.join(
                        os.path.dirname(__file__), "libscalene.dylib"
                    )
                    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
                    os.environ["PYTHONMALLOC"] = "malloc"
                    orig_args = args
                    new_args = [
                        os.path.basename(sys.executable),
                        "-m",
                        "scalene",
                    ] + sys.argv[1:]
                    result = subprocess.run(
                        new_args, close_fds=True, shell=False
                    )
                    if result.returncode < 0:
                        print(
                            "Scalene error: received signal",
                            signal.Signals(-result.returncode).name,
                        )
                    sys.exit(result.returncode)

    @staticmethod
    def main() -> None:
        # import scalene.replacement_rlock
        """Invokes the profiler from the command-line."""
        (
            args,
            left,
        ) = Scalene.parse_args()
        Scalene.setup_preload(args)
        sys.argv = left
        multiprocessing.set_start_method("fork")
        try:
            Scalene.__output_profile_interval = args.profile_interval
            Scalene.__next_output_time = (
                Scalene.get_wallclock_time()
                + Scalene.__output_profile_interval
            )
            Scalene.__html = args.html
            Scalene.__output_file = args.outfile
            Scalene.__profile_all = args.profile_all
            Scalene.__profile_only = args.profile_only
            Scalene.__is_child = args.pid != 0
            # the pid of the primary profiler
            Scalene.__parent_pid = (
                args.pid if Scalene.__is_child else os.getpid()
            )
            if args.reduced_profile:
                Scalene.__reduced_profile = True
            else:
                Scalene.__reduced_profile = False
            try:
                with open(sys.argv[0], "rb") as prog_being_profiled:
                    # Read in the code and compile it.
                    try:
                        code = compile(
                            prog_being_profiled.read(),
                            sys.argv[0],
                            "exec",
                        )
                    except SyntaxError:
                        traceback.print_exc()
                        sys.exit(-1)
                    # Push the program's path.
                    program_path = os.path.dirname(
                        os.path.abspath(sys.argv[0])
                    )
                    sys.path.insert(0, program_path)
                    Scalene.__program_path = program_path
                    # Grab local and global variables.
                    import __main__

                    the_locals = __main__.__dict__
                    the_globals = __main__.__dict__
                    # Splice in the name of the file being executed instead of the profiler.
                    the_globals["__file__"] = os.path.basename(sys.argv[0])
                    # Some mysterious module foo to make this work the same with -m as with `scalene`.
                    the_globals["__spec__"] = None
                    # Start the profiler.
                    fullname = os.path.join(
                        program_path, os.path.basename(sys.argv[0])
                    )
                    profiler = Scalene(args, Filename(fullname))
                    try:
                        # We exit with this status (returning error code as appropriate).
                        exit_status = 0
                        # Catch termination so we print a profile before exiting.
                        # (Invokes sys.exit, which is caught below.)
                        signal.signal(
                            signal.SIGTERM,
                            Scalene.termination_handler,
                        )
                        # Catch termination so we print a profile before exiting.
                        profiler.start()
                        # Run the code being profiled.
                        try:
                            exec(code, the_globals, the_locals)
                        except SystemExit as se:
                            # Intercept sys.exit and propagate the error code.
                            exit_status = se.code
                        except BaseException as e:
                            print("Error in program being profiled:\n", e)

                        profiler.stop()
                        # If we've collected any samples, dump them.
                        stats = Scalene.__stats
                        if profiler.output_profiles(stats):
                            pass
                        else:
                            print(
                                "Scalene: Program did not run for long enough to profile."
                            )
                        sys.exit(exit_status)
                    except Exception as ex:
                        template = "Scalene: An exception of type {0} occurred. Arguments:\n{1!r}"
                        message = template.format(type(ex).__name__, ex.args)
                        print(message)
                        print(traceback.format_exc())
            except (FileNotFoundError, IOError):
                print("Scalene: could not find input file " + sys.argv[0])
                sys.exit(-1)
        except SystemExit:
            pass
        except BaseException:
            print("Scalene failed to initialize.\n" + traceback.format_exc())
            sys.exit(-1)


if __name__ == "__main__":
    Scalene.main()
