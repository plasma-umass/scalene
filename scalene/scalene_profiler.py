from __future__ import annotations # work around Python 3.8 issue, see https://stackoverflow.com/a/68072481/335756

"""Scalene: a CPU+memory+GPU (and more) profiler for Python.

    https://github.com/plasma-umass/scalene

    See the paper "docs/osdi23-berger.pdf" in this repository for technical
    details on Scalene's design.

    by Emery Berger, Sam Stern, and Juan Altmayer Pizzorno

    usage: scalene test/testme.py
    usage help: scalene --help

"""

# Import cysignals early so it doesn't disrupt Scalene's use of signals; this allows Scalene to profile Sage.
# See https://github.com/plasma-umass/scalene/issues/740.
try:
    import cysignals  # type: ignore
except ModuleNotFoundError:
    pass

import argparse
import atexit
import builtins
import contextlib
import functools
import gc
import importlib
import inspect
import json
import math
import multiprocessing
import os
import pathlib
import platform
import queue
import re
import signal
import stat
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
import traceback
import webbrowser

# For debugging purposes
from rich.console import Console

from scalene.find_browser import find_browser
from scalene.get_module_details import _get_module_details
from scalene.time_info import get_times, TimeInfo
from scalene.redirect_python import redirect_python

from collections import defaultdict
from dataclasses import dataclass
from importlib.abc import SourceLoader
from importlib.machinery import ModuleSpec
from types import CodeType, FrameType
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
    cast,
)

import scalene.scalene_config
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
from scalene.scalene_utility import *

if sys.platform != "win32":
    import resource

if platform.system() == "Darwin":
    from scalene.scalene_apple_gpu import ScaleneAppleGPU as ScaleneGPU
else:
    from scalene.scalene_gpu import ScaleneGPU  # type: ignore

from scalene.scalene_parseargs import ScaleneParseArgs, StopJupyterExecution
from scalene.scalene_sigqueue import ScaleneSigQueue

console = Console(style="white on blue")
# Assigning to `nada` disables any console.log commands.
def nada(*args: Any) -> None:
    pass


console.log = nada  # type: ignore

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

def start() -> None:
    """Start profiling."""
    Scalene.start()


def stop() -> None:
    """Stop profiling."""
    Scalene.stop()


class Scalene:
    """The Scalene profiler itself."""

    # Get the number of available CPUs (preferring `os.sched_getaffinity`, if available).
    __availableCPUs: int
    try:
        __availableCPUs = len(os.sched_getaffinity(0))  # type: ignore
    except AttributeError:
        cpu_count = os.cpu_count()
        __availableCPUs = cpu_count if cpu_count else 1

    __in_jupyter = False  # are we running inside a Jupyter notebook
    __start_time = 0  # start of profiling, in nanoseconds
    __sigterm_exit_code = 143
    # Whether the current profiler is a child
    __is_child = -1
    # the pid of the primary profiler
    __parent_pid = -1
    __initialized: bool = False
    __last_profiled = [Filename("NADA"), LineNumber(0), ByteCodeIndex(0)]
    __orig_python = sys.executable # will be rewritten later
    @staticmethod
    def last_profiled_tuple() -> Tuple[Filename, LineNumber, ByteCodeIndex]:
        """Helper function to type last profiled information."""
        return cast(
            Tuple[Filename, LineNumber, ByteCodeIndex], Scalene.__last_profiled
        )

    __last_profiled_invalidated = False
    __gui_dir = "scalene-gui"
    __profile_filename = Filename("profile.json")
    __profiler_html = Filename("profile.html")
    __error_message = "Error in program being profiled"
    __windows_queue: queue.Queue[
        Any
    ] = queue.Queue()  # only used for Windows timer logic
    BYTES_PER_MB = 1024 * 1024

    MALLOC_ACTION = "M"
    FREE_ACTION = "F"
    FREE_ACTION_SAMPLED = "f"

    # Support for @profile
    # decorated files
    __files_to_profile: Set[Filename] = set()
    # decorated functions
    __functions_to_profile: Dict[Filename, Set[Any]] = defaultdict(set)

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
    __profiler_base: str

    @staticmethod
    def get_original_lock() -> threading.Lock:
        """Return the true lock, which we shim in replacement_lock.py."""
        return Scalene.__original_lock()
    @staticmethod
    def get_signals():
        return Scalene.__signals
    # when did we last receive a signal?
    __last_signal_time = TimeInfo()

    # path for the program being profiled
    __program_path = Filename("")
    __entrypoint_dir = Filename("")
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
    __lifecycle_disabled = False

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
    def get_lifecycle_signals() -> Tuple[signal.Signals, signal.Signals]:
        return Scalene.__signals.get_lifecycle_signals()

    @staticmethod
    def disable_lifecycle():
        Scalene.__lifecycle_disabled = True
    @staticmethod
    def get_lifecycle_disabled() -> bool:
        return Scalene.__lifecycle_disabled

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
    def update_line() -> None:
        """Mark a new line by allocating the trigger number of bytes."""
        bytearray(scalene.scalene_config.NEWLINE_TRIGGER_LENGTH)

    @staticmethod
    def update_profiled() -> None:
        with Scalene.__invalidate_mutex:
            last_prof_tuple = Scalene.last_profiled_tuple()
            Scalene.__invalidate_queue.append(
                (last_prof_tuple[0], last_prof_tuple[1])
            )
            Scalene.update_line()

    @staticmethod
    def invalidate_lines_python(
        frame: FrameType, _event: str, _arg: str
    ) -> Any:
        """Mark the last_profiled information as invalid as soon as we execute a different line of code."""
        try:
            # If we are still on the same line, return.
            ff = frame.f_code.co_filename
            fl = frame.f_lineno
            (fname, lineno, lasti) = Scalene.last_profiled_tuple()
            if (ff == fname) and (fl == lineno):
                return Scalene.invalidate_lines_python
            # Different line: stop tracing this frame.
            frame.f_trace = None
            frame.f_trace_lines = False
            if on_stack(frame, fname, lineno):
                # We are still on the same line, but somewhere up the stack
                # (since we returned when it was the same line in this
                # frame). Stop tracing in this frame.
                return None
            # We are on a different line; stop tracing and increment the count.
            sys.settrace(None)
            Scalene.update_profiled()
            Scalene.__last_profiled_invalidated = True

            Scalene.__last_profiled = [
                Filename("NADA"),
                LineNumber(0),
                ByteCodeIndex(0)
                #     Filename(ff),
                #     LineNumber(fl),
                #     ByteCodeIndex(frame.f_lasti),
            ]
            return None
        except AttributeError:
            # This can happen when Scalene shuts down.
            return None
        except Exception as e:
            print(f"{Scalene.__error_message}:\n", e, file=sys.stderr)
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

        if Scalene.__args.memory:
            Scalene.register_files_to_profile()
        return func

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
        assert sys.platform == "win32"
        Scalene.timer_signals = True
        while Scalene.timer_signals:
            Scalene.__windows_queue.get()
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
        if not Scalene.__args.memory:
            # This should never happen, but we fail gracefully.
            return
        from scalene import pywhere  # type: ignore

        if this_frame:
            Scalene.enter_function_meta(this_frame, Scalene.__stats)
        # Walk the stack till we find a line of code in a file we are tracing.
        found_frame = False
        f = this_frame
        while f:
            if found_frame := Scalene.should_trace(
                f.f_code.co_filename, f.f_code.co_name
            ):
                break
            f = cast(FrameType, f.f_back)
        if not found_frame:
            return
        assert f
        # Start tracing until we execute a different line of
        # code in a file we are tracking.
        # First, see if we have now executed a different line of code.
        # If so, increment.
        invalidated = pywhere.get_last_profiled_invalidated()
        (fname, lineno, lasti) = Scalene.last_profiled_tuple()
        if (
            not invalidated
            and this_frame
            and not (on_stack(this_frame, fname, lineno))
        ):
            Scalene.update_profiled()
        pywhere.set_last_profiled_invalidated_false()
        Scalene.__last_profiled = [
            Filename(f.f_code.co_filename),
            LineNumber(f.f_lineno),
            ByteCodeIndex(f.f_lasti),
        ]
        Scalene.__alloc_sigq.put([0])
        pywhere.enable_settrace()
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
    def enable_signals_win32() -> None:
        assert sys.platform == "win32"
        Scalene.timer_signals = True
        Scalene.__orig_signal(
            Scalene.__signals.cpu_signal,
            Scalene.cpu_signal_handler,
        )
        # On Windows, we simulate timer signals by running a background thread.
        Scalene.timer_signals = True
        t = threading.Thread(target=Scalene.windows_timer_loop)
        t.start()
        Scalene.__windows_queue.put(None)
        Scalene.start_signal_queues()
        return

    @staticmethod
    def enable_signals() -> None:
        """Set up the signal handlers to handle interrupts for profiling and start the
        timer interrupts."""
        if sys.platform == "win32":
            Scalene.enable_signals_win32()
            return
        Scalene.start_signal_queues()
        # Set signal handlers for various events.
        for sig, handler in [
            (Scalene.__signals.malloc_signal, Scalene.malloc_signal_handler),
            (Scalene.__signals.free_signal, Scalene.free_signal_handler),
            (Scalene.__signals.memcpy_signal, Scalene.memcpy_signal_handler),
            (signal.SIGTERM, Scalene.term_signal_handler),
            (Scalene.__signals.cpu_signal, Scalene.cpu_signal_handler),
        ]:
            Scalene.__orig_signal(sig, handler)
        # Set every signal to restart interrupted system calls.
        for s in Scalene.__signals.get_all_signals():
            Scalene.__orig_siginterrupt(s, False)
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

        Scalene.__windows_queue = queue.Queue()
        if sys.platform == "win32":
            if arguments.memory:
                print(
                    f"Scalene warning: Memory profiling is not currently supported for Windows.", file=sys.stderr
                )
                arguments.memory = False

        # Initialize the malloc related files; if for whatever reason
        # the files don't exist and we are supposed to be profiling
        # memory, exit.
        try:
            Scalene.__malloc_mapfile = ScaleneMapFile("malloc")
            Scalene.__memcpy_mapfile = ScaleneMapFile("memcpy")
        except Exception:
            # Ignore if we aren't profiling memory; otherwise, exit.
            if arguments.memory:
                sys.exit(1)

        Scalene.__signals.set_timer_signals(arguments.use_virtual_time)
        Scalene.__profiler_base = str(os.path.dirname(__file__))
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
            # Create a temporary directory to hold aliases to the Python
            # executable, so scalene can handle multiple processes; each
            # one is a shell script that redirects to Scalene.
            Scalene.__python_alias_dir = pathlib.Path(
                tempfile.mkdtemp(prefix="scalene")
            )
            Scalene.__pid = 0
            cmdline = ""
            # Pass along commands from the invoking command line.
            if "off" in arguments and arguments.off:
                cmdline += " --off"
            for arg in [
                "use_virtual_time",
                "cpu",
                "gpu",
                "memory",
                "cli",
                "web",
                "html",
                "no_browser",
                "reduced_profile",
            ]:
                if getattr(arguments, arg):
                    cmdline += f'  --{arg.replace("_", "-")}'
            # Add the --pid field so we can propagate it to the child.
            cmdline += f" --pid={os.getpid()} ---"
            # Build the commands to pass along other arguments
            environ = ScalenePreload.get_preload_environ(arguments)
            if sys.platform == "win32":
                preface = "\n".join(
                    f"set {k}={str(v)}\n" for (k, v) in environ.items()
                )
            else:
                preface = " ".join(
                    "=".join((k, str(v))) for (k, v) in environ.items()
                )

            Scalene.__orig_python = redirect_python(preface, cmdline, Scalene.__python_alias_dir)

        # Register the exit handler to run when the program terminates or we quit.
        atexit.register(Scalene.exit_handler)
        # Store relevant names (program, path).
        if program_being_profiled:
            Scalene.__program_being_profiled = Filename(program_being_profiled)

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
        try:
            # Get current time stats.
            now_sys, now_user = get_times()
            now_virtual = time.process_time()
            now_wallclock = time.perf_counter()
            if (
                Scalene.__last_signal_time.virtual == 0
                or Scalene.__last_signal_time.wallclock == 0
            ):
                # Initialization: store values and update on the next pass.
                Scalene.__last_signal_time.virtual = now_virtual
                Scalene.__last_signal_time.wallclock = now_wallclock
                Scalene.__last_signal_time.sys = now_sys
                Scalene.__last_signal_time.user = now_user
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
                Scalene.__last_signal_time.virtual,
                Scalene.__last_signal_time.wallclock,
                Scalene.__last_signal_time.sys,
                Scalene.__last_signal_time.user,
                Scalene.__is_thread_sleeping,
            )
            elapsed = now_wallclock - Scalene.__last_signal_time.wallclock
            # Store the latest values as the previously recorded values.
            Scalene.__last_signal_time.virtual = now_virtual
            Scalene.__last_signal_time.wallclock = now_wallclock
            Scalene.__last_signal_time.sys = now_sys
            Scalene.__last_signal_time.user = now_user
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
        finally:
            if sys.platform == "win32":
                Scalene.__windows_queue.put(None)

    @staticmethod
    def output_profile(program_args: Optional[List[str]] = None) -> bool:
        """Output the profile. Returns true iff there was any info reported the profile."""
        # sourcery skip: inline-immediately-returned-variable
        # print(flamegraph_format(Scalene.__stats.stacks))       
        if Scalene.__args.json:
            json_output = Scalene.__json.output_profiles(
                Scalene.__program_being_profiled,
                Scalene.__stats,
                Scalene.__pid,
                Scalene.profile_this_code,
                Scalene.__python_alias_dir,
                Scalene.__program_path,
                Scalene.__entrypoint_dir,
                program_args,
                profile_memory=Scalene.__args.memory,
                reduced_profile=Scalene.__args.reduced_profile,
            )
            # Since the default value returned for "there are no samples"
            # is `{}`, we use a sentinel value `{"is_child": True}`
            # when inside a child process to indicate that there are samples, but they weren't
            # turned into a JSON file because they'll later
            # be used by the parent process
            if "is_child" in json_output:
                return True
            outfile = Scalene.__output.output_file
            # If there was no output file specified, print to the console.
            if not outfile:
                if sys.platform == "win32":
                    outfile = "CON"
                else:
                    outfile = "/dev/stdout"
            # Write the JSON to the output file (or console).
            with open(outfile, "w") as f:
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
                program_args,
                profile_memory=Scalene.__args.memory,
                reduced_profile=Scalene.__args.reduced_profile,
            )
            return did_output

    @staticmethod
    @functools.lru_cache(None)
    def get_line_info(
        fname: Filename,
    ) -> Generator[Tuple[list[str], int], None, None]:
        line_info = (
            inspect.getsourcelines(fn)
            for fn in Scalene.__functions_to_profile[fname]
        )
        return line_info

    @staticmethod
    def profile_this_code(fname: Filename, lineno: LineNumber) -> bool:
        # sourcery skip: inline-immediately-returned-variable
        """When using @profile, only profile files & lines that have been decorated."""
        if not Scalene.__files_to_profile:
            return True
        if fname not in Scalene.__files_to_profile:
            return False
        # Now check to see if it's the right line range.
        line_info = Scalene.get_line_info(fname)
        found_function = any(
            line_start <= lineno < line_start + len(lines)
            for (lines, line_start) in line_info
        )
        return found_function

    @staticmethod
    def print_stacks() -> None:
        print(Scalene.__stats.stacks)

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
        if any([elapsed_virtual < 0, elapsed_wallclock < 0, elapsed_user < 0]):
            # If we get negative values, which appear to arise in some
            # multi-process settings (seen in gunicorn), skip this
            # sample.
            return
        cpu_utilization = 0.0
        if elapsed_wallclock != 0:
            cpu_utilization = elapsed_user / elapsed_wallclock
        # On multicore systems running multi-threaded native code, CPU
        # utilization can exceed 1; that is, elapsed user time is
        # longer than elapsed wallclock time. If this occurs, set
        # wall clock time to user time and set CPU utilization to 100%.
        core_utilization = cpu_utilization / Scalene.__availableCPUs
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

        if Scalene.__args.stacks:
            add_stack(
                main_thread_frame,
                Scalene.should_trace,
                Scalene.__stats.stacks,
                average_python_time,
                average_c_time,
                average_cpu_time
            )

        # First, handle the main thread.
        Scalene.enter_function_meta(main_thread_frame, Scalene.__stats)
        fname = Filename(main_thread_frame.f_code.co_filename)
        lineno = LineNumber(main_thread_frame.f_lineno)
        #print(main_thread_frame)
        #print(fname, lineno)
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
            Scalene.__stats.core_utilization[fname][lineno].push(
                core_utilization
            )
            Scalene.__stats.gpu_samples[fname][lineno] += average_gpu_time
            Scalene.__stats.gpu_mem_samples[fname][lineno].push(gpu_mem_used)

        # Now handle the rest of the threads.
        for (frame, tident, orig_frame) in new_frames:
            if frame == main_thread_frame:
                continue
            add_stack(frame,
                      Scalene.should_trace,
                      Scalene.__stats.stacks,
                      average_python_time,
                      average_c_time,
                      average_cpu_time)

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
            Scalene.__stats.core_utilization[fname][lineno].push(
                core_utilization
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
            func = frame.f_code.co_name
            # Record samples only for files we care about.
            if not fname:
                # 'eval/compile' gives no f_code.co_filename.  We have
                # to look back into the outer frame in order to check
                # the co_filename.
                back = cast(FrameType, frame.f_back)
                fname = Filename(back.f_code.co_filename)
                func = back.f_code.co_name
            while not Scalene.should_trace(fname, func):
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
                    func = frame.f_code.co_name
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
                # Handle case where the function with the name wrapped
                # in triangle brackets is at the bottom of the stack
                if f is None:
                    return
        except Exception:
            return
        if not Scalene.should_trace(f.f_code.co_filename, f.f_code.co_name):
            return

        fn_name = get_fully_qualified_name(f)
        firstline = f.f_code.co_firstlineno

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

        stats.alloc_samples += len(arr)

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
                python_fraction,
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
                    stats.max_footprint_python_fraction = python_fraction
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
            if is_malloc and count == scalene.scalene_config.NEWLINE_TRIGGER_LENGTH + 1:
                with Scalene.__invalidate_mutex:
                    last_file, last_line = Scalene.__invalidate_queue.pop(0)

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
                [time.monotonic_ns() - Scalene.__start_time, max(0, curr)]
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
    def should_trace(filename: Filename, func: str) -> bool:
        """Return true if we should trace this filename and function."""
        if not filename:
            return False
        if Scalene.__profiler_base in filename:
            # Don't profile the profiler.
            return False
        if Scalene.__functions_to_profile:
            if filename in Scalene.__functions_to_profile:
                if func in {
                    fn.__code__.co_name
                    for fn in Scalene.__functions_to_profile[filename]
                }:
                    return True
            return False
        # Don't profile the Python libraries, unless overridden by --profile-all
        try:
            resolved_filename = str(pathlib.Path(filename).resolve())
        except OSError:
            # Not a file
            return False
        if not Scalene.__args.profile_all:
            for n in sysconfig.get_scheme_names():
                for p in sysconfig.get_path_names():
                    the_path = sysconfig.get_path(p, n)
                    libdir = str(
                        pathlib.Path(the_path).resolve()
                    )
                    if libdir in resolved_filename:
                        return False

        # Generic handling follows (when no @profile decorator has been used).
        # TODO [EDB]: add support for this in traceconfig.cpp
        profile_exclude_list = Scalene.__args.profile_exclude.split(",")
        if any(
            prof in filename for prof in profile_exclude_list if prof != ""
        ):
            return False
        if filename.startswith("_ipython-input-"):
            # Profiling code created in a Jupyter cell:
            # create a file to hold the contents.
            import IPython  # type: ignore

            if result := re.match(r"_ipython-input-([0-9]+)-.*", filename):
                # Write the cell's contents into the file.
                cell_contents = (
                    IPython.get_ipython().history_manager.input_hist_raw[
                        int(result[1])
                    ]
                )
                with open(filename, "w+") as f:
                    f.write(cell_contents)
                return True
        # If (a) `profile-only` was used, and (b) the file matched
        # NONE of the provided patterns, don't profile it.
        profile_only_set = set(Scalene.__args.profile_only.split(","))
        if profile_only_set and all(
            prof not in filename for prof in profile_only_set
        ):
            return False
        if filename[0] == "<" and filename[-1] == ">":
            # Special non-file
            return False
        # Now we've filtered out any non matches to profile-only patterns.
        # If `profile-all` is specified, profile this file.
        if Scalene.__args.profile_all:
            return True
        # Profile anything in the program's directory or a child directory,
        # but nothing else, unless otherwise specified.
        filename = Filename(
            os.path.normpath(os.path.join(Scalene.__program_path, filename))
        )
        return Scalene.__program_path in filename

    __done = False

    @staticmethod
    def start() -> None:
        """Initiate profiling."""
        if not Scalene.__initialized:
            print(
                "ERROR: Do not try to invoke `start` if you have not called Scalene using one of the methods\n"
                "in https://github.com/plasma-umass/scalene#using-scalene\n"
                "(The most likely issue is that you need to run your code with `scalene`, not `python`).",
                file=sys.stderr
            )
            sys.exit(1)
        Scalene.__stats.start_clock()
        Scalene.enable_signals()
        Scalene.__start_time = time.monotonic_ns()
        Scalene.__done = False

        if Scalene.__args.memory:
            from scalene import pywhere  # type: ignore
            pywhere.set_scalene_done_false()


    @staticmethod
    def stop() -> None:
        """Complete profiling."""
        Scalene.__done = True
        if Scalene.__args.memory:
            from scalene import pywhere  # type: ignore
            pywhere.set_scalene_done_true()



        Scalene.disable_signals()
        Scalene.__stats.stop_clock()
        if Scalene.__args.outfile:
            Scalene.__profile_filename = os.path.join(
                os.path.dirname(Scalene.__args.outfile),
                os.path.basename(Scalene.__profile_filename),
            )

        if (
            Scalene.__args.web
            and not Scalene.__args.cli
            and not Scalene.__is_child
        ):
            # First, check for a browser.
            try:
                if not find_browser():
                    # Could not open a graphical web browser tab;
                    # act as if --web was not specified
                    Scalene.__args.web = False
                else:
                    # Force JSON output to profile.json.
                    Scalene.__args.json = True
                    Scalene.__output.html = False
                    Scalene.__output.output_file = Scalene.__profile_filename
            except Exception:
                # Couldn't find a browser.
                Scalene.__args.web = False

            # If so, set variables appropriately.
            if Scalene.__args.web and Scalene.in_jupyter():
                # Force JSON output to profile.json.
                Scalene.__args.json = True
                Scalene.__output.html = False
                Scalene.__output.output_file = Scalene.__profile_filename

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
        # Output the profile if `--outfile` was set to a file.
        if Scalene.__output.output_file:
            Scalene.output_profile(sys.argv)

    @staticmethod
    def disable_signals(retry: bool = True) -> None:
        """Turn off the profiling signals."""
        if sys.platform == "win32":
            Scalene.timer_signals = False
            return
        try:
            Scalene.__orig_setitimer(Scalene.__signals.cpu_timer_signal, 0)
            for sig in [
                Scalene.__signals.malloc_signal,
                Scalene.__signals.free_signal,
                Scalene.__signals.memcpy_signal,
            ]:
                Scalene.__orig_signal(sig, signal.SIG_IGN)
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
        left: List[str],
    ) -> int:
        """Initiate execution and profiling."""
        if Scalene.__args.memory:
            from scalene import pywhere  # type: ignore

            pywhere.populate_struct()
        # If --off is set, tell all children to not profile and stop profiling before we even start.
        if "off" not in Scalene.__args or not Scalene.__args.off:
            self.start()
        # Run the code being profiled.
        exit_status = 0
        try:
            exec(code, the_globals, the_locals)
        except SystemExit as se:
            # Intercept sys.exit and propagate the error code.
            exit_status = se.code if type(se.code) == int else 1
        except KeyboardInterrupt:
            # Cleanly handle keyboard interrupts (quits execution and dumps the profile).
            print("Scalene execution interrupted.", file=sys.stderr)
        except Exception as e:
            print(f"{Scalene.__error_message}:\n", e, file=sys.stderr)
            traceback.print_exc()
            exit_status = 1
        finally:
            self.stop()
            if Scalene.__args.memory:
                pywhere.disable_settrace()
                pywhere.depopulate_struct()
            # Leaving here in case of reversion
            # sys.settrace(None)
            stats = Scalene.__stats
            (last_file, last_line, _) = Scalene.last_profiled_tuple()
            stats.memory_malloc_count[last_file][last_line] += 1
            stats.memory_aggregate_footprint[last_file][
                last_line
            ] += stats.memory_current_highwater_mark[last_file][last_line]
            # If we've collected any samples, dump them.
            did_output = Scalene.output_profile(left)
            if not did_output:
                print(
                    "Scalene: The specified code did not run for long enough to profile.",
                    file=sys.stderr
                )
                # Print out hints to explain why the above message may have been printed.
                if not Scalene.__args.profile_all:
                    # if --profile-all was not specified, suggest it
                    # as a way to profile otherwise excluded code
                    # (notably Python libraries, which are excluded by
                    # default).
                    print(
                        "By default, Scalene only profiles code in the file executed and its subdirectories.",
                        file=sys.stderr
                        )
                    print(
                        "To track the time spent in all files, use the `--profile-all` option.",
                        file=sys.stderr
                    )
                elif Scalene.__args.profile_only or Scalene.__args.profile_exclude:
                    # if --profile-only or --profile-exclude were
                    # specified, suggest that the patterns might be
                    # excluding too many files. Collecting the
                    # previously filtered out files could allow
                    # suggested fixes (as in, remove foo because it
                    # matches too many files).
                    print("The patterns used in `--profile-only` or `--profile-exclude` may be filtering out too many files.",
                          file=sys.stderr
                          )
                else:
                    # if none of the above cases hold, indicate that
                    # Scalene can only profile code that runs for at
                    # least one second or allocates some threshold
                    # amount of memory.
                    print("Scalene can only profile code that runs for at least one second or allocates at least 10MB.",
                          file=sys.stderr
                        )
            if not (
                did_output
                and Scalene.__args.web
                and not Scalene.__args.cli
                and not Scalene.__is_child
            ):
                return exit_status

            generate_html(
                profile_fname=Scalene.__profile_filename,
                output_fname=Scalene.__args.outfile
                if Scalene.__args.outfile
                else Scalene.__profiler_html,
            )
            if Scalene.in_jupyter():
                from scalene.scalene_jupyter import ScaleneJupyter

                port = ScaleneJupyter.find_available_port(8181, 9000)
                if not port:
                    print("Scalene error: could not find an available port.",
                          file=sys.stderr)
                else:
                    ScaleneJupyter.display_profile(
                        port, Scalene.__profiler_html
                    )
            else:
                if not Scalene.__args.no_browser:
                    # Remove any interposition libraries from the environment before opening the browser.
                    # See also scalene/scalene_preload.py
                    old_dyld = os.environ.pop("DYLD_INSERT_LIBRARIES", "")
                    old_ld = os.environ.pop("LD_PRELOAD", "")
                    if Scalene.__args.outfile:
                        output_fname = Scalene.__args.outfile
                    else:
                        output_fname = (
                            f"{os.getcwd()}{os.sep}{Scalene.__profiler_html}"
                        )
                    if Scalene.__pid == 0:
                        # Only open a browser tab for the parent.
                        # url = f"file:///{output_fname}"
                        # webbrowser.open(url)
                        # show_browser(output_fname, SCALENE_PORT, Scalene.__orig_python)
                        dir = os.path.dirname(__file__)
                        subprocess.Popen([Scalene.__orig_python,
                                          f"{dir}{os.sep}launchbrowser.py",
                                          output_fname,
                                          str(scalene.scalene_config.SCALENE_PORT)],
                                         stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
                    # Restore them.
                    os.environ.update(
                        {
                            "DYLD_INSERT_LIBRARIES": old_dyld,
                            "LD_PRELOAD": old_ld,
                        }
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
        if args.outfile:
            Scalene.__output.output_file = os.path.abspath(
                os.path.expanduser(args.outfile)
            )
        Scalene.__is_child = args.pid != 0
        # the pid of the primary profiler
        Scalene.__parent_pid = args.pid if Scalene.__is_child else os.getpid()
        # Don't profile the GPU if not enabled (i.e., either no options or --cpu and/or --memory, but no --gpu).
        if not Scalene.__args.gpu:
            Scalene.__output.gpu = False
            Scalene.__json.gpu = False

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
    def register_files_to_profile() -> None:
        """Tells the pywhere module, which tracks memory, which files to profile."""
        from scalene import pywhere  # type: ignore

        profile_only_list = Scalene.__args.profile_only.split(",")

        pywhere.register_files_to_profile(
            list(Scalene.__files_to_profile) + profile_only_list,
            Scalene.__program_path,
            Scalene.__args.profile_all,
        )
        
    
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
                "To invoke Scalene programmatically, see the usage noted in https://github.com/plasma-umass/scalene#using-scalene",
                file=sys.stderr
            )
            sys.exit(1)
        if sys.platform != "win32":
            for sig, handler in [
                (
                    Scalene.__signals.start_profiling_signal,
                    Scalene.start_signal_handler,
                ),
                (
                    Scalene.__signals.stop_profiling_signal,
                    Scalene.stop_signal_handler,
                ),
            ]:
                Scalene.__orig_signal(sig, handler)
                Scalene.__orig_siginterrupt(sig, False)
        Scalene.__orig_signal(signal.SIGINT, Scalene.interruption_handler)
        did_preload = (
            False if is_jupyter else ScalenePreload.setup_preload(args)
        )
        if not did_preload:
            with contextlib.suppress(Exception):
                # If running in the background, print the PID.
                if os.getpgrp() != os.tcgetpgrp(sys.stdout.fileno()):
                    # In the background.
                    print(f"Scalene now profiling process {os.getpid()}", file=sys.stderr)
                    print(
                        f"  to disable profiling: python3 -m scalene.profile --off --pid {os.getpid()}",
                        file=sys.stderr
                    )
                    print(
                        f"  to resume profiling:  python3 -m scalene.profile --on  --pid {os.getpid()}",
                        file=sys.stderr
                    )
        Scalene.__stats.clear_all()
        sys.argv = left
        with contextlib.suppress(Exception):
            if not is_jupyter:
                multiprocessing.set_start_method("fork")
        spec = None
        try:
            Scalene.process_args(args)
            progs = None
            exit_status = 0
            try:
                # Handle direct invocation of a string by executing the string and returning.
                if len(sys.argv) >= 2 and sys.argv[0] == "-c":
                    try:
                        exec(sys.argv[1])
                    except SyntaxError:
                        traceback.print_exc()
                        sys.exit(1)
                    sys.exit(0)

                if len(sys.argv) >= 2 and sys.argv[0] == "-m":
                    module = True

                    # Remove -m and the provided module name
                    _, mod_name, *sys.argv = sys.argv

                    # Given `some.module`, find the path of the corresponding
                    # some/module/__main__.py or some/module.py file to run.
                    _, spec, _ = _get_module_details(mod_name)
                    if not spec.origin:
                        raise FileNotFoundError
                    # Prepend the found .py file to arguments
                    sys.argv.insert(0, spec.origin)
                else:
                    module = False

                # Look for something ending in '.py'. Treat the first one as our executable.
                progs = [x for x in sys.argv if re.match(r".*\.py$", x)]
                # Just in case that didn't work, try sys.argv[0] and __file__.
                with contextlib.suppress(Exception):
                    progs.extend((sys.argv[0], __file__))
                if not progs:
                    raise FileNotFoundError
                # Use the full absolute path of the program being profiled, expanding ~ if need be.
                prog_name = os.path.abspath(os.path.expanduser(progs[0]))
                with open(
                    prog_name, "r", encoding="utf-8"
                ) as prog_being_profiled:
                    # Read in the code and compile it.
                    code: Any = ""
                    try:
                        code = compile(
                            prog_being_profiled.read(),
                            prog_name,
                            "exec",
                        )
                    except SyntaxError:
                        traceback.print_exc()
                        sys.exit(1)
                    # Push the program's path.
                    program_path = Filename(os.path.dirname(prog_name))
                    if not module:
                        sys.path.insert(0, program_path)
                        # NOTE: Python, in its standard mode of operation,
                        # places the root of the module tree at the directory of
                        # the entrypoint script. This is different in how things
                        # work with the `-m` mode of operation, so for now we do not
                        # surface this in Scalene
                        #
                        # TODO: Add in entrypoint_dir logic for `-m` operation
                        Scalene.__entrypoint_dir = program_path
                    # If a program path was specified at the command-line, use it.
                    if len(args.program_path) > 0:
                        Scalene.__program_path = Filename(
                            os.path.abspath(args.program_path)
                        )
                    else:
                        # Otherwise, use the invoked directory.
                        Scalene.__program_path = program_path
                    # Grab local and global variables.
                    if Scalene.__args.memory:
                        Scalene.register_files_to_profile()
                    import __main__

                    the_locals = __main__.__dict__
                    the_globals = __main__.__dict__
                    # Splice in the name of the file being executed instead of the profiler.
                    the_globals["__file__"] = prog_name
                    # This part works because of the order in which Python attempts to resolve names--
                    # Within a given context, it first tries to look for __package__, and then for __spec__.
                    # __spec__ is a ModuleSpec object that carries a lot of extra machinery and requires
                    # extra effort to create (it seems, at least).
                    #
                    # __spec__ was originally set to none because the __globals__ here has the Scalene ModuleSpec
                    # but it doesn't seem like that was enough. Setting the __package__, as below, seems to be enough to make
                    # it look in the right place
                    the_globals["__spec__"] = None
                    if spec is not None:
                        name = spec.name
                        the_globals["__package__"] = name.split(".")[0]
                    # Do a GC before we start.
                    gc.collect()
                    # Start the profiler.
                    profiler = Scalene(args, Filename(prog_name))
                    try:
                        # We exit with this status (returning error code as appropriate).
                        exit_status = profiler.profile_code(
                            code, the_locals, the_globals, left
                        )
                        if not is_jupyter:
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
                        print(message, file=sys.stderr)
                        print(traceback.format_exc(), file=sys.stderr)
            except (FileNotFoundError, IOError):
                if progs:
                    print(f"Scalene: could not find input file {prog_name}", file=sys.stderr)
                else:
                    print("Scalene: no input file specified.", file=sys.stderr)
                sys.exit(1)
        except SystemExit as e:
            exit_status = e.code if type(e.code) == int else 1

        except StopJupyterExecution:
            pass
        except Exception:
            print("Scalene failed to initialize.\n" + traceback.format_exc(), file=sys.stderr)
            sys.exit(1)
        finally:
            with contextlib.suppress(Exception):
                for mapfile in [
                    Scalene.__malloc_mapfile,
                    Scalene.__memcpy_mapfile,
                ]:
                    mapfile.close()
                    if not Scalene.__is_child:
                        mapfile.cleanup()
            if not is_jupyter:
                sys.exit(exit_status)


if __name__ == "__main__":
    Scalene.main()
