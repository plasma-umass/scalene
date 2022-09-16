"""Scalene: a CPU+memory+GPU (and more) profiler for Python.

    https://github.com/plasma-umass/scalene

    See the paper "docs/scalene-paper.pdf" in this repository for technical
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
import contextlib
import functools
import gc
import http.server
import inspect
import json
import math
import multiprocessing
import os
import pathlib
import platform
import re
import signal
import socketserver
import stat
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from collections import defaultdict
from types import FrameType
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union, cast

from scalene.scalene_arguments import ScaleneArguments
from scalene.scalene_client_timer import ScaleneClientTimer
from scalene.scalene_funcutils import ScaleneFuncUtils
from scalene.scalene_json import ScaleneJSON
from scalene.scalene_mapfile import ScaleneMapFile
from scalene.scalene_output import ScaleneOutput
from scalene.scalene_preload import ScalenePreload
from scalene.scalene_signals import ScaleneSignals
from scalene.scalene_statistics import (
    Address,
    ByteCodeIndex,
    Filename,
    LineNumber,
    ScaleneStatistics,
)

if sys.platform != "win32":
    import resource

if platform.system() == "Darwin":
    from scalene.scalene_apple_gpu import ScaleneAppleGPU as ScaleneGPU
else:
    from scalene.scalene_gpu import ScaleneGPU  # type: ignore

from scalene.scalene_parseargs import ScaleneParseArgs, StopJupyterExecution
from scalene.scalene_sigqueue import ScaleneSigQueue

MINIMUM_PYTHON_VERSION_MAJOR = 3
MINIMUM_PYTHON_VERSION_MINOR = 8


def require_python(version: Tuple[int, int]) -> None:
    assert (
        sys.version_info >= version
    ), f"Scalene requires Python version {version[0]}.{version[1]} or above."


require_python((MINIMUM_PYTHON_VERSION_MAJOR, MINIMUM_PYTHON_VERSION_MINOR))


# Scalene fully supports Unix-like operating systems; in
# particular, Linux, Mac OS X, and WSL 2 (Windows Subsystem for Linux 2 = Ubuntu).
# It also has partial support for Windows.

# Install our profile decorator.


def scalene_redirect_profile(func: Any) -> Any:
    """Handle @profile decorators.

    If Scalene encounters any functions decorated by @profile, it will
    only report stats for those functions.

    """
    return Scalene.profile(func)


builtins.profile = scalene_redirect_profile  # type: ignore

# Must equal src/include/sampleheap.hpp NEWLINE *minus 1*
NEWLINE_TRIGGER_LENGTH = 98820  # SampleHeap<...>::NEWLINE-1


def start() -> None:
    """Start profiling."""
    Scalene.start()


def stop() -> None:
    """Stop profiling."""
    Scalene.stop()


class Scalene:
    """The Scalene profiler itself."""

    __in_jupyter = False  # are we running inside a Jupyter notebook
    __start_time = 0  # start of profiling, in nanoseconds
    __sigterm_exit_code = 143
    # Whether the current profiler is a child
    __is_child = -1
    # the pid of the primary profiler
    __parent_pid = -1
    __initialized: bool = False
    __last_profiled = (Filename("NADA"), LineNumber(0), ByteCodeIndex(0))
    __last_profiled_invalidated = False
    __gui_dir = "scalene-gui"
    __profile_filename = "profile.json"
    __localhost = "http://localhost"
    __profiler_html = "profiler.html"
    __error_message = "Error in program being profiled"
    BYTES_PER_MB = 1024 * 1024

    MALLOC_ACTION = "M"
    FREE_ACTION = "F"
    FREE_ACTION_SAMPLED = "f"

    # Support for @profile
    # decorated files
    __files_to_profile: Set[Filename] = set()
    # decorated functions
    __functions_to_profile: Dict[Filename, Set[Any]] = defaultdict(
        lambda: set()
    )

    # Cache the original thread join function, which we replace with our own version.
    __original_thread_join = threading.Thread.join

    # As above; we'll cache the original thread and replace it.
    __original_lock = threading.Lock

    __args = ScaleneArguments()
    __signals = ScaleneSignals()
    __stats = ScaleneStatistics()
    __output = ScaleneOutput()
    __json = ScaleneJSON()
    __gpu = ScaleneGPU()

    __output.gpu = __gpu.has_gpu()
    __json.gpu = __gpu.has_gpu()
    __invalidate_queue: List[Tuple[Filename, LineNumber]] = []
    __invalidate_mutex: threading.Lock

    @staticmethod
    def get_original_lock() -> threading.Lock:
        """Return the true lock, which we shim in replacement_lock.py."""
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

    # when did we last receive a signal?
    __last_signal_time_virtual: float = 0
    __last_signal_time_wallclock: float = 0
    __last_signal_time_sys: float = 0
    __last_signal_time_user: float = 0

    # path for the program being profiled
    __program_path: str = ""
    # temporary directory to hold aliases to Python

    __python_alias_dir: pathlib.Path

    # Profile output parameters

    # when we output the next profile
    __next_output_time: float = float("inf")
    # pid for tracking child processes
    __pid: int = 0

    __malloc_mapfile: ScaleneMapFile
    __memcpy_mapfile: ScaleneMapFile

    # Program-specific information:
    #   the name of the program being profiled
    __program_being_profiled = Filename("")

    # Is the thread sleeping? (We use this to properly attribute CPU time.)
    __is_thread_sleeping: Dict[int, bool] = defaultdict(
        bool
    )  # False by default

    child_pids: Set[
        int
    ] = set()  # Needs to be unmangled to be accessed by shims

    # Signal queues for allocations and memcpy
    __alloc_sigq: ScaleneSigQueue[Any]
    __memcpy_sigq: ScaleneSigQueue[Any]
    __sigqueues: List[ScaleneSigQueue[Any]]

    client_timer: ScaleneClientTimer = ScaleneClientTimer()

    __orig_signal = signal.signal
    __orig_exit = os._exit
    __orig_raise_signal = signal.raise_signal

    __orig_kill = os.kill
    if sys.platform != "win32":
        __orig_setitimer = signal.setitimer
        __orig_siginterrupt = signal.siginterrupt

    @staticmethod
    def get_all_signals_set() -> Set[int]:
        """Return the set of all signals currently set.

        Used by replacement_signal_fns.py to shim signals used by the client program.
        """
        return set(Scalene.__signals.get_all_signals())

    @staticmethod
    def get_timer_signals() -> Tuple[int, signal.Signals]:
        """Return the set of all TIMER signals currently set.

        Used by replacement_signal_fns.py to shim timers used by the client program.
        """
        return Scalene.__signals.get_timer_signals()

    @staticmethod
    def set_in_jupyter() -> None:
        """Tell Scalene that it is running inside a Jupyter notebook."""
        Scalene.__in_jupyter = True

    @staticmethod
    def in_jupyter() -> bool:
        """Return whether Scalene is running inside a Jupyter notebook."""
        return Scalene.__in_jupyter

    @staticmethod
    def interruption_handler(
        signum: Union[
            Callable[[signal.Signals, FrameType], None],
            int,
            signal.Handlers,
            None,
        ],
        this_frame: Optional[FrameType],
    ) -> None:
        """Handle keyboard interrupts (e.g., Ctrl-C)."""
        raise KeyboardInterrupt

    @staticmethod
    def on_stack(
        frame: FrameType, fname: Filename, lineno: LineNumber
    ) -> Optional[FrameType]:
        """Find a frame matching the given filename and line number, if any.

        Used for checking whether we are still executing the same line
        of code or not in invalidate_lines (for per-line memory
        accounting).
        """
        f = frame
        current_file_and_line = (fname, lineno)
        while f:
            if (f.f_code.co_filename, f.f_lineno) == current_file_and_line:
                return f
            f = cast(FrameType, f.f_back)
        return None

    @staticmethod
    def update_line() -> None:
        """Mark a new line by allocating the trigger number of bytes."""
        bytearray(NEWLINE_TRIGGER_LENGTH)

    @staticmethod
    def invalidate_lines(frame: FrameType, _event: str, _arg: str) -> Any:
        """Mark the last_profiled information as invalid as soon as we execute a different line of code."""
        try:
            # If we are still on the same line, return.
            ff = frame.f_code.co_filename
            fl = frame.f_lineno
            (fname, lineno, lasti) = Scalene.__last_profiled
            if (ff == fname) and (fl == lineno):
                return None
            # Different line: stop tracing this frame.
            frame.f_trace = None
            frame.f_trace_lines = False
            # If we are not in a file we should be tracing, return.
            if not Scalene.should_trace(ff):
                return None
            if f := Scalene.on_stack(frame, fname, lineno):
                # We are still on the same line, but somewhere up the stack
                # (since we returned when it was the same line in this
                # frame). Stop tracing in this frame.
                return None
            # We are on a different line; stop tracing and increment the count.
            sys.settrace(None)
            with Scalene.__invalidate_mutex:
                Scalene.__invalidate_queue.append(
                    (Scalene.__last_profiled[0], Scalene.__last_profiled[1])
                )
                print(Scalene.__last_profiled)
                Scalene.update_line()
            Scalene.__last_profiled_invalidated = False
            Scalene.__last_profiled = (
                Filename(ff),
                LineNumber(fl),
                ByteCodeIndex(frame.f_lasti),
            )
            return None
        except AttributeError:
            # This can happen when Scalene shuts down.
            return None
        except Exception as e:
            print(f"{Scalene.__error_message}:\n", e)
            traceback.print_exc()
            return None

    @classmethod
    def clear_metrics(cls) -> None:
        """Clear the various states for forked processes."""
        cls.__stats.clear()
        cls.child_pids.clear()

    @classmethod
    def add_child_pid(cls, pid: int) -> None:
        """Add this pid to the set of children. Used when forking."""
        cls.child_pids.add(pid)

    @classmethod
    def remove_child_pid(cls, pid: int) -> None:
        """Remove a child once we have joined with it (used by replacement_pjoin.py)."""
        with contextlib.suppress(KeyError):
            cls.child_pids.remove(pid)

    @staticmethod
    def profile(func: Any) -> Any:
        """Record the file and function name.

        Replacement @profile decorator function.  Scalene tracks which
        functions - in which files - have been decorated; if any have,
        it and only reports stats for those.

        """
        Scalene.__files_to_profile.add(func.__code__.co_filename)
        Scalene.__functions_to_profile[func.__code__.co_filename].add(func)

        @functools.wraps(func)
        def wrapper_profile(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return wrapper_profile

    @staticmethod
    def shim(func: Callable[[Any], Any]) -> Any:
        """Provide a decorator that calls the wrapped function with the
        Scalene variant.

                Wrapped function must be of type (s: Scalene) -> Any.

                This decorator allows for marking a function in a separate
                file as a drop-in replacement for an existing library
                function. The intention is for these functions to replace a
                function that indefinitely blocks (which interferes with
                Scalene) with a function that awakens periodically to allow
                for signals to be delivered.

        """
        func(Scalene)
        # Returns the function itself to the calling file for the sake
        # of not displaying unusual errors if someone attempts to call
        # it

        @functools.wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return wrapped

    @staticmethod
    def set_thread_sleeping(tid: int) -> None:
        """Indicate the given thread is sleeping.

        Used to attribute CPU time.
        """
        Scalene.__is_thread_sleeping[tid] = True

    @staticmethod
    def reset_thread_sleeping(tid: int) -> None:
        """Indicate the given thread is not sleeping.

        Used to attribute CPU time."""
        Scalene.__is_thread_sleeping[tid] = False

    timer_signals = True

    @staticmethod
    def windows_timer_loop() -> None:
        """For Windows, send periodic timer signals; launch as a background thread."""
        Scalene.timer_signals = True
        while Scalene.timer_signals:
            time.sleep(Scalene.__args.cpu_sampling_rate)
            Scalene.__orig_raise_signal(Scalene.__signals.cpu_signal)

    @staticmethod
    def start_signal_queues() -> None:
        """Start the signal processing queues (i.e., their threads)."""
        for sigq in Scalene.__sigqueues:
            sigq.start()

    @staticmethod
    def stop_signal_queues() -> None:
        """Stop the signal processing queues (i.e., their threads)."""
        for sigq in Scalene.__sigqueues:
            sigq.stop()

    @staticmethod
    def term_signal_handler(
        signum: Union[
            Callable[[signal.Signals, FrameType], None],
            int,
            signal.Handlers,
            None,
        ],
        this_frame: Optional[FrameType],
    ) -> None:
        """Handle terminate signals."""
        Scalene.stop()
        Scalene.output_profile()

        Scalene.__orig_exit(Scalene.__sigterm_exit_code)

    @staticmethod
    def malloc_signal_handler(
        signum: Union[
            Callable[[signal.Signals, FrameType], None],
            int,
            signal.Handlers,
            None,
        ],
        this_frame: Optional[FrameType],
    ) -> None:
        """Handle allocation signals.""" 
        if this_frame:
            Scalene.enter_function_meta(this_frame, Scalene.__stats)
        # Walk the stack till we find a line of code in a file we are tracing.
        found_frame = False
        f = this_frame
        while f:
            if Scalene.should_trace(f.f_code.co_filename):
                found_frame = True
                break
            f = cast(FrameType, f.f_back)
        if not found_frame:
            return
        assert f
        # Start tracing until we execute a different line of
        # code in a file we are tracking.
        # First, see if we have now executed a different line of code.
        # If so, increment.
        # TODO: assess the necessity of the following block
        # if invalidated or not (
        #     fname == Filename(f.f_code.co_filename)
        #     and lineno == LineNumber(f.f_lineno)
        # ):
        #     with Scalene.__invalidate_mutex:
        #         Scalene.__invalidate_queue.append(
        #             (Filename(f.f_code.co_filename), LineNumber(f.f_lineno))
        #         )
        #         Scalene.update_line()
        Scalene.__last_profiled_invalidated = False
        Scalene.__last_profiled = (
            Filename(f.f_code.co_filename),
            LineNumber(f.f_lineno),
            ByteCodeIndex(f.f_lasti),
        )
        Scalene.__alloc_sigq.put([0])
        # Start tracing.
        sys.settrace(Scalene.invalidate_lines)
        f.f_trace = Scalene.invalidate_lines
        f.f_trace_lines = True
        del this_frame

    @staticmethod
    def free_signal_handler(
        signum: Union[
            Callable[[signal.Signals, FrameType], None],
            int,
            signal.Handlers,
            None,
        ],
        this_frame: Optional[FrameType],
    ) -> None:
        """Handle free signals."""
        if this_frame:
            Scalene.enter_function_meta(this_frame, Scalene.__stats)
        Scalene.__alloc_sigq.put([0])
        del this_frame

    @staticmethod
    def memcpy_signal_handler(
        signum: Union[
            Callable[[signal.Signals, FrameType], None],
            int,
            signal.Handlers,
            None,
        ],
        this_frame: Optional[FrameType],
    ) -> None:
        """Handle memcpy signals."""
        Scalene.__memcpy_sigq.put((signum, this_frame))
        del this_frame

    @staticmethod
    def enable_signals() -> None:
        """Set up the signal handlers to handle interrupts for profiling and start the
        timer interrupts."""
        if sys.platform == "win32":
            Scalene.timer_signals = True
            Scalene.__orig_signal(
                Scalene.__signals.cpu_signal,
                Scalene.cpu_signal_handler,
            )
            # On Windows, we simulate timer signals by running a background thread.
            Scalene.timer_signals = True
            t = threading.Thread(target=Scalene.windows_timer_loop)
            t.start()
            Scalene.start_signal_queues()
            return
        Scalene.start_signal_queues()
        # Set signal handlers for memory allocation and memcpy events.
        Scalene.__orig_signal(
            Scalene.__signals.malloc_signal, Scalene.malloc_signal_handler
        )
        Scalene.__orig_signal(
            Scalene.__signals.free_signal, Scalene.free_signal_handler
        )
        Scalene.__orig_signal(
            Scalene.__signals.memcpy_signal, Scalene.memcpy_signal_handler
        )
        Scalene.__orig_signal(signal.SIGTERM, Scalene.term_signal_handler)
        # Set every signal to restart interrupted system calls.
        for s in Scalene.__signals.get_all_signals():
            Scalene.__orig_siginterrupt(s, False)
        # Turn on the CPU profiling timer to run at the sampling rate, exactly once.
        Scalene.__orig_signal(
            Scalene.__signals.cpu_signal,
            Scalene.cpu_signal_handler,
        )
        if sys.platform != "win32":
            Scalene.__orig_setitimer(
                Scalene.__signals.cpu_timer_signal,
                Scalene.__args.cpu_sampling_rate,
            )

    def __init__(
        self,
        arguments: argparse.Namespace,
        program_being_profiled: Optional[Filename] = None,
    ) -> None:
        import scalene.replacement_exit
        import scalene.replacement_get_context

        # Hijack lock, poll, thread_join, fork, and exit.
        import scalene.replacement_lock
        import scalene.replacement_mp_lock
        import scalene.replacement_pjoin
        import scalene.replacement_signal_fns
        import scalene.replacement_thread_join

        if sys.platform != "win32":
            import scalene.replacement_fork
            import scalene.replacement_poll_selector

        Scalene.__args = cast(ScaleneArguments, arguments)
        Scalene.__alloc_sigq = ScaleneSigQueue(
            Scalene.alloc_sigqueue_processor
        )
        Scalene.__memcpy_sigq = ScaleneSigQueue(
            Scalene.memcpy_sigqueue_processor
        )
        Scalene.__sigqueues = [
            Scalene.__alloc_sigq,
            Scalene.__memcpy_sigq,
        ]
        Scalene.__invalidate_mutex = Scalene.get_original_lock()

        # Initialize the malloc related files; if for whatever reason
        # the files don't exist and we are supposed to be profiling
        # memory, exit.
        try:
            Scalene.__malloc_mapfile = ScaleneMapFile("malloc")
            Scalene.__memcpy_mapfile = ScaleneMapFile("memcpy")
        except Exception:
            # Ignore if we aren't profiling memory; otherwise, exit.
            if not arguments.cpu_only:
                sys.exit(1)

        Scalene.__signals.set_timer_signals(arguments.use_virtual_time)
        if arguments.pid:
            # Child process.
            # We need to use the same directory as the parent.
            # The parent always puts this directory as the first entry in the PATH.
            # Extract the alias directory from the path.
            dirname = os.environ["PATH"].split(os.pathsep)[0]
            Scalene.__python_alias_dir = pathlib.Path(dirname)
            Scalene.__pid = arguments.pid

        else:
            # Parent process.
            Scalene.__python_alias_dir = pathlib.Path(
                tempfile.mkdtemp(prefix="scalene")
            )
            # Create a temporary directory to hold aliases to the Python
            # executable, so scalene can handle multiple processes; each
            # one is a shell script that redirects to Scalene.
            Scalene.__pid = 0
            cmdline = ""
            # Pass along commands from the invoking command line.
            cmdline += f" --cpu-sampling-rate={arguments.cpu_sampling_rate}"
            if arguments.use_virtual_time:
                cmdline += " --use-virtual-time"
            if "off" in arguments and arguments.off:
                cmdline += " --off"
            if arguments.cpu_only:
                cmdline += " --cpu-only"

            environ = ScalenePreload.get_preload_environ(arguments)
            preface = " ".join(
                "=".join((k, str(v))) for (k, v) in environ.items()
            )

            # Add the --pid field so we can propagate it to the child.
            cmdline += f" --pid={os.getpid()} ---"
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
                fname = os.path.join(Scalene.__python_alias_dir, name)
                with open(fname, "w") as file:
                    file.write(payload)
                os.chmod(fname, stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR)
            # Finally, insert this directory into the path.
            sys.path.insert(0, str(Scalene.__python_alias_dir))
            os.environ["PATH"] = (
                str(Scalene.__python_alias_dir)
                + os.pathsep
                + os.environ["PATH"]
            )
            # Force the executable (if anyone invokes it later) to point to one of our aliases.
            sys.executable = Scalene.__all_python_names[0]

        # Register the exit handler to run when the program terminates or we quit.
        atexit.register(Scalene.exit_handler)
        # Store relevant names (program, path).
        if program_being_profiled:
            Scalene.__program_being_profiled = Filename(
                # os.path.abspath(program_being_profiled)
                program_being_profiled
            )

    @staticmethod
    def cpu_signal_handler(
        signum: Union[
            Callable[[signal.Signals, FrameType], None],
            int,
            signal.Handlers,
            None,
        ],
        this_frame: Optional[FrameType],
    ) -> None:
        """Handle CPU signals."""
        # Get current time stats.
        now_sys: float = 0
        now_user: float = 0
        if sys.platform != "win32":
            # On Linux/Mac, use getrusage, which provides higher
            # resolution values than os.times() for some reason.
            ru = resource.getrusage(resource.RUSAGE_SELF)
            now_sys = ru.ru_stime
            now_user = ru.ru_utime
        else:
            time_info = os.times()
            now_sys = time_info.system
            now_user = time_info.user
        now_virtual = time.process_time()
        now_wallclock = time.perf_counter()
        if (
            Scalene.__last_signal_time_virtual == 0
            or Scalene.__last_signal_time_wallclock == 0
        ):
            # Initialization: store values and update on the next pass.
            Scalene.__last_signal_time_virtual = now_virtual
            Scalene.__last_signal_time_wallclock = now_wallclock
            Scalene.__last_signal_time_sys = now_sys
            Scalene.__last_signal_time_user = now_user
            if sys.platform != "win32":
                Scalene.__orig_setitimer(
                    Scalene.__signals.cpu_timer_signal,
                    Scalene.__args.cpu_sampling_rate,
                )
            return

        (gpu_load, gpu_mem_used) = Scalene.__gpu.get_stats()

        # Process this CPU sample.
        Scalene.process_cpu_sample(
            signum,
            Scalene.compute_frames_to_record(),
            now_virtual,
            now_wallclock,
            now_sys,
            now_user,
            gpu_load,
            gpu_mem_used,
            Scalene.__last_signal_time_virtual,
            Scalene.__last_signal_time_wallclock,
            Scalene.__last_signal_time_sys,
            Scalene.__last_signal_time_user,
            Scalene.__is_thread_sleeping,
        )
        elapsed = now_wallclock - Scalene.__last_signal_time_wallclock
        # Store the latest values as the previously recorded values.
        Scalene.__last_signal_time_virtual = now_virtual
        Scalene.__last_signal_time_wallclock = now_wallclock
        Scalene.__last_signal_time_sys = now_sys
        Scalene.__last_signal_time_user = now_user
        # Restart the timer while handling any timers set by the client.
        if sys.platform != "win32":
            if Scalene.client_timer.is_set:

                (
                    should_raise,
                    remaining_time,
                ) = Scalene.client_timer.yield_next_delay(elapsed)
                if should_raise:
                    Scalene.__orig_raise_signal(signal.SIGUSR1)
                # NOTE-- 0 will only be returned if the 'seconds' have elapsed
                # and there is no interval
                to_wait: float
                if remaining_time > 0:
                    to_wait = min(
                        remaining_time, Scalene.__args.cpu_sampling_rate
                    )
                else:
                    to_wait = Scalene.__args.cpu_sampling_rate
                    Scalene.client_timer.reset()
                Scalene.__orig_setitimer(
                    Scalene.__signals.cpu_timer_signal,
                    to_wait,
                )
            else:
                Scalene.__orig_setitimer(
                    Scalene.__signals.cpu_timer_signal,
                    Scalene.__args.cpu_sampling_rate,
                )

    @staticmethod
    def output_profile() -> bool:
        # sourcery skip: inline-immediately-returned-variable
        """Output the profile. Returns true iff there was any info reported the profile."""
        if Scalene.__args.json:
            json_output = Scalene.__json.output_profiles(
                Scalene.__program_being_profiled,
                Scalene.__stats,
                Scalene.__pid,
                Scalene.profile_this_code,
                Scalene.__python_alias_dir,
                Scalene.__program_path,
                profile_memory=not Scalene.__args.cpu_only,
            )
            if not Scalene.__output.output_file:
                Scalene.__output.output_file = "/dev/stdout"
            with open(Scalene.__output.output_file, "w") as f:
                f.write(
                    json.dumps(json_output, sort_keys=True, indent=4) + "\n"
                )
            return json_output != {}

        else:
            output = Scalene.__output
            column_width = Scalene.__args.column_width
            if not Scalene.__args.html:
                # Get column width of the terminal and adjust to fit.
                with contextlib.suppress(Exception):
                    # If we are in a Jupyter notebook, stick with 132
                    if "ipykernel" in sys.modules:
                        column_width = 132
                    else:
                        import shutil

                        column_width = shutil.get_terminal_size().columns
            did_output: bool = output.output_profiles(
                column_width,
                Scalene.__stats,
                Scalene.__pid,
                Scalene.profile_this_code,
                Scalene.__python_alias_dir,
                Scalene.__program_path,
                profile_memory=not Scalene.__args.cpu_only,
                reduced_profile=Scalene.__args.reduced_profile,
            )
            return did_output

    @staticmethod
    def profile_this_code(fname: Filename, lineno: LineNumber) -> bool:
        # sourcery skip: inline-immediately-returned-variable
        """When using @profile, only profile files & lines that have been decorated."""
        if not Scalene.__files_to_profile:
            return True
        if fname not in Scalene.__files_to_profile:
            return False
        # Now check to see if it's the right line range.
        line_info = (
            inspect.getsourcelines(fn)
            for fn in Scalene.__functions_to_profile[fname]
        )
        found_function = any(
            line_start <= lineno < line_start + len(lines)
            for (lines, line_start) in line_info
        )
        return found_function

    @staticmethod
    def process_cpu_sample(
        _signum: Union[
            Callable[[signal.Signals, FrameType], None],
            int,
            signal.Handlers,
            None,
        ],
        new_frames: List[Tuple[FrameType, int, FrameType]],
        now_virtual: float,
        now_wallclock: float,
        now_sys: float,
        now_user: float,
        gpu_load: float,
        gpu_mem_used: float,
        prev_virtual: float,
        prev_wallclock: float,
        _prev_sys: float,
        prev_user: float,
        is_thread_sleeping: Dict[int, bool],
    ) -> None:
        """Handle interrupts for CPU profiling."""
        # We have recorded how long it has been since we received a timer
        # before.  See the logic below.
        # If it's time to print some profiling info, do so.

        if now_wallclock >= Scalene.__next_output_time:
            # Print out the profile. Set the next output time, stop
            # signals, print the profile, and then start signals
            # again.
            Scalene.__next_output_time += Scalene.__args.profile_interval
            stats = Scalene.__stats
            # pause (lock) all the queues to prevent updates while we output
            with contextlib.ExitStack() as stack:
                _ = [stack.enter_context(s.lock) for s in Scalene.__sigqueues]
                stats.stop_clock()
                Scalene.output_profile()
                stats.start_clock()

        if not new_frames:
            # No new frames, so nothing to update.
            return

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
        elapsed_virtual = now_virtual - prev_virtual
        elapsed_wallclock = now_wallclock - prev_wallclock
        # CPU utilization is the fraction of time spent on the CPU
        # over the total time.
        elapsed_user = now_user - prev_user
        cpu_utilization = 0.0
        if elapsed_wallclock != 0:
            cpu_utilization = elapsed_user / elapsed_wallclock
        # On multicore systems running multi-threaded native code, CPU
        # utilization can exceed 1; that is, elapsed user time is
        # longer than elapsed wallclock time. If this occurs, set
        # wall clock time to user time and set CPU utilization to 100%.
        if cpu_utilization > 1.0:
            cpu_utilization = 1.0
            elapsed_wallclock = elapsed_user
        # Deal with an odd case reported here: https://github.com/plasma-umass/scalene/issues/124
        # (Note: probably obsolete now that Scalene is using the nvidia wrappers, but just in case...)
        # We don't want to report 'nan', so turn the load into 0.
        if math.isnan(gpu_load):
            gpu_load = 0.0
        gpu_time = gpu_load * Scalene.__args.cpu_sampling_rate
        Scalene.__stats.total_gpu_samples += gpu_time
        python_time = Scalene.__args.cpu_sampling_rate
        c_time = elapsed_virtual - python_time
        c_time = max(c_time, 0)
        # Now update counters (weighted) for every frame we are tracking.
        total_time = python_time + c_time

        # First, find out how many frames are not sleeping.  We need
        # to know this number so we can parcel out time appropriately
        # (equally to each running thread).
        total_frames = sum(
            not is_thread_sleeping[tident]
            for frame, tident, orig_frame in new_frames
        )

        if total_frames == 0:
            total_frames = 1

        normalized_time = total_time / total_frames

        # Now attribute execution time.

        main_thread_frame = new_frames[0][0]

        average_python_time = python_time / total_frames
        average_c_time = c_time / total_frames
        average_gpu_time = gpu_time / total_frames
        average_cpu_time = (python_time + c_time) / total_frames

        # First, handle the main thread.
        Scalene.enter_function_meta(main_thread_frame, Scalene.__stats)
        fname = Filename(main_thread_frame.f_code.co_filename)
        lineno = LineNumber(main_thread_frame.f_lineno)
        main_tid = cast(int, threading.main_thread().ident)
        if not is_thread_sleeping[main_tid]:
            Scalene.__stats.cpu_samples_python[fname][
                lineno
            ] += average_python_time
            Scalene.__stats.cpu_samples_c[fname][lineno] += average_c_time
            Scalene.__stats.cpu_samples[fname] += average_cpu_time
            Scalene.__stats.cpu_utilization[fname][lineno].push(
                cpu_utilization
            )
            Scalene.__stats.gpu_samples[fname][lineno] += average_gpu_time
            Scalene.__stats.gpu_mem_samples[fname][lineno].push(gpu_mem_used)

        # Now handle the rest of the threads.
        for (frame, tident, orig_frame) in new_frames:
            if frame == main_thread_frame:
                continue
            # In a thread.
            fname = Filename(frame.f_code.co_filename)
            lineno = LineNumber(frame.f_lineno)
            Scalene.enter_function_meta(frame, Scalene.__stats)
            # We can't play the same game here of attributing
            # time, because we are in a thread, and threads don't
            # get signals in Python. Instead, we check if the
            # bytecode instruction being executed is a function
            # call.  If so, we attribute all the time to native.
            # NOTE: for now, we don't try to attribute GPU time to threads.
            if is_thread_sleeping[tident]:
                # Ignore sleeping threads.
                continue
            # Check if the original caller is stuck inside a call.
            if ScaleneFuncUtils.is_call_function(
                orig_frame.f_code,
                ByteCodeIndex(orig_frame.f_lasti),
            ):
                # It is. Attribute time to native.
                Scalene.__stats.cpu_samples_c[fname][lineno] += normalized_time
            else:
                # Not in a call function so we attribute the time to Python.
                Scalene.__stats.cpu_samples_python[fname][
                    lineno
                ] += normalized_time
            Scalene.__stats.cpu_samples[fname] += normalized_time
            Scalene.__stats.cpu_utilization[fname][lineno].push(
                cpu_utilization
            )

        # Clean up all the frames
        del new_frames[:]
        del new_frames
        del is_thread_sleeping
        Scalene.__stats.total_cpu_samples += total_time

    # Returns final frame (up to a line in a file we are profiling), the thread identifier, and the original frame.
    @staticmethod
    def compute_frames_to_record() -> List[Tuple[FrameType, int, FrameType]]:
        """Collect all stack frames that Scalene actually processes."""
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

        tid = cast(int, threading.main_thread().ident)
        frames.insert(
            0,
            (
                sys._current_frames().get(tid, cast(FrameType, None)),
                tid,
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
                else:
                    break
                if frame:
                    fname = frame.f_code.co_filename
            if frame:
                new_frames.append((frame, tident, orig_frame))
        del frames[:]
        return new_frames

    @staticmethod
    def enter_function_meta(
        frame: FrameType, stats: ScaleneStatistics
    ) -> None:
        """Update tracking info so we can correctly report line number info later."""
        fname = Filename(frame.f_code.co_filename)
        lineno = LineNumber(frame.f_lineno)

        f = frame
        try:
            while "<" in Filename(f.f_code.co_name):
                f = cast(FrameType, f.f_back)
                # Handle case where the function with the name wrapped in triangle brackets is at the bottom of the stack
                if f is None:
                    return
        except Exception:
            return
        if not Scalene.should_trace(f.f_code.co_filename):
            return

        fn_name = Filename(f.f_code.co_name)
        firstline = f.f_code.co_firstlineno
        # Prepend the class, if any
        while (
            f
            and f.f_back
            and f.f_back.f_code
            # NOTE: next line disabled as it is interfering with name resolution for thread run methods
            # and Scalene.should_trace(f.f_back.f_code.co_filename)
        ):
            if "self" in f.f_locals:
                prepend_name = f.f_locals["self"].__class__.__name__
                if "Scalene" not in prepend_name:
                    fn_name = Filename(f"{prepend_name}.{fn_name}")
                break
            if "cls" in f.f_locals:
                prepend_name = getattr(f.f_locals["cls"], "__name__", None)
                if not prepend_name or "Scalene" in prepend_name:
                    break
                fn_name = Filename(f"{prepend_name}.{fn_name}")
                break
            f = f.f_back

        stats.function_map[fname][lineno] = fn_name
        stats.firstline_map[fn_name] = LineNumber(firstline)

    @staticmethod
    def alloc_sigqueue_processor(x: Optional[List[int]]) -> None:
        """Handle interrupts for memory profiling (mallocs and frees)."""
        stats = Scalene.__stats
        curr_pid = os.getpid()
        # Process the input array from where we left off reading last time.
        arr: List[
            Tuple[
                int,
                str,
                float,
                float,
                str,
                Filename,
                LineNumber,
                ByteCodeIndex,
            ]
        ] = []
        with contextlib.suppress(FileNotFoundError):
            while Scalene.__malloc_mapfile.read():
                count_str = Scalene.__malloc_mapfile.get_str()
                if count_str.strip() == "":
                    break
                (
                    action,
                    alloc_time_str,
                    count_str,
                    python_fraction_str,
                    pid,
                    pointer,
                    reported_fname,
                    reported_lineno,
                    bytei_str,
                ) = count_str.split(",")
                if int(curr_pid) != int(pid):
                    continue
                arr.append(
                    (
                        int(alloc_time_str),
                        action,
                        float(count_str),
                        float(python_fraction_str),
                        pointer,
                        Filename(reported_fname),
                        LineNumber(int(reported_lineno)),
                        ByteCodeIndex(int(bytei_str)),
                    )
                )

        # Iterate through the array to compute the new current footprint
        # and update the global __memory_footprint_samples. Since on some systems,
        # we get free events before mallocs, force `before` to always be at least 0.
        before = max(stats.current_footprint, 0)
        prevmax = stats.max_footprint
        freed_last_trigger = 0
        for item in arr:
            (
                _alloc_time,
                action,
                count,
                _python_fraction,
                pointer,
                fname,
                lineno,
                bytei,
            ) = item
            is_malloc = action == Scalene.MALLOC_ACTION
            count /= Scalene.BYTES_PER_MB
            if is_malloc:
                stats.current_footprint += count
                if stats.current_footprint > stats.max_footprint:
                    stats.max_footprint = stats.current_footprint
                    stats.max_footprint_loc = (fname, lineno)
            else:
                assert action in [
                    Scalene.FREE_ACTION,
                    Scalene.FREE_ACTION_SAMPLED,
                ]
                stats.current_footprint -= count
                # Force current footprint to be non-negative; this
                # code is needed because Scalene can miss some initial
                # allocations at startup.
                stats.current_footprint = max(0, stats.current_footprint)
                if (
                    action == Scalene.FREE_ACTION_SAMPLED
                    and stats.last_malloc_triggered[2] == pointer
                ):
                    freed_last_trigger += 1
            timestamp = time.monotonic_ns() - Scalene.__start_time
            if len(stats.memory_footprint_samples) > 2:
                # Compress the footprints by discarding intermediate
                # points along increases and decreases. For example:
                # if the new point is an increase over the previous
                # point, and that point was also an increase,
                # eliminate the previous (intermediate) point.
                (t1, prior_y) = stats.memory_footprint_samples[-2]
                (t2, last_y) = stats.memory_footprint_samples[-1]
                y = stats.current_footprint
                if prior_y < last_y < y or prior_y > last_y > y:
                    # Same direction.
                    # Replace the previous (intermediate) point.
                    stats.memory_footprint_samples[-1] = [timestamp, y]
                else:
                    stats.memory_footprint_samples.append([timestamp, y])
            else:
                stats.memory_footprint_samples.append(
                    [
                        timestamp,
                        stats.current_footprint,
                    ]
                )
        after = stats.current_footprint

        if freed_last_trigger:
            if freed_last_trigger <= 1:
                # We freed the last allocation trigger. Adjust scores.
                this_fn, this_ln, _this_ptr = stats.last_malloc_triggered
                if this_ln != 0:
                    mallocs, frees = stats.leak_score[this_fn][this_ln]
                    stats.leak_score[this_fn][this_ln] = (
                        mallocs,
                        frees + 1,
                    )
            stats.last_malloc_triggered = (
                Filename(""),
                LineNumber(0),
                Address("0x0"),
            )

        allocs = 0.0
        last_malloc = (Filename(""), LineNumber(0), Address("0x0"))
        malloc_pointer = "0x0"
        curr = before

        # Go through the array again and add each updated current footprint.
        for item in arr:
            (
                _alloc_time,
                action,
                count,
                python_fraction,
                pointer,
                fname,
                lineno,
                bytei,
            ) = item

            is_malloc = action == Scalene.MALLOC_ACTION
            if is_malloc and count == NEWLINE_TRIGGER_LENGTH + 1:
                last_file, last_line = Scalene.__invalidate_queue.pop(0)
                print(last_file, last_line)
                stats.memory_malloc_count[last_file][last_line] += 1
                stats.memory_aggregate_footprint[last_file][
                    last_line
                ] += stats.memory_current_highwater_mark[last_file][last_line]

                stats.memory_current_footprint[last_file][last_line] = 0
                stats.memory_current_highwater_mark[last_file][last_line] = 0
                continue

            # Add the byte index to the set for this line (if it's not there already).
            stats.bytei_map[fname][lineno].add(bytei)
            count /= Scalene.BYTES_PER_MB
            if is_malloc:
                allocs += count
                curr += count
                malloc_pointer = pointer
                stats.memory_malloc_samples[fname][lineno] += count
                stats.memory_python_samples[fname][lineno] += (
                    python_fraction * count
                )
                stats.malloc_samples[fname] += 1
                stats.total_memory_malloc_samples += count
                # Update current and max footprints for this file & line.
                stats.memory_current_footprint[fname][lineno] += count
                if (
                    stats.memory_current_footprint[fname][lineno]
                    > stats.memory_current_highwater_mark[fname][lineno]
                ):
                    stats.memory_current_highwater_mark[fname][
                        lineno
                    ] = stats.memory_current_footprint[fname][lineno]
                stats.memory_current_highwater_mark[fname][lineno] = max(
                    stats.memory_current_highwater_mark[fname][lineno],
                    stats.memory_current_footprint[fname][lineno],
                )
                stats.memory_max_footprint[fname][lineno] = max(
                    stats.memory_current_footprint[fname][lineno],
                    stats.memory_max_footprint[fname][lineno],
                )
            else:
                assert action in [
                    Scalene.FREE_ACTION,
                    Scalene.FREE_ACTION_SAMPLED,
                ]
                curr -= count
                stats.memory_free_samples[fname][lineno] += count
                stats.memory_free_count[fname][lineno] += 1
                stats.total_memory_free_samples += count
                stats.memory_current_footprint[fname][lineno] -= count
                # Ensure that we never drop the current footprint below 0.
                stats.memory_current_footprint[fname][lineno] = max(
                    0, stats.memory_current_footprint[fname][lineno]
                )

            stats.per_line_footprint_samples[fname][lineno].append(
                [time.monotonic_ns() - Scalene.__start_time, curr]
            )
            # If we allocated anything, then mark this as the last triggering malloc
            if allocs > 0:
                last_malloc = (
                    Filename(fname),
                    LineNumber(lineno),
                    Address(malloc_pointer),
                )
        stats.allocation_velocity = (
            stats.allocation_velocity[0] + (after - before),
            stats.allocation_velocity[1] + allocs,
        )
        if (
            Scalene.__args.memory_leak_detector
            and prevmax < stats.max_footprint
            and stats.max_footprint > 100
        ):
            stats.last_malloc_triggered = last_malloc
            fname, lineno, _ = last_malloc
            mallocs, frees = stats.leak_score[fname][lineno]
            stats.leak_score[fname][lineno] = (mallocs + 1, frees)

    @staticmethod
    def before_fork() -> None:
        """The parent process should invoke this function just before a fork.

        Invoked by replacement_fork.py.
        """
        Scalene.stop_signal_queues()

    @staticmethod
    def after_fork_in_parent(child_pid: int) -> None:
        """The parent process should invoke this function after a fork.

        Invoked by replacement_fork.py.
        """
        Scalene.add_child_pid(child_pid)
        Scalene.start_signal_queues()

    @staticmethod
    def after_fork_in_child() -> None:
        """
        Executed by a child process after a fork; mutates the
        current profiler into a child.

        Invoked by replacement_fork.py.
        """
        Scalene.__is_child = True

        Scalene.clear_metrics()
        if Scalene.__gpu.has_gpu():
            Scalene.__gpu.nvml_reinit()
        # Note: __parent_pid of the topmost process is its own pid.
        Scalene.__pid = Scalene.__parent_pid
        if "off" not in Scalene.__args or not Scalene.__args.off:
            Scalene.enable_signals()

    @staticmethod
    def memcpy_sigqueue_processor(
        _signum: Union[
            Callable[[signal.Signals, FrameType], None],
            int,
            signal.Handlers,
            None,
        ],
        frame: FrameType,
    ) -> None:
        """Process memcpy signals (used in a ScaleneSigQueue)."""
        curr_pid = os.getpid()
        arr: List[Tuple[str, int, int, int, int]] = []
        # Process the input array.
        with contextlib.suppress(ValueError):
            while Scalene.__memcpy_mapfile.read():
                count_str = Scalene.__memcpy_mapfile.get_str()
                (
                    memcpy_time_str,
                    count_str2,
                    pid,
                    filename,
                    lineno,
                    bytei,
                ) = count_str.split(",")
                if int(curr_pid) != int(pid):
                    continue
                arr.append(
                    (
                        filename,
                        int(lineno),
                        int(bytei),
                        int(memcpy_time_str),
                        int(count_str2),
                    )
                )
        arr.sort()

        for item in arr:
            filename, linenum, byteindex, _memcpy_time, count = item
            fname = Filename(filename)
            line_no = LineNumber(linenum)
            byteidx = ByteCodeIndex(byteindex)
            # Add the byte index to the set for this line.
            Scalene.__stats.bytei_map[fname][line_no].add(byteidx)
            Scalene.__stats.memcpy_samples[fname][line_no] += int(count)

    @staticmethod
    @functools.lru_cache(None)
    def should_trace(filename: str) -> bool:
        """Return true if the filename is one we should trace."""
        if not filename:
            return False
        if (
            "scalene/scalene" in filename
        ):  # lgtm [py/member-test-non-container]
            # Don't profile the profiler.
            return False
        if (
            "site-packages" in filename
            or "/lib/python" in filename  # lgtm [py/member-test-non-container]
        ) and not Scalene.__args.profile_all:
            return False
        # Generic handling follows (when no @profile decorator has been used).
        profile_exclude_list = Scalene.__args.profile_exclude.split(",")
        if any(
            prof in filename for prof in profile_exclude_list if prof != ""
        ):
            return False
        if filename[0] == "<":
            if (
                "<ipython" not in filename
            ):  # lgtm [py/member-test-non-container]
                # Not a real file and not a function created in Jupyter.
                return False
            # Profiling code created in a Jupyter cell:
            # create a file to hold the contents.
            import IPython

            if result := re.match("<ipython-input-([0-9]+)-.*>", filename):
                # Write the cell's contents into the file.
                with open(filename, "w+") as f:
                    f.write(
                        IPython.get_ipython().history_manager.input_hist_raw[
                            int(result[1])
                        ]
                    )
            return True
        # If (a) `profile-only` was used, and (b) the file matched
        # NONE of the provided patterns, don't profile it.
        profile_only_set = set(Scalene.__args.profile_only.split(","))
        if not_found_in_profile_only := profile_only_set and all(
            prof not in filename for prof in profile_only_set
        ):
            return False
        # Now we've filtered out any non matches to profile-only patterns.
        # If `profile-all` is specified, profile this file.
        if Scalene.__args.profile_all:
            return True
        # Profile anything in the program's directory or a child directory,
        # but nothing else, unless otherwise specified.
        filename = os.path.normpath(
            os.path.join(Scalene.__program_path, filename)
        )
        return Scalene.__program_path in filename

    __done = False

    @staticmethod
    def start() -> None:
        """Initiate profiling."""
        if not Scalene.__initialized:
            print(
                "ERROR: Do not try to invoke `start` when you have not called Scalene using one of the methods "
                "in https://github.com/plasma-umass/scalene#using-scalene"
            )
            sys.exit(1)
        Scalene.__stats.start_clock()
        Scalene.enable_signals()
        Scalene.__start_time = time.monotonic_ns()
        Scalene.__done = False

    @staticmethod
    def stop() -> None:
        """Complete profiling."""
        Scalene.__done = True
        Scalene.disable_signals()
        Scalene.__stats.stop_clock()
        if (
            Scalene.__args.web
            and not Scalene.__args.cli
            and not Scalene.__is_child
        ):
            if Scalene.in_jupyter():
                # Force JSON output to profile.json.
                Scalene.__args.json = True
                Scalene.__output.html = False
                Scalene.__output.output_file = Scalene.__profile_filename
                return
            # Check for a browser.
            try:
                if (
                    not webbrowser.get()
                    or type(webbrowser.get()).__name__ == "GenericBrowser"
                ):
                    # Could not open a graphical web browser tab;
                    # act as if --web was not specified
                    # (GenericBrowser means text-based browsers like Lynx.)
                    Scalene.__args.web = False
                else:
                    # Force JSON output to profile.json.
                    Scalene.__args.json = True
                    Scalene.__output.html = False
                    Scalene.__output.output_file = Scalene.__profile_filename
            except Exception:
                # Couldn't find a browser.
                Scalene.__args.web = False

    @staticmethod
    def is_done() -> bool:
        """Return true if Scalene has stopped profiling."""
        return Scalene.__done

    @staticmethod
    def start_signal_handler(
        _signum: Union[
            Callable[[signal.Signals, FrameType], None],
            int,
            signal.Handlers,
            None,
        ],
        _this_frame: Optional[FrameType],
    ) -> None:
        """Respond to a signal to start or resume profiling (--on).

        See scalene_parseargs.py.
        """
        for pid in Scalene.child_pids:
            Scalene.__orig_kill(pid, Scalene.__signals.start_profiling_signal)
        Scalene.start()

    @staticmethod
    def stop_signal_handler(
        _signum: Union[
            Callable[[signal.Signals, FrameType], None],
            int,
            signal.Handlers,
            None,
        ],
        _this_frame: Optional[FrameType],
    ) -> None:
        """Respond to a signal to suspend profiling (--off).

        See scalene_parseargs.py.
        """
        for pid in Scalene.child_pids:
            Scalene.__orig_kill(pid, Scalene.__signals.stop_profiling_signal)
        Scalene.stop()

    @staticmethod
    def disable_signals(retry: bool = True) -> None:
        """Turn off the profiling signals."""
        if sys.platform == "win32":
            Scalene.timer_signals = False
            return
        try:
            Scalene.__orig_setitimer(Scalene.__signals.cpu_timer_signal, 0)
            Scalene.__orig_signal(
                Scalene.__signals.malloc_signal, signal.SIG_IGN
            )
            Scalene.__orig_signal(
                Scalene.__signals.free_signal, signal.SIG_IGN
            )
            Scalene.__orig_signal(
                Scalene.__signals.memcpy_signal, signal.SIG_IGN
            )
            Scalene.stop_signal_queues()
        except Exception:
            # Retry just in case we get interrupted by one of our own signals.
            if retry:
                Scalene.disable_signals(retry=False)

    @staticmethod
    def exit_handler() -> None:
        """When we exit, disable all signals."""
        Scalene.disable_signals()
        # Delete the temporary directory.
        with contextlib.suppress(Exception):
            if not Scalene.__pid:
                Scalene.__python_alias_dir.cleanup()  # type: ignore
        with contextlib.suppress(Exception):
            os.remove(f"/tmp/scalene-malloc-lock{os.getpid()}")

    def profile_code(
        self,
        code: str,
        the_globals: Dict[str, str],
        the_locals: Dict[str, str],
    ) -> int:
        """Initiate execution and profiling."""
        # If --off is set, tell all children to not profile and stop profiling before we even start.
        if "off" not in Scalene.__args or not Scalene.__args.off:
            self.start()
        # Run the code being profiled.
        exit_status = 0
        try:
            exec(code, the_globals, the_locals)
        except SystemExit as se:
            # Intercept sys.exit and propagate the error code.
            exit_status = se.code
        except KeyboardInterrupt:
            # Cleanly handle keyboard interrupts (quits execution and dumps the profile).
            print("Scalene execution interrupted.")
        except Exception as e:
            print(f"{Scalene.__error_message}:\n", e)
            traceback.print_exc()
            exit_status = 1
        finally:
            self.stop()
            sys.settrace(None)
            # If we've collected any samples, dump them.
            did_output = Scalene.output_profile()
            if not did_output:
                print(
                    "Scalene: Program did not run for long enough to profile."
                )

            if not (
                did_output
                and Scalene.__args.web
                and not Scalene.__args.cli
                and not Scalene.__is_child
            ):
                return exit_status

            # Start up a web server (in a background thread) to host the GUI,
            # and open a browser tab to the server. If this fails, fail-over
            # to using the CLI.

            try:
                PORT = Scalene.__args.port

                # Silence web server output by overriding logging messages.
                class NoLogs(http.server.SimpleHTTPRequestHandler):
                    def log_message(
                        self, format: str, *args: List[Any]
                    ) -> None:
                        return

                    def log_request(
                        self,
                        code: Union[int, str] = 0,
                        size: Union[int, str] = 0,
                    ) -> None:
                        return

                Handler = NoLogs
                socketserver.TCPServer.allow_reuse_address = True
                with socketserver.TCPServer(("", PORT), Handler) as httpd:
                    t = threading.Thread(target=httpd.serve_forever)
                    # Copy files into a new directory and then point the tab there.
                    import shutil

                    webgui_dir = pathlib.Path(
                        tempfile.mkdtemp(prefix=Scalene.__gui_dir)
                    )
                    shutil.copytree(
                        os.path.join(
                            os.path.dirname(__file__), Scalene.__gui_dir
                        ),
                        os.path.join(webgui_dir, Scalene.__gui_dir),
                    )
                    shutil.copy(
                        Scalene.__profile_filename,
                        os.path.join(webgui_dir, Scalene.__gui_dir),
                    )
                    os.chdir(os.path.join(webgui_dir, Scalene.__gui_dir))
                    t.start()
                    if Scalene.in_jupyter():
                        from IPython.core.display import HTML, display
                        from IPython.display import IFrame

                        display(
                            IFrame(
                                src=f"{Scalene.__localhost}:{PORT}/{Scalene.__profiler_html}",
                                width=700,
                                height=600,
                            )
                        )
                    else:
                        # Disable the preload environment
                        # variables which are no longer needed
                        # anyway (for memory/copy volume tracking)
                        # and which interfere with at least one
                        # browser on one platform.
                        os.environ["LD_PRELOAD"] = ""
                        os.environ["DYLD_INSERT_LIBRARIES"] = ""
                        # Now open a tab with the profiler.
                        webbrowser.open(
                            f"{Scalene.__localhost}:{PORT}/{Scalene.__profiler_html}"
                        )
                    # Wait long enough for the server to serve the page, and then shut down the server.
                    time.sleep(5)
                    httpd.shutdown()
            except OSError:
                print(
                    f"Scalene: unable to run the Scalene GUI on port {PORT}."
                )
                print("Possible solutions:")
                print("(1) Use a different port (with --port)")
                print("(2) Use the text version (with --cli)")
                print(
                    "(3) Upload a generated profile.json file to the web GUI: https://plasma-umass.org/scalene-gui/."
                )

        return exit_status

    @staticmethod
    def process_args(args: argparse.Namespace) -> None:
        """Process all arguments."""
        Scalene.__args = cast(ScaleneArguments, args)
        Scalene.__next_output_time = (
            time.perf_counter() + Scalene.__args.profile_interval
        )
        Scalene.__output.html = args.html
        Scalene.__output.output_file = args.outfile
        Scalene.__is_child = args.pid != 0
        # the pid of the primary profiler
        Scalene.__parent_pid = args.pid if Scalene.__is_child else os.getpid()

    @staticmethod
    def set_initialized() -> None:
        """Indicate that Scalene has been initialized and is ready to begin profiling."""
        Scalene.__initialized = True

    @staticmethod
    def main() -> None:
        """Initialize and profile."""
        (
            args,
            left,
        ) = ScaleneParseArgs.parse_args()
        Scalene.set_initialized()
        Scalene.run_profiler(args, left)

    @staticmethod
    def run_profiler(
        args: argparse.Namespace, left: List[str], is_jupyter: bool = False
    ) -> None:
        """Set up and initiate profiling."""
        # Set up signal handlers for starting and stopping profiling.
        if is_jupyter:
            Scalene.set_in_jupyter()
        if not Scalene.__initialized:
            print(
                "ERROR: Do not try to manually invoke `run_profiler`.\n"
                "To invoke Scalene programmatically, see the usage noted in https://github.com/plasma-umass/scalene#using-scalene"
            )
            sys.exit(1)
        Scalene.__orig_signal(
            Scalene.__signals.start_profiling_signal,
            Scalene.start_signal_handler,
        )
        Scalene.__orig_signal(
            Scalene.__signals.stop_profiling_signal,
            Scalene.stop_signal_handler,
        )
        if sys.platform != "win32":
            Scalene.__orig_siginterrupt(
                Scalene.__signals.start_profiling_signal, False
            )
            Scalene.__orig_siginterrupt(
                Scalene.__signals.stop_profiling_signal, False
            )

        Scalene.__orig_signal(signal.SIGINT, Scalene.interruption_handler)
        did_preload = (
            False if is_jupyter else ScalenePreload.setup_preload(args)
        )
        if not did_preload:
            with contextlib.suppress(Exception):
                # If running in the background, print the PID.
                if os.getpgrp() != os.tcgetpgrp(sys.stdout.fileno()):
                    # In the background.
                    print(f"Scalene now profiling process {os.getpid()}")
                    print(
                        f"  to disable profiling: python3 -m scalene.profile --off --pid {os.getpid()}"
                    )
                    print(
                        f"  to resume profiling:  python3 -m scalene.profile --on  --pid {os.getpid()}"
                    )
        Scalene.__stats.clear_all()
        sys.argv = left
        with contextlib.suppress(Exception):
            if not is_jupyter:
                multiprocessing.set_start_method("fork")
        try:
            Scalene.process_args(args)
            progs = None
            exit_status = 0
            try:
                # Look for something ending in '.py'. Treat the first one as our executable.
                progs = [x for x in sys.argv if re.match(".*\.py$", x)]
                # Just in case that didn't work, try sys.argv[0] and __file__.
                with contextlib.suppress(Exception):
                    progs.extend((sys.argv[0], __file__))
                if not progs:
                    raise FileNotFoundError
                with open(progs[0], "rb") as prog_being_profiled:
                    # Read in the code and compile it.
                    code: Any
                    try:
                        code = compile(
                            prog_being_profiled.read(),
                            progs[0],
                            "exec",
                        )
                    except SyntaxError:
                        traceback.print_exc()
                        sys.exit(1)
                    # Push the program's path.
                    program_path = os.path.dirname(os.path.abspath(progs[0]))
                    sys.path.insert(0, program_path)
                    # If a program path was specified at the command-line, use it.
                    if len(args.program_path) > 0:
                        Scalene.__program_path = os.path.abspath(
                            args.program_path
                        )
                    else:
                        # Otherwise, use the invoked directory.
                        Scalene.__program_path = os.getcwd()
                    # Grab local and global variables.
                    if not Scalene.__args.cpu_only:
                        from scalene import pywhere  # type: ignore

                        pywhere.register_files_to_profile(
                            list(Scalene.__files_to_profile),
                            Scalene.__program_path,
                            Scalene.__args.profile_all,
                        )

                    import __main__

                    the_locals = __main__.__dict__
                    the_globals = __main__.__dict__
                    # Splice in the name of the file being executed instead of the profiler.
                    the_globals["__file__"] = os.path.abspath(progs[0])
                    # Some mysterious module foo to make this work the same with -m as with `scalene`.
                    the_globals["__spec__"] = None
                    # Do a GC before we start.
                    gc.collect()
                    # Start the profiler.
                    profiler = Scalene(args, Filename(progs[0]))
                    try:
                        # We exit with this status (returning error code as appropriate).
                        exit_status = profiler.profile_code(
                            code, the_locals, the_globals
                        )
                        sys.exit(exit_status)
                    except StopJupyterExecution:
                        # Running in Jupyter notebooks
                        pass
                    except AttributeError:
                        # don't let the handler below mask programming errors
                        raise
                    except Exception as ex:
                        template = "Scalene: An exception of type {0} occurred. Arguments:\n{1!r}"
                        message = template.format(type(ex).__name__, ex.args)
                        print(message)
                        print(traceback.format_exc())
            except (FileNotFoundError, IOError):
                if progs:
                    print(f"Scalene: could not find input file {progs[0]}")
                else:
                    print("Scalene: no input file specified.")
                sys.exit(1)
        except SystemExit:
            pass
        except StopJupyterExecution:
            pass
        except Exception:
            print("Scalene failed to initialize.\n" + traceback.format_exc())
            sys.exit(1)
        finally:
            with contextlib.suppress(Exception):
                Scalene.__malloc_mapfile.close()
                Scalene.__memcpy_mapfile.close()
                if not Scalene.__is_child:
                    # We are done with these files, so remove them.
                    Scalene.__malloc_mapfile.cleanup()
                    Scalene.__memcpy_mapfile.cleanup()
            sys.exit(exit_status)


if __name__ == "__main__":
    Scalene.main()
