"""
Utility methods extracted from Scalene profiler for better modularity.

This module contains various utility and helper methods that were previously
in the main Scalene class.
"""

import contextlib
import functools
import gc
import inspect
import os
import signal
import sys
import threading
from types import FrameType
from typing import Any, Dict, Generator, List, Optional, Set, Tuple

from scalene.scalene_statistics import Filename, LineNumber, ByteCodeIndex
from scalene.scalene_utility import enter_function_meta, on_stack


class ScaleneUtils:
    """Utility methods for Scalene profiler."""

    @staticmethod
    def enable_signals(
        malloc_signal_handler,
        free_signal_handler,
        memcpy_signal_handler,
        term_signal_handler,
        cpu_signal_handler,
        signal_manager,
        sample_cpu_interval_func,
    ) -> None:
        """Set up the signal handlers to handle interrupts for profiling and start the
        timer interrupts."""
        next_interval = sample_cpu_interval_func()
        signal_manager.enable_signals(
            malloc_signal_handler,
            free_signal_handler,
            memcpy_signal_handler,
            term_signal_handler,
            cpu_signal_handler,
            next_interval,
        )

    @staticmethod
    def disable_signals(signal_manager, retry: bool = True) -> None:
        """Turn off the signals."""
        try:
            signal_manager.disable_signals()
        except Exception:
            # Could be a ValueError (signal only works in main thread) or
            # even an OSError in certain contexts.
            if retry:
                pass

    @staticmethod 
    def malloc_signal_handler(
        signum,
        this_frame: Optional[FrameType],
        args,
        should_trace_func,
        last_profiled_tuple_func,
        update_profiled_func,
        last_profiled_ref,
        alloc_sigq,
    ) -> None:
        """Handle allocation signals."""
        if not args.memory:
            # This should never happen, but we fail gracefully.
            return
        from scalene import pywhere  # type: ignore

        if this_frame:
            # Use a dummy stats object since we don't have access to it here
            enter_function_meta(this_frame, should_trace_func, None)
        # Walk the stack till we find a line of code in a file we are tracing.
        found_frame = False
        f = this_frame
        while f:
            if found_frame := should_trace_func(
                f.f_code.co_filename, f.f_code.co_name
            ):
                break
            f = f.f_back
        if not found_frame:
            return
        assert f
        # Start tracing until we execute a different line of
        # code in a file we are tracking.
        # First, see if we have now executed a different line of code.
        # If so, increment.

        invalidated = pywhere.get_last_profiled_invalidated()
        (fname, lineno, lasti) = last_profiled_tuple_func()
        if not invalidated and this_frame and not (on_stack(this_frame, fname, lineno)):
            update_profiled_func()
        pywhere.set_last_profiled_invalidated_false()
        # In the setprofile callback, we rely on
        # __last_profiled always having the same memory address.
        # This is an optimization to not have to traverse the Scalene profiler
        # object's dictionary every time we want to update the last profiled line.
        #
        # A previous change to this code set Scalene.__last_profiled = [fname, lineno, lasti],
        # which created a new list object and set the __last_profiled attribute to the new list. This
        # made the object held in `pywhere.cpp` out of date, and caused the profiler to not update the last profiled line.
        last_profiled_ref[:] = [
            Filename(f.f_code.co_filename),
            LineNumber(f.f_lineno),
            ByteCodeIndex(f.f_lasti),
        ]
        alloc_sigq.put([0])
        pywhere.enable_settrace(this_frame)
        del this_frame

    @staticmethod
    def free_signal_handler(
        signum,
        this_frame: Optional[FrameType],
        args,
        alloc_sigq,
    ) -> None:
        """Handle free signals."""
        if not args.memory:
            return
        alloc_sigq.put([1])

    @staticmethod
    def memcpy_signal_handler(
        signum,
        this_frame: Optional[FrameType],
        args,
        memcpy_sigq,
    ) -> None:
        """Handle memcpy signals."""
        if not args.memory:
            return
        memcpy_sigq.put((signum, this_frame))

    @staticmethod
    def term_signal_handler(
        signum,
        this_frame: Optional[FrameType],
        sigterm_exit_code: int,
    ) -> None:
        """Handle sigterm signals."""
        sys.exit(sigterm_exit_code)

    @staticmethod
    def print_stacks(stats) -> None:
        """Print stack information."""
        for f in stats.stacks:
            print(f)

    @staticmethod
    @functools.cache
    def get_line_info(
        fname: Filename,
        functions_to_profile: Dict[Filename, Set[Any]],
    ) -> Generator[Tuple[list[str], int], None, None]:
        """Get line information for profiled functions."""
        line_info = (
            inspect.getsourcelines(fn) for fn in functions_to_profile[fname]
        )
        return line_info

    @staticmethod
    def profile_this_code(
        fname: Filename, 
        lineno: LineNumber,
        files_to_profile: Set[Filename],
        functions_to_profile: Dict[Filename, Set[Any]],
    ) -> bool:
        """When using @profile, only profile files & lines that have been decorated."""
        if not files_to_profile:
            return True
        if fname not in files_to_profile:
            return False
        # Now check to see if it's the right line range.
        line_info = ScaleneUtils.get_line_info(fname, functions_to_profile)
        found_function = any(
            line_start <= lineno < line_start + len(lines)
            for (lines, line_start) in line_info
        )
        return found_function

    @staticmethod
    def alloc_sigqueue_processor(
        memory_profiler,
        stats,
        args,
        invalidate_mutex,
        invalidate_queue,
        start_time,
    ) -> None:
        """Handle interrupts for memory profiling (mallocs and frees)."""
        # Process all the messages in the queue.
        memory_profiler.process_malloc_free_samples(
            start_time,
            args,
            invalidate_mutex,
            invalidate_queue,
        )

    @staticmethod
    def memcpy_sigqueue_processor(
        memory_profiler,
    ) -> None:
        """Process memcpy signals (used in a ScaleneSigQueue)."""
        # Process all the messages in the queue.
        memory_profiler.process_memcpy_samples()

    @staticmethod
    def start_signal_queues(signal_manager) -> None:
        """Start the signal processing queues (i.e., their threads)."""
        signal_manager.start_signal_queues()

    @staticmethod
    def stop_signal_queues(signal_manager) -> None:
        """Stop the signal processing queues."""
        signal_manager.stop_signal_queues()

    @staticmethod
    def clear_metrics(stats) -> None:
        """Clear the various collected metrics."""
        stats.clear_all()
        gc.collect()

    @staticmethod
    def add_child_pid(child_pids: Set[int], pid: int) -> None:
        """Add a child PID to the set of children being managed."""
        child_pids.add(pid)

    @staticmethod
    def remove_child_pid(child_pids: Set[int], pid: int) -> None:
        """Remove a child PID from the set of children being managed."""
        child_pids.discard(pid)

    @staticmethod
    def exit_handler(
        stop_func,
        is_child: bool,
        memory_profiler,
    ) -> None:
        """When we exit, disable signals."""
        stop_func()
        if not is_child and memory_profiler:
            memory_profiler.cleanup()

    @staticmethod
    def set_thread_sleeping(is_thread_sleeping: Dict[int, bool], tid: int) -> None:
        """Indicate the given thread is sleeping."""
        is_thread_sleeping[tid] = True

    @staticmethod  
    def reset_thread_sleeping(is_thread_sleeping: Dict[int, bool], tid: int) -> None:
        """Indicate the given thread is not sleeping."""
        is_thread_sleeping[tid] = False