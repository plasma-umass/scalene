"""
CPU profiling functionality for Scalene profiler.

This module extracts CPU profiling functionality from the main Scalene class
to improve code organization and reduce complexity.
"""

import math
import signal
import sys
import time
from typing import Any, Dict, Optional

from scalene.scalene_signals import SignumType
from scalene.time_info import TimeInfo, get_times
from scalene.scalene_utility import compute_frames_to_record

if sys.version_info >= (3, 11):
    from types import FrameType
else:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from types import FrameType
    else:
        FrameType = Any


class ScaleneCPUProfiler:
    """Handles CPU profiling functionality for Scalene."""

    def __init__(self, stats, signal_manager, accelerator, client_timer, orig_raise_signal, is_thread_sleeping):
        """Initialize the CPU profiler."""
        self.__stats = stats
        self.__signal_manager = signal_manager
        self.__accelerator = accelerator
        self.__client_timer = client_timer
        self.__orig_raise_signal = orig_raise_signal
        self.__is_thread_sleeping = is_thread_sleeping
        self.__last_signal_time = TimeInfo()
        self.__last_cpu_interval = 0.0

    @staticmethod
    def generate_exponential_sample(scale: float) -> float:
        """Generate an exponentially distributed sample."""
        import math
        import random

        u = random.random()  # Uniformly distributed random number between 0 and 1
        return -scale * math.log(1 - u)

    def sample_cpu_interval(self, cpu_sampling_rate: float) -> float:
        """Return the CPU sampling interval."""
        # Sample an interval from an exponential distribution.
        self.__last_cpu_interval = self.generate_exponential_sample(cpu_sampling_rate)
        return self.__last_cpu_interval

    def cpu_signal_handler(
        self,
        signum: SignumType,
        this_frame: Optional[FrameType],
        should_trace_func,
        process_cpu_sample_func,
        sample_cpu_interval_func,
        restart_timer_func,
    ) -> None:
        """Handle CPU signals."""
        try:
            # Get current time stats.
            now = TimeInfo()
            now.sys, now.user = get_times()
            now.virtual = time.process_time()
            now.wallclock = time.perf_counter()
            if (
                self.__last_signal_time.virtual == 0
                or self.__last_signal_time.wallclock == 0
            ):
                # Initialization: store values and update on the next pass.
                self.__last_signal_time = now
                if sys.platform != "win32":
                    next_interval = sample_cpu_interval_func()
                    restart_timer_func(next_interval)
                return

            if self.__accelerator:
                (gpu_load, gpu_mem_used) = self.__accelerator.get_stats()
            else:
                (gpu_load, gpu_mem_used) = (0.0, 0.0)

            # Process this CPU sample.
            process_cpu_sample_func(
                signum,
                compute_frames_to_record(should_trace_func),
                now,
                gpu_load,
                gpu_mem_used,
                self.__last_signal_time,
                self.__is_thread_sleeping,
            )
            elapsed = now.wallclock - self.__last_signal_time.wallclock
            # Store the latest values as the previously recorded values.
            self.__last_signal_time = now
            # Restart the timer while handling any timers set by the client.
            next_interval = sample_cpu_interval_func()
            if sys.platform != "win32":
                if self.__client_timer.is_set:
                    (
                        should_raise,
                        remaining_time,
                    ) = self.__client_timer.yield_next_delay(elapsed)
                    if should_raise:
                        self.__orig_raise_signal(signal.SIGUSR1)
                    # NOTE-- 0 will only be returned if the 'seconds' have elapsed
                    # and there is no interval
                    to_wait: float
                    if remaining_time > 0:
                        to_wait = min(remaining_time, next_interval)
                    else:
                        to_wait = next_interval
                        self.__client_timer.reset()
                    restart_timer_func(to_wait)
                else:
                    restart_timer_func(next_interval)
        finally:
            if sys.platform == "win32":
                restart_timer_func(next_interval)

    def windows_timer_loop(self, windows_queue, timer_signals) -> None:
        """Timer loop for Windows CPU profiling."""
        while timer_signals:
            time.sleep(0.01)
            windows_queue.put(None)