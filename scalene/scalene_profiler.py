"""Scalene: a scripting-language aware profiler for Python.

    https://github.com/plasma-umass/scalene

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
import dis
import functools
import get_line_atomic
import inspect
import math
import mmap
import multiprocessing
import os
import platform
import random
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import GPUtil

from collections import defaultdict
from functools import lru_cache, wraps
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

from scalene.scalene_arguments import ScaleneArguments
from scalene.scalene_statistics import *
from scalene.scalene_output import ScaleneOutput
from scalene.scalene_signals import ScaleneSignals


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

    __args = ScaleneArguments()
    __stats = ScaleneStatistics()
    __output = ScaleneOutput()

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

    # last num seconds between interrupts for CPU sampling.
    __last_cpu_sampling_rate: float = 0

    # when did we last receive a signal?
    __last_signal_time_virtual: float = 0
    __last_signal_time_wallclock: float = 0

    # path for the program being profiled
    __program_path: str = ""
    # temporary directory to hold aliases to Python
    __python_alias_dir: Any
    # and its name
    __python_alias_dir_name: Filename

    ## Profile output parameters

    # when we output the next profile
    __next_output_time: float = float("inf")
    # when we started
    __start_time: float = 0
    # pid for tracking child processes
    __pid: int = 0

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
        os.unlink(__malloc_signal_fd.name)
        __malloc_lock_fd = open(__malloc_lock_filename, "x")
        os.unlink(__malloc_lock_fd.name)
        __malloc_signal_fd.close()
        __malloc_lock_fd.close()
    except BaseException as exc:
        pass
    try:
        __malloc_signal_fd = open(__malloc_signal_filename, "r")
        os.unlink(__malloc_signal_fd.name)
        __malloc_lock_fd = open(__malloc_lock_filename, "r+")
        os.unlink(__malloc_lock_fd.name)
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
    try:
        __memcpy_signal_fd = open(__memcpy_signal_filename, "r")
        os.unlink(__memcpy_signal_fd.name)
        __memcpy_lock_fd = open(__memcpy_lock_filename, "r+")
        os.unlink(__memcpy_lock_fd.name)
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
    
    # Whether we are in a signal handler or not (to make things properly re-entrant).
    __in_signal_handler = threading.Lock()

    # Program-specific information:
    #   the name of the program being profiled
    __program_being_profiled = Filename("")

    # Is the thread sleeping? (We use this to properly attribute CPU time.)
    __is_thread_sleeping: Dict[int, bool] = defaultdict(
        bool
    )  # False by default

    @classmethod
    def clear_metrics(cls) -> None:
        """
        Clears the various states so that each forked process
        can start with a clean slate
        """
        cls.__stats.clear()

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
        if Scalene.__args.use_virtual_time:
            ScaleneSignals.cpu_timer_signal = signal.ITIMER_VIRTUAL
        else:
            ScaleneSignals.cpu_timer_signal = signal.ITIMER_REAL

        # Now set the appropriate timer signal.
        if ScaleneSignals.cpu_timer_signal == signal.ITIMER_REAL:
            ScaleneSignals.cpu_signal = signal.SIGALRM
        elif ScaleneSignals.cpu_timer_signal == signal.ITIMER_VIRTUAL:
            ScaleneSignals.cpu_signal = signal.SIGVTALRM
        elif ScaleneSignals.cpu_timer_signal == signal.ITIMER_PROF:
            ScaleneSignals.cpu_signal = signal.SIGPROF
            # NOT SUPPORTED
            assert False, "ITIMER_PROF is not currently supported."

    @staticmethod
    def enable_signals() -> None:
        """Set up the signal handlers to handle interrupts for profiling and start the
        timer interrupts."""
        Scalene.set_timer_signals()
        # CPU
        signal.signal(ScaleneSignals.cpu_signal, Scalene.cpu_signal_handler)
        # Set signal handlers for memory allocation and memcpy events.
        signal.signal(ScaleneSignals.malloc_signal, Scalene.malloc_signal_handler)
        signal.signal(ScaleneSignals.free_signal, Scalene.free_signal_handler)
        signal.signal(ScaleneSignals.fork_signal, Scalene.fork_signal_handler)
        signal.signal(
            ScaleneSignals.memcpy_signal,
            Scalene.memcpy_event_signal_handler,
        )
        # Set every signal to restart interrupted system calls.
        signal.siginterrupt(ScaleneSignals.cpu_signal, False)
        signal.siginterrupt(ScaleneSignals.malloc_signal, False)
        signal.siginterrupt(ScaleneSignals.free_signal, False)
        signal.siginterrupt(ScaleneSignals.memcpy_signal, False)
        signal.siginterrupt(ScaleneSignals.fork_signal, False)
        # Turn on the CPU profiling timer to run every mean_cpu_sampling_rate seconds.
        signal.setitimer(
            ScaleneSignals.cpu_timer_signal,
            Scalene.__args.cpu_sampling_rate,
            Scalene.__args.cpu_sampling_rate,
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

        Scalene.__args = cast(ScaleneArguments, arguments)

        if arguments.pid:
            # Child process.
            # We need to use the same directory as the parent.
            # The parent always puts this directory as the first entry in the PATH.
            # Extract the alias directory from the path.
            dirname = os.environ["PATH"].split(os.pathsep)[0]
            Scalene.__python_alias_dir = None
            Scalene.__python_alias_dir_name = Filename(dirname)
            Scalene.__pid = arguments.pid

        else:
            # Parent process.
            Scalene.__python_alias_dir = Filename(
                tempfile.mkdtemp(prefix="scalene")
            )
            Scalene.__python_alias_dir_name = Scalene.__python_alias_dir
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
            Scalene.__next_output_time += (
                Scalene.__args.output_profile_interval
            )
            Scalene.stop()
            stats = Scalene.__stats
            output = Scalene.__output
            output.output_profiles(
                stats,
                Scalene.__pid,
                Scalene.profile_this_code,
                Scalene.__python_alias_dir_name,
                Scalene.__python_alias_dir,
                profile_memory=not Scalene.__args.cpu_only,
                reduced_profile=Scalene.__args.reduced_profile,
            )
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
        # Sample GPU utilization at 1/10th the frequency of CPU
        # sampling to reduce overhead (it's costly).  We multiply the
        # elapsed time by a large number to get some moderately random
        # chunk of the elapsed time.
        gpu_load = 0.0
        if int(100000 * elapsed_wallclock) % 10 == 0:
            try:
                for g in GPUtil.getGPUs():
                    gpu_load += g.load
            except:
                pass
        # Deal with an odd case reported here: https://github.com/plasma-umass/scalene/issues/124
        # We don't want to report 'nan', so turn the load into 0.
        if math.isnan(gpu_load):
            gpu_load = 0.0
        gpu_time = gpu_load * Scalene.__last_cpu_sampling_rate
        Scalene.__stats.total_gpu_samples += gpu_time
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
            Scalene.enter_function_meta(frame, Scalene.__stats)
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
                    Scalene.__stats.gpu_samples[fname][lineno] += (
                        gpu_time / total_frames
                    )

            else:
                # We can't play the same game here of attributing
                # time, because we are in a thread, and threads don't
                # get signals in Python. Instead, we check if the
                # bytecode instruction being executed is a function
                # call.  If so, we attribute all the time to native.
                # NOTE: for now, we don't try to attribute GPU time to threads.
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
                Scalene.__args.cpu_sampling_rate,
                Scalene.__args.cpu_sampling_rate / 3.0,
            )
        Scalene.__last_cpu_sampling_rate = next_interval
        Scalene.__last_signal_time_wallclock = Scalene.get_wallclock_time()
        Scalene.__last_signal_time_virtual = Scalene.get_process_time()
        signal.setitimer(
            ScaleneSignals.cpu_timer_signal, next_interval, next_interval
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
    def enter_function_meta(
        frame: FrameType, stats: ScaleneStatistics
    ) -> None:
        fname = Filename(frame.f_code.co_filename)
        lineno = LineNumber(frame.f_lineno)
        f = frame
        while "<" in Filename(f.f_code.co_name):
            f = cast(FrameType, frame.f_back)
        if not Scalene.should_trace(f.f_code.co_filename):
            return
        fn_name = Filename(f.f_code.co_name)
        firstline = f.f_code.co_firstlineno
        # Prepend the class, if any
        while f and Scalene.should_trace(f.f_back.f_code.co_filename):  # type: ignore
            if "self" in f.f_locals:
                prepend_name = f.f_locals["self"].__class__.__name__
                if "Scalene" not in prepend_name:
                    fn_name = prepend_name + "." + fn_name
                break
            if "cls" in f.f_locals:
                prepend_name = f.f_locals["cls"].__name__
                if "Scalene" in prepend_name:
                    break
                fn_name = prepend_name + "." + fn_name
                break
            f = cast(FrameType, f.f_back)

        stats.function_map[fname][lineno] = fn_name
        stats.firstline_map[fn_name] = LineNumber(firstline)

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

    MAX_BUFSIZE = 256  # Must match SampleFile::MAX_BUFSIZE

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
        buf = bytearray(Scalene.MAX_BUFSIZE)
        try:
            buf = bytearray(Scalene.MAX_BUFSIZE)

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
            # Walk the stack backwards until we find a proper function
            # name (as in, one that doesn't contain "<", which
            # indicates things like list comprehensions).
            Scalene.enter_function_meta(frame, stats)
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
        signal.signal(ScaleneSignals.malloc_signal, Scalene.malloc_signal_handler)
        signal.signal(ScaleneSignals.free_signal, Scalene.free_signal_handler)
        signal.signal(
            ScaleneSignals.memcpy_signal,
            Scalene.memcpy_event_signal_handler,
        )
        signal.setitimer(
            ScaleneSignals.cpu_timer_signal,
            Scalene.__args.cpu_sampling_rate,
            Scalene.__args.cpu_sampling_rate,
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
                buf = bytearray(Scalene.MAX_BUFSIZE)
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
        if "site-packages" in filename or "/lib/python" in filename:
            # Don't profile Python internals.
            return False
        # If the @profile decorator has been used,
        # we restrict profiling to files containing decorated functions.
        if Scalene.__files_to_profile:
            return filename in Scalene.__files_to_profile
        # Generic handling follows (when no @profile decorator has been used).
        if not filename:
            return False
        if filename[0] == "<":
            if "<ipython" in filename:
                # Profiling code created in a Jupyter cell:
                # create a file to hold the contents.
                from IPython import get_ipython
                import re

                # Find the input where the function was defined;
                # we need this to properly annotate the code.
                result = re.match("<ipython-input-([0-9]+)-.*>", filename)
                if result:
                    # Write the cell's contents into the file.
                    with open(filename, "w+") as f:
                        # with open(str(frame.f_code.co_filename), "w+") as f:
                        f.write(
                            get_ipython().history_manager.input_hist_raw[
                                int(result.group(1))
                            ]
                        )
                return True
            else:
                # Not a real file and not a function created in Jupyter.
                return False
        if (
            "scalene/"
            in filename
            # or "scalene/__main__.py" in filename
        ):
            # Don't profile the profiler.
            return False
        if not Scalene.__args.profile_only in filename:
            return False
        if Scalene.__args.profile_all:
            # Profile everything else, except for "only" choices.
            if Scalene.__args.profile_only in filename:
                return True
            else:
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
    def start_signal_handler(
        signum: Union[
            Callable[[Signals, FrameType], None], int, Handlers, None
        ],
        this_frame: FrameType,
    ) -> None:
        Scalene.start()
        
    @staticmethod
    def stop_signal_handler(
        signum: Union[
            Callable[[Signals, FrameType], None], int, Handlers, None
        ],
        this_frame: FrameType,
    ) -> None:
        Scalene.stop()
        
    @staticmethod
    def disable_signals() -> None:
        """Turn off the profiling signals."""
        try:
            signal.setitimer(ScaleneSignals.cpu_timer_signal, 0)
            signal.signal(ScaleneSignals.malloc_signal, signal.SIG_IGN)
            signal.signal(ScaleneSignals.free_signal, signal.SIG_IGN)
            signal.signal(ScaleneSignals.memcpy_signal, signal.SIG_IGN)
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

    class StopJupyterExecution(Exception):
        """NOP exception to enable clean exits from within Jupyter notebooks."""

        def _render_traceback_(self) -> None:
            pass

    @staticmethod
    def clean_exit(code: int) -> None:
        """Replacement for sys.exit that exits cleanly from within Jupyter notebooks."""
        raise Scalene.StopJupyterExecution

    @staticmethod
    def parse_args() -> Tuple[argparse.Namespace, List[str]]:
        # In IPython, intercept exit cleanly (because sys.exit triggers a backtrace).
        try:
            from IPython import get_ipython

            if get_ipython():
                sys.exit = Scalene.clean_exit  # type: ignore
        except:
            pass
        defaults = ScaleneArguments()
        usage = dedent(
            """Scalene: a high-precision CPU and memory profiler.
https://github.com/plasma-umass/scalene

command-line:
   % scalene [options] yourprogram.py
or
   % python3 -m scalene [options] yourprogram.py

in Jupyter, line mode:
   %scrun [options] statement

in Jupyter, cell mode:
   %%scalene [options]
   code...
   code...
"""
            )
        epilog = dedent("""When running Scalene in the background, you can suspend/resume profiling
for the process ID that Scalene reports. For example:

   % python3 -m scalene [options] yourprogram.py &
 Scalene now profiling process 12345
   to disable profiling: python3 -m scalene.profile --off --pid 12345
   to resume profiling:  python3 -m scalene.profile --on  --pid 12345
"""
        )
        parser = argparse.ArgumentParser(
            prog="scalene",
            description=usage,
            epilog=epilog,
            formatter_class=argparse.RawTextHelpFormatter,
            allow_abbrev=False,
        )
        parser.add_argument(
            "--outfile",
            type=str,
            default=defaults.outfile,
            help="file to hold profiler output (default: "
            + ("stdout" if not defaults.outfile else defaults.outfile)
            + ")",
        )
        parser.add_argument(
            "--html",
            dest="html",
            action="store_const",
            const=True,
            default=defaults.html,
            help="output as HTML (default: "
            + str("html" if defaults.html else "text")
            + ")",
        )
        parser.add_argument(
            "--reduced-profile",
            dest="reduced_profile",
            action="store_const",
            const=True,
            default=defaults.reduced_profile,
            help="generate a reduced profile, with non-zero lines only (default: "
            + str(defaults.reduced_profile)
            + ")",
        )
        parser.add_argument(
            "--profile-interval",
            type=float,
            default=defaults.profile_interval,
            help="output profiles every so many seconds (default: "
            + str(defaults.profile_interval)
            + ")",
        )
        parser.add_argument(
            "--cpu-only",
            dest="cpu_only",
            action="store_const",
            const=True,
            default=defaults.cpu_only,
            help="only profile CPU time (default: profile "
            + ("CPU only" if defaults.cpu_only else "CPU, memory, and copying")
            + ")",
        )
        parser.add_argument(
            "--profile-all",
            dest="profile_all",
            action="store_const",
            const=True,
            default=defaults.profile_all,
            help="profile all executed code, not just the target program (default: "
            + (
                "all code"
                if defaults.profile_all
                else "only the target program"
            )
            + ")",
        )
        parser.add_argument(
            "--profile-only",
            dest="profile_only",
            type=str,
            default=defaults.profile_only,
            help="profile only code in files that contain the given string (default: "
            + (
                "no restrictions"
                if not defaults.profile_only
                else defaults.profile_only
            )
            + ")",
        )
        parser.add_argument(
            "--use-virtual-time",
            dest="use_virtual_time",
            action="store_const",
            const=True,
            default=defaults.use_virtual_time,
            help="measure only CPU time, not time spent in I/O or blocking (default: "
            + str(defaults.use_virtual_time)
            + ")",
        )
        parser.add_argument(
            "--cpu-percent-threshold",
            dest="cpu_percent_threshold",
            type=int,
            default=defaults.cpu_percent_threshold,
            help="only report profiles with at least this percent of CPU time (default: "
            + str(defaults.cpu_percent_threshold)
            + "%%)",
        )
        parser.add_argument(
            "--cpu-sampling-rate",
            dest="cpu_sampling_rate",
            type=float,
            default=defaults.cpu_sampling_rate,
            help="CPU sampling rate (default: every "
            + str(defaults.cpu_sampling_rate)
            + "s)",
        )
        parser.add_argument(
            "--malloc-threshold",
            dest="malloc_threshold",
            type=int,
            default=defaults.malloc_threshold,
            help="only report profiles with at least this many allocations (default: "
            + str(defaults.malloc_threshold)
            + ")",
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
    def setup_preload(args: argparse.Namespace) -> bool:
        # Return true iff we had to preload libraries and run another process.
        
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
        
        if args.cpu_only:
            return False

        try:
            from IPython import get_ipython

            if get_ipython():
                sys.exit = Scalene.clean_exit  # type: ignore
        except:
            pass
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
                result = subprocess.Popen(
                    new_args, close_fds=True, shell=False
                )
                # If running in the background, print the PID.
                if os.getpgrp() != os.tcgetpgrp(sys.stdout.fileno()):
                    # In the background.
                    print("Scalene now profiling process " + str(result.pid)) 
                    print("  to disable profiling: python3 -m scalene.profile --off --pid " + str(result.pid))
                    print("  to resume profiling:  python3 -m scalene.profile --on  --pid " + str(result.pid))

                result.wait()
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
                result = subprocess.Popen(
                    new_args, close_fds=True, shell=False
                )
                # If running in the background, print the PID.
                if os.getpgrp() != os.tcgetpgrp(sys.stdout.fileno()):
                    # In the background.
                    print("Scalene now profiling process " + str(result.pid))
                    print("  to disable profiling: python3 -m scalene.profile --off --pid " + str(result.pid))
                    print("  to resume profiling:  python3 -m scalene.profile --on  --pid " + str(result.pid))
                result.wait()
                if result.returncode < 0:
                    print(
                        "Scalene error: received signal",
                        signal.Signals(-result.returncode).name,
                    )
                sys.exit(result.returncode)
        return True
                    
    def profile_code(
        self,
        code: str,
        the_globals: Dict[str, str],
        the_locals: Dict[str, str],
    ) -> int:
        # Catch termination so we print a profile before exiting.
        self.start()
        # Run the code being profiled.
        exit_status = 0
        try:
            exec(code, the_globals, the_locals)
        except SystemExit as se:
            # Intercept sys.exit and propagate the error code.
            exit_status = se.code
        except BaseException as e:
            print("Error in program being profiled:\n", e)

        self.stop()
        # If we've collected any samples, dump them.
        if Scalene.__output.output_profiles(
            Scalene.__stats,
            Scalene.__pid,
            Scalene.profile_this_code,
            Scalene.__python_alias_dir_name,
            Scalene.__python_alias_dir,
            profile_memory=not Scalene.__args.cpu_only,
            reduced_profile=Scalene.__args.reduced_profile,
        ):
            pass
        else:
            print("Scalene: Program did not run for long enough to profile.")
        return exit_status

    @staticmethod
    def process_args(args: argparse.Namespace) -> None:
        Scalene.__args = cast(ScaleneArguments, args)
        Scalene.__next_output_time = (
            Scalene.get_wallclock_time() + Scalene.__args.profile_interval
        )
        Scalene.__output.html = args.html
        Scalene.__output.output_file = args.outfile
        Scalene.__is_child = args.pid != 0
        # the pid of the primary profiler
        Scalene.__parent_pid = args.pid if Scalene.__is_child else os.getpid()

    @staticmethod
    def main() -> None:
        (
            args,
            left,
        ) = Scalene.parse_args()
        Scalene.run_profiler(args, left)

    @staticmethod
    def run_profiler(args: argparse.Namespace, left: List[str]) -> None:
        # Set up signal handlers for starting and stopping profiling.
        signal.signal(ScaleneSignals.start_profiling_signal, Scalene.start_signal_handler)
        signal.signal(ScaleneSignals.stop_profiling_signal, Scalene.stop_signal_handler)
        signal.siginterrupt(ScaleneSignals.start_profiling_signal, False)
        signal.siginterrupt(ScaleneSignals.stop_profiling_signal, False)
        
        did_preload = Scalene.setup_preload(args)
        if not did_preload:
            # If running in the background, print the PID.
            if os.getpgrp() != os.tcgetpgrp(sys.stdout.fileno()):
                # In the background.
                print("Scalene now profiling process " + str(os.getpid()))
                print("  to disable profiling: python3 -m scalene.profile --off --pid " + str(os.getpid()))
                print("  to resume profiling:  python3 -m scalene.profile --on  --pid " + str(os.getpid()))
        Scalene.__stats.clear_all()
        sys.argv = left
        try:
            multiprocessing.set_start_method("fork")
        except:
            pass
        try:
            Scalene.process_args(args)
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
                        exit_status = profiler.profile_code(
                            code, the_locals, the_globals
                        )
                        sys.exit(exit_status)
                    except Scalene.StopJupyterExecution:
                        # Running in Jupyter notebooks
                        pass
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
        except Scalene.StopJupyterExecution:
            pass
        except BaseException:
            print("Scalene failed to initialize.\n" + traceback.format_exc())
            sys.exit(-1)
        finally:
            try:
                Scalene.__malloc_signal_fd.close()
                Scalene.__malloc_lock_fd.close()
                Scalene.__memcpy_signal_fd.close()
                Scalene.__memcpy_lock_fd.close()
            except BaseException:
                pass


if __name__ == "__main__":
    Scalene.main()
