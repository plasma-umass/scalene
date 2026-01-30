# ruff: noqa: E402

from __future__ import (
    annotations,
)

"""Scalene: a CPU+memory+GPU (and more) profiler for Python.

    https://github.com/plasma-umass/scalene

    See the paper "docs/osdi23-berger.pdf" in this repository for technical
    details on Scalene's design.

    by Emery Berger, Sam Stern, and Juan Altmayer Pizzorno

    usage: scalene test/testme.py
    usage help: scalene --help

   Scalene fully supports Unix-like operating systems; in
   particular, Linux, Mac OS X, and WSL 2 (Windows Subsystem for Linux 2 = Ubuntu).
   It also has partial support for Windows.

"""

# Import cysignals early so it doesn't disrupt Scalene's use of signals; this allows Scalene to profile Sage.
# See https://github.com/plasma-umass/scalene/issues/740.
try:  # noqa: SIM105
    import cysignals  # noqa: F401
except ModuleNotFoundError:
    pass

import argparse
import atexit
import builtins
import contextlib
import ctypes  # noqa: F401
import functools
import gc
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
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
import traceback
import warnings
from collections import defaultdict
from types import (
    FrameType,
)
from typing import (
    Any,
    Callable,
    Generator,
    cast,
)

# For debugging purposes
from rich.console import Console

import scalene.scalene_config
from scalene.find_browser import find_browser
from scalene.get_module_details import _get_module_details
from scalene.redirect_python import redirect_python
from scalene.scalene_accelerator import ScaleneAccelerator
from scalene.scalene_arguments import ScaleneArguments
from scalene.scalene_client_timer import ScaleneClientTimer
from scalene.scalene_cpu_profiler import ScaleneCPUProfiler
from scalene.scalene_funcutils import ScaleneFuncUtils
from scalene.scalene_jax import JaxProfiler
from scalene.scalene_json import ScaleneJSON
from scalene.scalene_library_profiler import ScaleneLibraryProfiler
from scalene.scalene_library_registry import LibraryProfilerRegistry
from scalene.scalene_lifecycle import ScaleneLifecycle
from scalene.scalene_mapfile import ScaleneMapFile
from scalene.scalene_memory_profiler import ScaleneMemoryProfiler
from scalene.scalene_output import ScaleneOutput
from scalene.scalene_parseargs import ScaleneParseArgs, StopJupyterExecution
from scalene.scalene_preload import ScalenePreload
from scalene.scalene_signal_manager import ScaleneSignalManager
from scalene.scalene_signals import ScaleneSignals, SignumType
from scalene.scalene_sigqueue import ScaleneSigQueue
from scalene.scalene_statistics import (
    Address,
    ByteCodeIndex,
    Filename,
    LineNumber,
    MemcpyProfilingSample,
    ProfilingSample,
    ScaleneStatistics,
)
from scalene.scalene_tensorflow import TensorFlowProfiler
from scalene.scalene_torch import TorchProfiler, is_torch_available
from scalene.scalene_tracer import (
    ScaleneTracer,
    cleanup_tracer,
    disable_tracing,
    enable_tracing,
    initialize_tracer,
    set_use_legacy_tracer,
    set_use_python_callback,
    using_sys_monitoring,
)
from scalene.scalene_tracing import ScaleneTracing
from scalene.scalene_utility import (
    add_stack,
    compute_frames_to_record,
    enter_function_meta,
    generate_html,
    get_fully_qualified_name,
    on_stack,
    patch_module_functions_with_signal_blocking,
)
from scalene.time_info import TimeInfo, get_times

console = Console(style="white on blue")


# Assigning to `nada` disables any console.log commands.
def nada(*args: Any) -> None:
    pass


console.log = nada  # type: ignore

MINIMUM_PYTHON_VERSION_MAJOR = 3
MINIMUM_PYTHON_VERSION_MINOR = 8


def require_python(version: tuple[int, int]) -> None:
    assert (
        sys.version_info >= version
    ), f"Scalene requires Python version {version[0]}.{version[1]} or above."


require_python((MINIMUM_PYTHON_VERSION_MAJOR, MINIMUM_PYTHON_VERSION_MINOR))


class Scalene:
    """The Scalene profiler itself."""

    # Get the number of available CPUs (preferring `os.sched_getaffinity`, if available).
    __availableCPUs: int

    __in_jupyter = False  # are we running inside a Jupyter notebook
    __start_time = 0  # start of profiling, in nanoseconds
    __sigterm_exit_code = 143
    # Whether the current profiler is a child
    __is_child = -1
    # the pid of the primary profiler
    __parent_pid = -1
    __initialized: bool = False
    __last_profiled: list[Filename | LineNumber | ByteCodeIndex] = [
        Filename("NADA"),
        LineNumber(0),
        ByteCodeIndex(0),
    ]
    __orig_python = sys.executable  # will be rewritten later

    __profile_filename = Filename("scalene-profile.json")
    __profiler_html = Filename("scalene-profile.html")
    __error_message = "Error in program being profiled"
    __windows_queue: queue.Queue[Any] = (
        queue.Queue()
    )  # only used for Windows timer logic
    BYTES_PER_MB = 1024 * 1024

    # Memory allocation action constants (moved to ScaleneMemoryProfiler)
    # These are kept for backward compatibility
    MALLOC_ACTION = ScaleneMemoryProfiler.MALLOC_ACTION
    FREE_ACTION = ScaleneMemoryProfiler.FREE_ACTION
    FREE_ACTION_SAMPLED = ScaleneMemoryProfiler.FREE_ACTION_SAMPLED

    # Support for @profile
    # decorated files
    __files_to_profile: set[Filename] = set()
    # decorated functions
    __functions_to_profile: dict[Filename, set[Any]] = defaultdict(set)

    # Cache the original thread join function, which we replace with our own version.
    __original_thread_join = threading.Thread.join

    # As above; we'll cache the original thread and replace it.
    __original_lock = threading.Lock

    __args = ScaleneArguments()
    __signals = ScaleneSignals()
    __signal_manager: ScaleneSignalManager[Any] = ScaleneSignalManager()
    __stats = ScaleneStatistics()
    __memory_profiler = ScaleneMemoryProfiler(__stats)
    __output = ScaleneOutput()
    __json = ScaleneJSON()
    __accelerator: ScaleneAccelerator | None = (
        None  # initialized after parsing arguments in `main`
    )
    __invalidate_queue: list[tuple[Filename, LineNumber]] = []
    __invalidate_mutex: threading.Lock
    __profiler_base: str

    # Modular components
    __cpu_profiler: ScaleneCPUProfiler
    __tracing: ScaleneTracing

    # Library profiler registry for framework integrations
    # (PyTorch, JAX, TensorFlow, etc.)
    # See https://github.com/plasma-umass/scalene/issues/908
    __library_profilers: LibraryProfilerRegistry = LibraryProfilerRegistry()
    # Keep direct reference to torch profiler for MPS-specific handling
    __torch_profiler: TorchProfiler | None = None

    # when did we last receive a signal?
    __last_signal_time = TimeInfo()

    # path for the program being profiled
    __program_path = Filename("")
    __entrypoint_dir = Filename("")

    # System library paths (for filtering when profile_system_libraries=False)
    __system_lib_paths: tuple[str, ...] = ()

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
    __is_thread_sleeping: dict[int, bool] = defaultdict(bool)  # False by default

    child_pids: set[int] = set()  # Needs to be unmangled to be accessed by shims

    # Signal queues for allocations and memcpy
    __alloc_sigq: ScaleneSigQueue[Any]
    __memcpy_sigq: ScaleneSigQueue[Any]
    __sigqueues: list[ScaleneSigQueue[Any]]

    client_timer: ScaleneClientTimer = ScaleneClientTimer()

    __orig_signal = signal.signal
    __orig_exit = os._exit
    __orig_raise_signal = signal.raise_signal
    __lifecycle_disabled = False

    __orig_kill = os.kill

    __last_cpu_interval = 0.0

    def __init__(
        self,
        arguments: argparse.Namespace,
        program_being_profiled: Filename | None = None,
    ) -> None:
        # Wrap all os calls so that they disable SIGALRM (the signal used for CPU sampling).
        # This fixes https://github.com/plasma-umass/scalene/issues/841.
        if sys.platform != "win32":
            patch_module_functions_with_signal_blocking(os, signal.SIGALRM)

        # Import all replacement functions.
        import scalene.replacement_exec
        import scalene.replacement_exit
        import scalene.replacement_get_context
        import scalene.replacement_lock
        import scalene.replacement_mp_lock
        import scalene.replacement_pjoin
        import scalene.replacement_signal_fns
        import scalene.replacement_thread_join

        if sys.platform != "win32":
            import scalene.replacement_fork
            import scalene.replacement_poll_selector  # noqa: F401

        Scalene.__args = ScaleneArguments(**vars(arguments))
        Scalene.__alloc_sigq = ScaleneSigQueue(Scalene._alloc_sigqueue_processor)
        Scalene.__memcpy_sigq = ScaleneSigQueue(Scalene._memcpy_sigqueue_processor)
        Scalene.__sigqueues = [
            Scalene.__alloc_sigq,
            Scalene.__memcpy_sigq,
        ]
        # Add signal queues to the signal manager
        Scalene.__signal_manager.add_signal_queue(Scalene.__alloc_sigq)
        Scalene.__signal_manager.add_signal_queue(Scalene.__memcpy_sigq)
        Scalene.__invalidate_mutex = Scalene.get_original_lock()

        Scalene.__windows_queue = queue.Queue()

        # Initialize the malloc related files; if for whatever reason
        # the files don't exist and we are supposed to be profiling
        # memory, exit.
        try:
            Scalene.__malloc_mapfile = ScaleneMapFile("malloc")
            Scalene.__memcpy_mapfile = ScaleneMapFile("memcpy")
            Scalene.__memory_profiler.set_mapfiles(
                Scalene.__malloc_mapfile, Scalene.__memcpy_mapfile
            )
        except Exception as e:
            # Ignore if we aren't profiling memory; otherwise, exit.
            if Scalene.__args.memory:
                print(
                    f"Scalene: Failed to initialize memory profiling: {e}",
                    file=sys.stderr,
                )
                sys.exit(1)

        Scalene.__signal_manager.get_signals().set_timer_signals(
            Scalene.__args.use_virtual_time
        )
        Scalene.__profiler_base = str(os.path.dirname(__file__))

        # Initialize modular components
        if not hasattr(Scalene, "_Scalene__availableCPUs"):
            cpu_count = os.cpu_count()
            Scalene.__availableCPUs = cpu_count if cpu_count is not None else 1
        Scalene.__cpu_profiler = ScaleneCPUProfiler(
            Scalene.__stats, Scalene.__availableCPUs
        )
        Scalene.__tracing = ScaleneTracing(
            Scalene.__args,
            Scalene.__profiler_base,
            Scalene.__program_path,
        )
        if Scalene.__args.pid:
            # Child process.
            # We need to use the same directory as the parent.
            # The parent always puts this directory as the first entry in the PATH.
            # Extract the alias directory from the path.
            dirname = os.environ["PATH"].split(os.pathsep)[0]
            Scalene.__python_alias_dir = pathlib.Path(dirname)
            Scalene.__pid = Scalene.__args.pid

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
            if "off" in Scalene.__args and Scalene.__args.off:
                cmdline += " --off"
            # Only pass along options that are valid for the 'run' subcommand
            if getattr(Scalene.__args, "use_virtual_time", False):
                cmdline += " --use-virtual-time"
            if getattr(Scalene.__args, "gpu", False):
                cmdline += " --gpu"
            if getattr(Scalene.__args, "memory", False):
                cmdline += " --memory"
            # Note: --cpu is now --cpu-only; only pass if we are CPU-only (no memory/gpu)
            if (
                getattr(Scalene.__args, "cpu", False)
                and not getattr(Scalene.__args, "memory", False)
                and not getattr(Scalene.__args, "gpu", False)
            ):
                cmdline += " --cpu-only"
            # Add the --pid field so we can propagate it to the child.
            cmdline += f" --pid={os.getpid()} ---"
            # Build the commands to pass along other arguments
            environ = ScalenePreload.get_preload_environ(Scalene.__args)
            if sys.platform == "win32":
                preface = "\n".join(f"set {k}={str(v)}\n" for (k, v) in environ.items())
            else:
                preface = " ".join(
                    "=".join((k, f"'{str(v)}'")) for (k, v) in environ.items()
                )
            Scalene.__orig_python = redirect_python(
                preface, cmdline, Scalene.__python_alias_dir
            )

        # Register the exit handler to run when the program terminates or we quit.
        atexit.register(Scalene._exit_handler)
        # Store relevant names (program, path).
        if program_being_profiled:
            Scalene.__program_being_profiled = Filename(program_being_profiled)

    try:
        __availableCPUs = len(os.sched_getaffinity(0))  # type: ignore[unused-ignore,attr-defined]
    except AttributeError:
        cpu_count = os.cpu_count()
        __availableCPUs = cpu_count if cpu_count is not None else 1

    @staticmethod
    def last_profiled_tuple() -> tuple[Filename, LineNumber, ByteCodeIndex]:
        """Helper function to type last profiled information."""
        return cast(
            "tuple[Filename, LineNumber, ByteCodeIndex]", Scalene.__last_profiled
        )

    if sys.platform != "win32":
        __orig_setitimer = signal.setitimer
        __orig_siginterrupt = signal.siginterrupt

    @classmethod
    def _clear_metrics(cls) -> None:
        """Clear the various states for forked processes."""
        cls.__stats.clear()
        cls.child_pids.clear()

    @classmethod
    def _add_child_pid(cls, pid: int) -> None:
        """Add this pid to the set of children. Used when forking."""
        cls.child_pids.add(pid)

    @classmethod
    def remove_child_pid(cls, pid: int) -> None:
        """Remove a child once we have joined with it (used by replacement_pjoin.py)."""
        with contextlib.suppress(KeyError):
            cls.child_pids.remove(pid)

    @staticmethod
    def after_fork_in_child() -> None:
        """Execute in a child process after a fork. Invoked by replacement_fork.py."""
        Scalene.__is_child = True
        Scalene._clear_metrics()
        if Scalene.__accelerator and Scalene.__accelerator.has_gpu():
            Scalene.__accelerator.reinit()
        Scalene.__pid = Scalene.__parent_pid
        if "off" not in Scalene.__args or not Scalene.__args.off:
            Scalene.enable_signals()

    @staticmethod
    def after_fork_in_parent(child_pid: int) -> None:
        """Execute in parent after a fork. Invoked by replacement_fork.py."""
        Scalene._add_child_pid(child_pid)
        Scalene.start_signal_queues()

    @staticmethod
    def before_fork() -> None:
        """Execute just before a fork. Invoked by replacement_fork.py."""
        Scalene.stop_signal_queues()

    @staticmethod
    def disable_lifecycle() -> None:
        Scalene.__lifecycle_disabled = True

    @staticmethod
    def get_all_signals_set() -> set[int]:
        """Return the set of all signals currently set.

        Used by replacement_signal_fns.py to shim signals used by the client program.
        """
        return set(Scalene.__signal_manager.get_signals().get_all_signals())

    @staticmethod
    def get_lifecycle_signals() -> tuple[signal.Signals, signal.Signals]:
        return Scalene.__signal_manager.get_signals().get_lifecycle_signals()

    @staticmethod
    def get_original_lock() -> threading.Lock:
        """Return the true lock, which we shim in replacement_lock.py."""
        return Scalene.__original_lock()

    @staticmethod
    def get_signals() -> ScaleneSignals:
        return Scalene.__signal_manager.get_signals()

    @staticmethod
    def get_lifecycle_disabled() -> bool:
        return Scalene.__lifecycle_disabled

    @staticmethod
    def get_timer_signals() -> tuple[int, signal.Signals]:
        """Return the set of all TIMER signals currently set.

        Used by replacement_signal_fns.py to shim timers used by the client program.
        """
        return Scalene.__signal_manager.get_signals().get_timer_signals()

    @staticmethod
    def update_line() -> None:
        """Mark a new line by allocating the trigger number of bytes."""
        bytearray(scalene.scalene_config.NEWLINE_TRIGGER_LENGTH)

    @staticmethod
    def update_profiled() -> None:
        with Scalene.__invalidate_mutex:
            last_prof_tuple = Scalene.last_profiled_tuple()
            Scalene.__invalidate_queue.append((last_prof_tuple[0], last_prof_tuple[1]))
            Scalene.update_line()

    @staticmethod
    def _profile(func: Any) -> Any:
        """Record the file and function name.

        Replacement @profile decorator function.  Scalene tracks which
        functions - in which files - have been decorated; if any have,
        it and only reports stats for those.

        """
        filename = Filename(func.__code__.co_filename)
        Scalene.__files_to_profile.add(filename)
        Scalene.__functions_to_profile[filename].add(func)

        # Also update the tracing module
        if hasattr(Scalene, "_Scalene__tracing"):
            Scalene.__tracing.add_file_to_profile(filename)
            Scalene.__tracing.add_function_to_profile(filename, func)

        if Scalene.__args.memory:
            Scalene._register_files_to_profile()
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

    @staticmethod
    def windows_timer_loop() -> None:
        """For Windows, send periodic timer signals; launch as a background thread."""
        Scalene.__signal_manager.windows_timer_loop(
            Scalene.__args.cpu_sampling_rate
        )  # TODO: integrate support for use of sample_cpu_interval()

    @staticmethod
    def start_signal_queues() -> None:
        """Start the signal processing queues (i.e., their threads)."""
        Scalene.__signal_manager.start_signal_queues()

    @staticmethod
    def stop_signal_queues() -> None:
        """Stop the signal processing queues (i.e., their threads)."""
        Scalene.__signal_manager.stop_signal_queues()

    @staticmethod
    def term_signal_handler(
        signum: SignumType,
        this_frame: FrameType | None,
    ) -> None:
        """Handle terminate signals."""
        Scalene.stop()
        Scalene.output_profile()

        Scalene.__orig_exit(Scalene.__sigterm_exit_code)

    @staticmethod
    def malloc_signal_handler(
        signum: SignumType,
        this_frame: FrameType | None,
    ) -> None:
        """Handle allocation signals."""
        if not Scalene.__args.memory:
            # This should never happen, but we fail gracefully.
            return
        from scalene import pywhere  # type: ignore

        if this_frame:
            enter_function_meta(this_frame, Scalene._should_trace, Scalene.__stats)
        # Walk the stack till we find a line of code in a file we are tracing.
        found_frame = False
        f = this_frame
        while f:
            if found_frame := Scalene._should_trace(
                Filename(f.f_code.co_filename), f.f_code.co_name
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
        fname, lineno, _lasti = Scalene.last_profiled_tuple()
        if not invalidated and this_frame and not (on_stack(this_frame, fname, lineno)):
            Scalene.update_profiled()
        pywhere.set_last_profiled_invalidated_false()
        # In the setprofile callback, we rely on
        # __last_profiled always having the same memory address.
        # This is an optimization to not have to traverse the Scalene profiler
        # object's dictionary every time we want to update the last profiled line.
        #
        # A previous change to this code set Scalene.__last_profiled = [fname, lineno, lasti],
        # which created a new list object and set the __last_profiled attribute to the new list. This
        # made the object held in `pywhere.cpp` out of date, and caused the profiler to not update the last profiled line.
        Scalene.__last_profiled[:] = [
            Filename(f.f_code.co_filename),
            (
                LineNumber(f.f_lineno)
                if f.f_lineno is not None
                else LineNumber(f.f_code.co_firstlineno)
            ),
            ByteCodeIndex(f.f_lasti),
        ]
        Scalene.__alloc_sigq.put([0])
        # Enable line tracing to detect when execution moves to a different line.
        # On Python 3.12+, this uses sys.monitoring; on earlier versions,
        # it falls back to PyEval_SetTrace.
        assert this_frame
        enable_tracing(this_frame)
        del this_frame

    @staticmethod
    def free_signal_handler(
        signum: SignumType,
        this_frame: FrameType | None,
    ) -> None:
        """Handle free signals."""
        if this_frame:
            enter_function_meta(this_frame, Scalene._should_trace, Scalene.__stats)
        Scalene.__alloc_sigq.put([0])
        del this_frame

    @staticmethod
    def memcpy_signal_handler(
        signum: SignumType,
        this_frame: FrameType | None,
    ) -> None:
        """Handle memcpy signals."""
        Scalene.__memcpy_sigq.put((signum, this_frame))
        del this_frame

    @staticmethod
    def enable_signals() -> None:
        """Set up the signal handlers to handle interrupts for profiling and start the
        timer interrupts."""
        next_interval = Scalene._sample_cpu_interval()
        # On Windows, pre-initialize the time values so the first timer callback
        # can record samples. Without this, the first call just initializes time
        # and returns, but on Windows the program may finish before the second call.
        if sys.platform == "win32":
            now = TimeInfo()
            now.sys, now.user = get_times()
            now.virtual = time.process_time()
            now.wallclock = time.perf_counter()
            Scalene.__last_signal_time = now
        # On Windows, pass the signal queues for memory polling only if memory profiling is enabled
        alloc_sigq = None
        memcpy_sigq = None
        if sys.platform == "win32" and Scalene.__args.memory:
            alloc_sigq = Scalene.__alloc_sigq
            memcpy_sigq = Scalene.__memcpy_sigq
        Scalene.__signal_manager.enable_signals(
            Scalene.malloc_signal_handler,
            Scalene.free_signal_handler,
            Scalene.memcpy_signal_handler,
            Scalene.term_signal_handler,
            Scalene.cpu_signal_handler,
            next_interval,
            alloc_sigq,
            memcpy_sigq,
        )

    @staticmethod
    def cpu_signal_handler(
        signum: SignumType,
        this_frame: FrameType | None,
    ) -> None:
        """Handle CPU signals.

        Note: On Windows, this handler is called directly from a background thread
        (not via signals) because signal.raise_signal() cannot be called from
        background threads. The handler uses sys._current_frames() which is
        thread-safe, so this is safe to call from any thread.
        """
        # Initialize next_interval with a default value in case an exception occurs
        # before it's assigned. This prevents NameError in the finally block.
        next_interval = Scalene._sample_cpu_interval()
        try:
            # Get current time stats.
            now = TimeInfo()
            now.sys, now.user = get_times()
            now.virtual = time.process_time()
            now.wallclock = time.perf_counter()
            if (
                Scalene.__last_signal_time.virtual == 0
                or Scalene.__last_signal_time.wallclock == 0
            ):
                # Initialization: store values and update on the next pass.
                # On Windows, we pre-initialize in enable_signals() so this
                # shouldn't be reached, but handle it just in case.
                Scalene.__last_signal_time = now
                if sys.platform != "win32":
                    Scalene.__signal_manager.restart_timer(next_interval)
                return

            if Scalene.__accelerator:
                gpu_load, gpu_mem_used = Scalene.__accelerator.get_stats()
            else:
                gpu_load, gpu_mem_used = (0.0, 0.0)

            # Process this CPU sample.
            frames = compute_frames_to_record(Scalene._should_trace)
            Scalene._process_cpu_sample(
                signum,
                frames,
                now,
                gpu_load,
                gpu_mem_used,
                Scalene.__last_signal_time,
                Scalene.__is_thread_sleeping,
            )
            elapsed = now.wallclock - Scalene.__last_signal_time.wallclock
            # Store the latest values as the previously recorded values.
            Scalene.__last_signal_time = now
            # Restart the timer while handling any timers set by the client.
            next_interval = Scalene._sample_cpu_interval()
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
                        to_wait = min(remaining_time, next_interval)
                    else:
                        to_wait = next_interval
                    Scalene.__signal_manager.restart_timer(to_wait)
                else:
                    Scalene.__signal_manager.restart_timer(next_interval)
        finally:
            if sys.platform == "win32":
                Scalene.__signal_manager.restart_timer(next_interval)

    @staticmethod
    def output_profile(program_args: list[str] | None = None) -> bool:
        """Output the profile. Returns true iff there was any info reported the profile."""
        if Scalene.__args.json:
            json_output = Scalene.__json.output_profiles(
                Scalene.__program_being_profiled,
                Scalene.__stats,
                Scalene.__pid,
                Scalene._profile_this_code,
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
            if Scalene.__args.outfile:
                outfile = os.path.join(
                    os.path.dirname(Scalene.__args.outfile),
                    os.path.splitext(os.path.basename(Scalene.__args.outfile))[0]
                    + ".json",
                )
            # If there was no output file specified, use the default profile filename.
            if not outfile:
                outfile = Scalene.__profile_filename
            # Write the JSON to the output file.
            with open(outfile, "w") as f:
                f.write(json.dumps(json_output, sort_keys=True, indent=4) + "\n")
            # Print instructions for viewing the profile
            if json_output and not Scalene.__is_child:
                # Only include filename if non-default output was used
                file_arg = (
                    "" if outfile == Scalene.__profile_filename else f" {outfile}"
                )
                print(
                    f"\nScalene: profile saved to {outfile}\n"
                    f"  To view in browser:  scalene view{file_arg}\n"
                    f"  To view in terminal: scalene view --cli{file_arg}",
                    file=sys.stderr,
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
                Scalene._profile_this_code,
                Scalene.__python_alias_dir,
                Scalene.__program_path,
                program_args,
                profile_memory=Scalene.__args.memory,
                reduced_profile=Scalene.__args.reduced_profile,
            )
            return did_output

    @staticmethod
    def _set_in_jupyter() -> None:
        """Tell Scalene that it is running inside a Jupyter notebook."""
        Scalene.__in_jupyter = True

    @staticmethod
    def _in_jupyter() -> bool:
        """Return whether Scalene is running inside a Jupyter notebook."""
        return Scalene.__in_jupyter

    @staticmethod
    def _interruption_handler(
        signum: SignumType,
        this_frame: FrameType | None,
    ) -> None:
        """Handle keyboard interrupts (e.g., Ctrl-C)."""
        raise KeyboardInterrupt

    @staticmethod
    def _generate_exponential_sample(scale: float) -> float:
        import random

        u = random.random()  # Uniformly distributed random number between 0 and 1
        return -scale * math.log(1 - u)

    @staticmethod
    def _sample_cpu_interval() -> float:
        interval = Scalene._generate_exponential_sample(
            Scalene.__args.cpu_sampling_rate
        )
        Scalene.__last_cpu_interval = interval
        return interval

    @staticmethod
    @functools.lru_cache(maxsize=None)
    def _get_line_info(
        fname: Filename,
    ) -> list[tuple[list[str], int]]:
        line_info = (
            inspect.getsourcelines(fn) for fn in Scalene.__functions_to_profile[fname]
        )
        return list(line_info)

    @staticmethod
    def _profile_this_code(fname: Filename, lineno: LineNumber) -> bool:
        # sourcery skip: inline-immediately-returned-variable
        """When using @profile, only profile files & lines that have been decorated."""
        if not Scalene.__files_to_profile:
            return True
        if fname not in Scalene.__files_to_profile:
            return False
        # Now check to see if it's the right line range.
        line_info = Scalene._get_line_info(fname)
        found_function = any(
            line_start <= lineno < line_start + len(lines)
            for (lines, line_start) in line_info
        )
        return found_function

    @staticmethod
    def _process_cpu_sample(
        _signum: SignumType,
        new_frames: list[tuple[FrameType, int, FrameType]],
        now: TimeInfo,
        gpu_load: float,
        gpu_mem_used: float,
        prev: TimeInfo,
        is_thread_sleeping: dict[int, bool],
    ) -> None:
        """Handle interrupts for CPU profiling.

        Delegates to ScaleneCPUProfiler for the actual processing.
        """
        # Check if it's time to print profiling info
        if now.wallclock >= Scalene.__next_output_time:
            Scalene.__next_output_time += Scalene.__args.profile_interval
            stats = Scalene.__stats
            with contextlib.ExitStack() as stack:
                _ = [stack.enter_context(s.lock) for s in Scalene.__sigqueues]
                stats.stop_clock()
                Scalene.output_profile()
                stats.start_clock()

        # Delegate to CPU profiler module
        Scalene.__cpu_profiler.process_cpu_sample(
            new_frames,
            now,
            gpu_load,
            gpu_mem_used,
            prev,
            is_thread_sleeping,
            Scalene._should_trace,
            Scalene.__last_cpu_interval,
            Scalene.__args.stacks,
        )

    @staticmethod
    def _alloc_sigqueue_processor(_x: list[int] | None) -> None:
        """Handle interrupts for memory profiling (mallocs and frees)."""
        # Delegate malloc/free processing to the memory profiler
        Scalene.__memory_profiler.process_malloc_free_samples(
            Scalene.__start_time,
            Scalene.__args,
            Scalene.__invalidate_mutex,
            Scalene.__invalidate_queue,
        )

    @staticmethod
    def _memcpy_sigqueue_processor(
        _signum: SignumType,
        frame: FrameType,
    ) -> None:
        """Process memcpy signals (used in a ScaleneSigQueue)."""
        if Scalene.__memory_profiler:
            Scalene.__memory_profiler.process_memcpy_samples()

    @staticmethod
    def _should_trace(filename: Filename, func: str) -> bool:
        """Return true if we should trace this filename and function.

        Delegates to ScaleneTracing module for the actual logic.
        Caching is handled by ScaleneTracing.should_trace via lru_cache.
        """
        return Scalene.__tracing.should_trace(filename, func)

    @staticmethod
    def start() -> None:
        """Initiate profiling."""
        if not Scalene.__initialized:
            print(
                "ERROR: Do not try to invoke `start` if you have not called Scalene using one of the methods\n"
                "in https://github.com/plasma-umass/scalene#using-scalene\n"
                "(The most likely issue is that you need to run your code with `scalene`, not `python`).",
                file=sys.stderr,
            )
            sys.exit(1)
        Scalene.__stats.start_clock()
        Scalene.enable_signals()
        Scalene.__start_time = time.monotonic_ns()

        # Start neuron monitor if using Neuron accelerator
        if (
            hasattr(Scalene.__accelerator, "start_monitor")
            and Scalene.__accelerator is not None
        ):
            Scalene.__accelerator.start_monitor()

        if Scalene.__args.memory:
            from scalene import pywhere  # type: ignore

            pywhere.set_scalene_done_false()

    @staticmethod
    def stop() -> None:
        """Complete profiling."""
        if Scalene.__args.memory:
            from scalene import pywhere  # type: ignore

            pywhere.set_scalene_done_true()

        Scalene._disable_signals()
        Scalene.__stats.stop_clock()
        if Scalene.__args.outfile:
            Scalene.__profile_filename = Filename(
                os.path.join(
                    os.path.dirname(Scalene.__args.outfile),
                    os.path.basename(Scalene.__profile_filename),
                )
            )

        if Scalene.__args.web and not Scalene.__args.cli and not Scalene.__is_child:
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
            if Scalene.__args.web and Scalene._in_jupyter():
                # Force JSON output to profile.json.
                Scalene.__args.json = True
                Scalene.__output.html = False
                Scalene.__output.output_file = Scalene.__profile_filename

    @staticmethod
    def _start_signal_handler(
        _signum: SignumType,
        _this_frame: FrameType | None,
    ) -> None:
        """Respond to a signal to start or resume profiling (--on).

        See scalene_parseargs.py.
        """
        for pid in Scalene.child_pids:
            Scalene.__signal_manager.send_signal_to_child(
                pid, Scalene.__signal_manager.get_signals().start_profiling_signal
            )
        Scalene.start()

    @staticmethod
    def _stop_signal_handler(
        _signum: SignumType,
        _this_frame: FrameType | None,
    ) -> None:
        """Respond to a signal to suspend profiling (--off).

        See scalene_parseargs.py.
        """
        for pid in Scalene.child_pids:
            Scalene.__signal_manager.send_signal_to_child(
                pid, Scalene.__signal_manager.get_signals().stop_profiling_signal
            )
        Scalene.stop()
        # Output the profile if `--outfile` was set to a file.
        if Scalene.__output.output_file:
            Scalene.output_profile(sys.argv)

    @staticmethod
    def _disable_signals(retry: bool = True) -> None:
        """Turn off the profiling signals."""
        if sys.platform == "win32":
            Scalene.__signal_manager.set_timer_signals(False)
            Scalene.__signal_manager.stop_timer_thread()
            Scalene.__signal_manager.stop_windows_memory_polling()
            Scalene.stop_signal_queues()
            return
        try:
            signals = Scalene.__signal_manager.get_signals()
            assert signals.cpu_timer_signal is not None
            Scalene.__orig_setitimer(signals.cpu_timer_signal, 0)
            for sig in [
                signals.malloc_signal,
                signals.free_signal,
                signals.memcpy_signal,
            ]:
                Scalene.__orig_signal(sig, signal.SIG_IGN)
            Scalene.stop_signal_queues()
        except Exception:
            # Retry just in case we get interrupted by one of our own signals.
            if retry:
                Scalene._disable_signals(retry=False)

    @staticmethod
    def _merge_profiler_timing(
        profiler: ScaleneLibraryProfiler,
        cpu_stats: dict[Any, dict[Any, float]],
        gpu_stats: dict[Any, dict[Any, float]],
    ) -> None:
        """Merge timing data from a library profiler into statistics.

        Args:
            profiler: The library profiler to merge data from.
            cpu_stats: The CPU timing statistics dict to merge into.
            gpu_stats: The GPU timing statistics dict to merge into.
        """
        # Merge CPU timing (convert from microseconds to seconds)
        for filename, line_times in profiler.line_times.items():
            for lineno, time_us in line_times.items():
                cpu_stats[Filename(filename)][LineNumber(lineno)] += time_us / 1_000_000
        # Merge GPU timing (convert from microseconds to seconds)
        for filename, line_times in profiler.gpu_line_times.items():
            for lineno, time_us in line_times.items():
                gpu_stats[Filename(filename)][LineNumber(lineno)] += time_us / 1_000_000

    @staticmethod
    def _merge_library_profiler_timing() -> None:
        """Merge timing data from all library profilers into statistics."""
        stats = Scalene.__stats.cpu_stats

        # Mapping from profiler type to (cpu_stats, gpu_stats)
        profiler_stats_map: dict[
            type, tuple[dict[Any, dict[Any, float]], dict[Any, dict[Any, float]]]
        ] = {
            TorchProfiler: (stats.torch_cpu_time, stats.torch_gpu_time),
            JaxProfiler: (stats.jax_cpu_time, stats.jax_gpu_time),
            TensorFlowProfiler: (stats.tensorflow_cpu_time, stats.tensorflow_gpu_time),
        }

        for profiler in Scalene.__library_profilers.get_profilers():
            try:
                profiler_type = type(profiler)
                if profiler_type in profiler_stats_map:
                    cpu_stats, gpu_stats = profiler_stats_map[profiler_type]
                    Scalene._merge_profiler_timing(profiler, cpu_stats, gpu_stats)

                # Handle PyTorch MPS-specific timing (Apple Silicon)
                if isinstance(profiler, TorchProfiler):
                    Scalene._handle_mps_timing(profiler)
            except Exception:
                # Silently handle any errors during profiler data merge
                pass

        # Clear torch profiler reference
        Scalene.__torch_profiler = None

    @staticmethod
    def _handle_mps_timing(profiler: TorchProfiler) -> None:
        """Handle Apple Silicon MPS GPU timing distribution.

        For Apple Silicon, distribute MPS GPU timing proportionally
        to lines based on their PyTorch CPU time. This enables
        per-process GPU timing on macOS where per-line GPU timing
        isn't available from torch.profiler.
        """
        if platform.system() != "Darwin":
            return
        if not hasattr(profiler, "get_mps_total_time"):
            return

        mps_time = profiler.get_mps_total_time()
        if mps_time <= 0:
            return

        # Calculate total torch CPU time across all lines
        total_torch_cpu_time = sum(
            time_us
            for line_times in profiler.line_times.values()
            for time_us in line_times.values()
        )

        # Distribute MPS time proportionally to torch CPU time
        if total_torch_cpu_time > 0:
            for filename, line_times in profiler.line_times.items():
                for lineno, time_us in line_times.items():
                    proportion = time_us / total_torch_cpu_time
                    Scalene.__stats.cpu_stats.torch_gpu_time[Filename(filename)][
                        LineNumber(lineno)
                    ] += (mps_time * proportion)

        # Update accelerator for aggregate stats
        if Scalene.__accelerator is not None and hasattr(
            Scalene.__accelerator, "set_torch_mps_time"
        ):
            Scalene.__accelerator.set_torch_mps_time(mps_time)

    @staticmethod
    def _exit_handler() -> None:
        """When we exit, disable all signals."""
        Scalene._disable_signals()
        # Delete the temporary directory.
        with contextlib.suppress(Exception):
            if not Scalene.__pid:
                Scalene.__python_alias_dir.cleanup()  # type: ignore
        with contextlib.suppress(Exception):
            os.remove(f"/tmp/scalene-malloc-lock{os.getpid()}")

    def profile_code(
        self,
        code: str,
        the_globals: dict[str, str],
        the_locals: dict[str, str],
        left: list[str],
    ) -> int:
        """Initiate execution and profiling."""
        if Scalene.__args.memory:
            from scalene import pywhere  # type: ignore

            pywhere.populate_struct()
            # Set legacy tracer mode if requested via command line
            if (
                hasattr(Scalene.__args, "use_legacy_tracer")
                and Scalene.__args.use_legacy_tracer
            ):
                set_use_legacy_tracer(True)
            # Set Python callback mode if requested via command line (disables C callback)
            if (
                hasattr(Scalene.__args, "use_python_callback")
                and Scalene.__args.use_python_callback
            ):
                set_use_python_callback(True)
            # Initialize the tracer for sys.monitoring support (Python 3.12+)
            initialize_tracer(
                Scalene.__last_profiled,
                Scalene.__invalidate_queue,
                Scalene._should_trace,
            )
        # Initialize library profilers (PyTorch, JAX, TensorFlow, etc.)
        # This allows accurate attribution of JIT-compiled code in these frameworks
        # Skip when gpu=False (i.e., --cpu-only mode) to avoid overhead
        if Scalene.__args.gpu:
            Scalene.__library_profilers.initialize()
            Scalene.__library_profilers.start_all()
            # Keep reference to torch profiler for MPS-specific handling
            for profiler in Scalene.__library_profilers.get_profilers():
                if isinstance(profiler, TorchProfiler):
                    Scalene.__torch_profiler = profiler
                    break

        # If --off is set, tell all children to not profile and stop profiling before we even start.
        if "off" not in Scalene.__args or not Scalene.__args.off:
            self.start()
        # Run the code being profiled.
        exit_status = 0
        try:
            exec(code, the_globals, the_locals)
        except SystemExit as se:
            # Intercept sys.exit and propagate the error code.
            exit_status = se.code if isinstance(se.code, int) else 1
        except KeyboardInterrupt:
            # Cleanly handle keyboard interrupts (quits execution and dumps the profile).
            print("Scalene execution interrupted.", file=sys.stderr)
        except Exception as e:
            print(f"{Scalene.__error_message}:\n", e, file=sys.stderr)
            traceback.print_exc()
            exit_status = 1

        finally:
            self.stop()
            # Stop all library profilers and merge timing data into statistics
            Scalene.__library_profilers.stop_all()
            Scalene._merge_library_profiler_timing()

            if Scalene.__args.memory:
                # Disable line tracing and clean up tracer resources
                disable_tracing()
                cleanup_tracer()
                pywhere.depopulate_struct()

        # Leaving here in case of reversion
        # sys.settrace(None)
        stats = Scalene.__stats
        last_file, last_line, _ = Scalene.last_profiled_tuple()
        stats.memory_stats.memory_malloc_count[last_file][last_line] += 1
        stats.memory_stats.memory_aggregate_footprint[last_file][
            last_line
        ] += stats.memory_stats.memory_current_highwater_mark[last_file][last_line]
        # If we've collected any samples, dump them.
        did_output = Scalene.output_profile(left)
        if not did_output:
            print(
                "Scalene: The specified code did not run for long enough to profile.",
                file=sys.stderr,
            )
            # Print out hints to explain why the above message may have been printed.
            if not Scalene.__args.profile_all:
                # if --profile-all was not specified, suggest it
                # as a way to profile otherwise excluded code
                # (notably Python libraries, which are excluded by
                # default).
                print(
                    "By default, Scalene only profiles code in the file executed and its subdirectories.",
                    file=sys.stderr,
                )
                print(
                    "To track the time spent in all files, use the `--profile-all` option.",
                    file=sys.stderr,
                )
            elif Scalene.__args.profile_only or Scalene.__args.profile_exclude:
                # if --profile-only or --profile-exclude were
                # specified, suggest that the patterns might be
                # excluding too many files. Collecting the
                # previously filtered out files could allow
                # suggested fixes (as in, remove foo because it
                # matches too many files).
                print(
                    "The patterns used in `--profile-only` or `--profile-exclude` may be filtering out too many files.",
                    file=sys.stderr,
                )
            else:
                # if none of the above cases hold, indicate that
                # Scalene can only profile code that runs for at
                # least one second or allocates some threshold
                # amount of memory.
                print(
                    "Scalene can only profile code that runs for at least one second or allocates at least 10MB.",
                    file=sys.stderr,
                )

            if not (
                did_output
                and Scalene.__args.web
                and not Scalene.__args.cli
                and not Scalene.__is_child
            ):
                return exit_status

        assert did_output
        if Scalene.__args.web or Scalene.__args.html:
            profile_filename = Scalene.__profile_filename
            if Scalene.__args.outfile:
                profile_filename = os.path.join(
                    os.path.dirname(Scalene.__args.outfile),
                    os.path.splitext(os.path.basename(Scalene.__args.outfile))[0]
                    + ".json",
                )
            generate_html(
                profile_fname=profile_filename,
                output_fname=(
                    Scalene.__profiler_html
                    if not Scalene.__args.outfile
                    else Scalene.__args.outfile
                ),
            )
        if Scalene._in_jupyter():
            from scalene.scalene_jupyter import ScaleneJupyter

            port = ScaleneJupyter.find_available_port(8181, 9000)
            if not port:
                print(
                    "Scalene error: could not find an available port.",
                    file=sys.stderr,
                )
            else:
                ScaleneJupyter.display_profile(port, Scalene.__profiler_html)
        else:
            if not Scalene.__args.no_browser:
                # Remove any interposition libraries from the environment before opening the browser.
                # See also scalene/scalene_preload.py
                old_dyld = os.environ.pop("DYLD_INSERT_LIBRARIES", "")
                old_ld = os.environ.pop("LD_PRELOAD", "")
                output_fname = f"{os.getcwd()}{os.sep}{Scalene.__profiler_html}"
                if Scalene.__pid == 0:
                    # Only open a browser tab for the parent.
                    dir = os.path.dirname(__file__)
                    subprocess.Popen(
                        [
                            Scalene.__orig_python,
                            f"{dir}{os.sep}launchbrowser.py",
                            output_fname,
                            str(scalene.scalene_config.SCALENE_PORT),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                # Restore them.
                os.environ.update(
                    {
                        "DYLD_INSERT_LIBRARIES": old_dyld,
                        "LD_PRELOAD": old_ld,
                    }
                )

        return exit_status

    @staticmethod
    def _process_args(args: argparse.Namespace) -> None:
        """Process all arguments."""
        Scalene.__args = ScaleneArguments(**vars(args))
        Scalene.__next_output_time = (
            time.perf_counter() + Scalene.__args.profile_interval
        )
        Scalene.__output.html = Scalene.__args.html
        if Scalene.__args.outfile:
            Scalene.__output.output_file = os.path.abspath(
                os.path.expanduser(Scalene.__args.outfile)
            )
        Scalene.__is_child = Scalene.__args.pid != 0
        # the pid of the primary profiler
        Scalene.__parent_pid = Scalene.__args.pid if Scalene.__is_child else os.getpid()
        # Don't profile the GPU if not enabled (i.e., either no options or --cpu and/or --memory, but no --gpu).
        if not Scalene.__args.gpu:
            Scalene.__output.gpu = False
            Scalene.__json.gpu = False

        # Update tracing module with new args
        if hasattr(Scalene, "_Scalene__tracing"):
            Scalene.__tracing.set_args(Scalene.__args)

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
        # Try to profile an accelerator if one is found and `--gpu` is selected / it's the default (see ScaleneArguments).
        if args.gpu:
            if platform.system() == "Darwin":
                from scalene.scalene_apple_gpu import ScaleneAppleGPU

                Scalene.__accelerator = ScaleneAppleGPU()
            else:
                from scalene.scalene_nvidia_gpu import ScaleneNVIDIAGPU

                Scalene.__accelerator = ScaleneNVIDIAGPU()

                if not Scalene.__accelerator.has_gpu():
                    # Failover to try Neuron
                    from scalene.scalene_neuron import ScaleneNeuron

                    Scalene.__accelerator = ScaleneNeuron()

            assert Scalene.__accelerator is not None
            Scalene.__output.gpu = Scalene.__accelerator.has_gpu()
            Scalene.__json.gpu = Scalene.__output.gpu
            Scalene.__json.gpu_device = Scalene.__accelerator.gpu_device()

        else:
            Scalene.__accelerator = None
            Scalene.__output.gpu = False
            Scalene.__json.gpu = False
            Scalene.__json.gpu_device = ""

        Scalene.set_initialized()
        Scalene.run_profiler(args, left)

    @staticmethod
    def _register_files_to_profile() -> None:
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
        args: argparse.Namespace, left: list[str], is_jupyter: bool = False
    ) -> None:
        """Set up and initiate profiling."""
        # Set up signal handlers for starting and stopping profiling.
        if is_jupyter:
            Scalene._set_in_jupyter()
        if not Scalene.__initialized:
            print(
                "ERROR: Do not try to manually invoke `run_profiler`.\n"
                "To invoke Scalene programmatically, see the usage noted in https://github.com/plasma-umass/scalene#using-scalene",
                file=sys.stderr,
            )
            sys.exit(1)
        if sys.platform != "win32":
            Scalene.__signal_manager.setup_lifecycle_signals(
                Scalene._start_signal_handler,
                Scalene._stop_signal_handler,
                Scalene._interruption_handler,
            )
        else:
            Scalene.__orig_signal(signal.SIGINT, Scalene._interruption_handler)
        did_preload = False if is_jupyter else ScalenePreload.setup_preload(args)

        # On Windows, load the libscalene DLL for memory profiling
        if sys.platform == "win32" and args.memory and not did_preload:
            try:
                from scalene.scalene_windows import get_windows_profiler

                win_profiler = get_windows_profiler()
                if not win_profiler.load_dll():
                    # Detailed error already printed by load_dll()
                    args.memory = False
                elif not win_profiler.initialize():
                    print(
                        "Warning: Failed to initialize Windows memory profiler. Memory profiling disabled.",
                        file=sys.stderr,
                    )
                    args.memory = False
            except Exception as e:
                print(
                    f"Warning: Windows memory profiler setup failed: {e}. Memory profiling disabled.",
                    file=sys.stderr,
                )
                args.memory = False

        if not did_preload:
            with contextlib.suppress(Exception):
                # If running in the background, print the PID.
                if os.getpgrp() != os.tcgetpgrp(sys.stdout.fileno()):
                    # In the background.
                    print(
                        f"Scalene now profiling process {os.getpid()}",
                        file=sys.stderr,
                    )
                    print(
                        f"  to disable profiling: python3 -m scalene.profile --off --pid {os.getpid()}",
                        file=sys.stderr,
                    )
                    print(
                        f"  to resume profiling:  python3 -m scalene.profile --on  --pid {os.getpid()}",
                        file=sys.stderr,
                    )
        Scalene.__stats.clear_all()
        sys.argv = left
        with contextlib.suppress(Exception):
            # Only set start method to fork if one hasn't been set yet
            # This respects user's choice (e.g., spawn on macOS)
            if (
                not is_jupyter
                and multiprocessing.get_start_method(allow_none=True) is None
            ):
                multiprocessing.set_start_method("fork")
        spec = None
        try:
            Scalene._process_args(args)
            progs = None
            exit_status = 0
            try:
                # Handle direct invocation of a string by executing the string and returning.
                if len(sys.argv) >= 2 and sys.argv[0] == "-c":
                    code_to_exec = sys.argv[1]
                    # Set sys.argv to match Python's native behavior:
                    # When running "python -c <code> <args>", sys.argv is ['-c'] + <args>
                    # The code string itself is not included in sys.argv.
                    # This is important for multiprocessing spawn mode, which checks
                    # sys.argv[1] == '--multiprocessing-fork'
                    sys.argv = [sys.argv[0]] + sys.argv[2:]
                    try:
                        exec(code_to_exec)
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
                with open(prog_name, encoding="utf-8") as prog_being_profiled:
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
                    if len(Scalene.__args.program_path) > 0:
                        Scalene.__program_path = Filename(
                            os.path.abspath(args.program_path)
                        )
                    else:
                        # Otherwise, use the invoked directory.
                        Scalene.__program_path = program_path

                    # Update tracing module with the program path
                    if hasattr(Scalene, "_Scalene__tracing"):
                        Scalene.__tracing.set_program_path(Scalene.__program_path)

                    # Grab local and global variables.
                    if Scalene.__args.memory:
                        Scalene._register_files_to_profile()
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
                        the_globals["__package__"] = name.rsplit(".", 1)[0]
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
            except (OSError, FileNotFoundError):
                if progs:
                    print(
                        f"Scalene: could not find input file {prog_name}",
                        file=sys.stderr,
                    )
                else:
                    print("Scalene: no input file specified.", file=sys.stderr)
                sys.exit(1)
        except SystemExit as e:
            exit_status = e.code if isinstance(e.code, int) else 1

        except StopJupyterExecution:
            pass
        except Exception:
            print(
                "Scalene failed to initialize.\n" + traceback.format_exc(),
                file=sys.stderr,
            )
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


# Handle @profile decorators.
# If Scalene encounters any functions decorated by @profile, it will
# only report stats for those functions.

builtins.profile = Scalene._profile  # type: ignore


def start() -> None:
    """Start profiling."""
    Scalene.start()


def stop() -> None:
    """Stop profiling."""
    Scalene.stop()


@contextlib.contextmanager
def enable_profiling() -> Generator[None, None, None]:
    """Contextmanager that starts and stops profiling"""
    start()
    yield
    stop()


if __name__ == "__main__":
    Scalene.main()
