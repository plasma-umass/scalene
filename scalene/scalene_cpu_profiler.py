"""CPU profiling logic for Scalene."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable

from scalene.runningstats import RunningStats
from scalene.scalene_funcutils import ScaleneFuncUtils
from scalene.scalene_statistics import (
    ByteCodeIndex,
    Filename,
    LineNumber,
    ScaleneStatistics,
)
from scalene.scalene_utility import _main_thread_id, add_stack, enter_function_meta
from scalene.time_info import TimeInfo

if TYPE_CHECKING:
    from types import FrameType


class ScaleneCPUProfiler:
    """Handles CPU profiling sample processing."""

    def __init__(self, stats: ScaleneStatistics, available_cpus: int) -> None:
        """Initialize the CPU profiler.

        Args:
            stats: The statistics object to update with CPU samples.
            available_cpus: Number of available CPUs for utilization calculations.
        """
        self._stats = stats
        self._available_cpus = available_cpus

    def process_cpu_sample(
        self,
        new_frames: list[tuple[FrameType, int, FrameType]],
        now: TimeInfo,
        gpu_load: float,
        gpu_mem_used: float,
        prev: TimeInfo,
        is_thread_sleeping: dict[int, bool],
        should_trace: Callable[[Filename, str], bool],
        last_cpu_interval: float,
        stacks_enabled: bool,
    ) -> None:
        """Handle interrupts for CPU profiling.

        Args:
            new_frames: List of (frame, thread_id, original_frame) tuples.
            now: Current time information.
            gpu_load: Current GPU load (0.0-1.0).
            gpu_mem_used: Current GPU memory usage.
            prev: Previous time information.
            is_thread_sleeping: Dict mapping thread IDs to sleep status.
            should_trace: Function to check if a file/function should be traced.
            last_cpu_interval: The last CPU sampling interval.
            stacks_enabled: Whether stack collection is enabled.
        """
        if not new_frames:
            return

        elapsed = now - prev

        # Skip samples with negative values (can occur in multi-process settings)
        if any([elapsed.virtual < 0, elapsed.wallclock < 0, elapsed.user < 0]):
            return

        # Calculate CPU utilization
        cpu_utilization = 0.0
        if elapsed.wallclock != 0:
            cpu_utilization = elapsed.user / elapsed.wallclock

        core_utilization = cpu_utilization / self._available_cpus
        if cpu_utilization > 1.0:
            cpu_utilization = 1.0
            elapsed.wallclock = elapsed.user

        # Handle NaN GPU load
        if math.isnan(gpu_load):
            gpu_load = 0.0
        assert 0.0 <= gpu_load <= 1.0

        gpu_time = gpu_load * elapsed.wallclock
        self._stats.gpu_stats.total_gpu_samples += gpu_time

        python_time = last_cpu_interval
        c_time = max(elapsed.virtual - python_time, 0)
        total_time = python_time + c_time

        # Count non-sleeping frames
        total_frames = sum(
            not is_thread_sleeping[tident] for frame, tident, orig_frame in new_frames
        )
        if total_frames == 0:
            total_frames = 1

        normalized_time = total_time / total_frames
        average_python_time = python_time / total_frames
        average_c_time = c_time / total_frames
        average_cpu_time = (python_time + c_time) / total_frames

        # Process main thread
        main_thread_frame = new_frames[0][0]

        if stacks_enabled:
            add_stack(
                main_thread_frame,
                should_trace,
                self._stats.stacks,
                average_python_time,
                average_c_time,
                average_cpu_time,
            )

        enter_function_meta(main_thread_frame, should_trace, self._stats)
        fname = Filename(main_thread_frame.f_code.co_filename)
        lineno = (
            LineNumber(main_thread_frame.f_lineno)
            if main_thread_frame.f_lineno is not None
            else LineNumber(main_thread_frame.f_code.co_firstlineno)
        )

        if not is_thread_sleeping[_main_thread_id]:
            self._update_main_thread_stats(
                fname,
                lineno,
                now,
                average_python_time,
                average_c_time,
                average_cpu_time,
                cpu_utilization,
                core_utilization,
                gpu_load,
                gpu_mem_used,
                elapsed,
            )

        # Process other threads
        for frame, tident, orig_frame in new_frames:
            if frame == main_thread_frame:
                continue

            add_stack(
                frame,
                should_trace,
                self._stats.stacks,
                average_python_time,
                average_c_time,
                average_cpu_time,
            )

            fname = Filename(frame.f_code.co_filename)
            lineno = (
                LineNumber(frame.f_lineno)
                if frame.f_lineno is not None
                else LineNumber(frame.f_code.co_firstlineno)
            )
            enter_function_meta(frame, should_trace, self._stats)

            if is_thread_sleeping[tident]:
                continue

            self._update_thread_stats(
                fname,
                lineno,
                orig_frame,
                normalized_time,
                cpu_utilization,
                core_utilization,
            )

        # Cleanup
        del new_frames[:]
        del new_frames
        del is_thread_sleeping
        self._stats.cpu_stats.total_cpu_samples += total_time

    def _update_main_thread_stats(
        self,
        fname: Filename,
        lineno: LineNumber,
        now: TimeInfo,
        average_python_time: float,
        average_c_time: float,
        average_cpu_time: float,
        cpu_utilization: float,
        core_utilization: float,
        gpu_load: float,
        gpu_mem_used: float,
        elapsed: TimeInfo,
    ) -> None:
        """Update statistics for the main thread."""
        cpu_stats = self._stats.cpu_stats
        gpu_stats = self._stats.gpu_stats

        cpu_stats.cpu_samples_list[fname][lineno].append(now.wallclock)
        cpu_stats.cpu_samples_python[fname][lineno] += average_python_time
        cpu_stats.cpu_samples_c[fname][lineno] += average_c_time
        cpu_stats.cpu_samples[fname] += average_cpu_time
        cpu_stats.cpu_utilization[fname][lineno].push(cpu_utilization)
        cpu_stats.core_utilization[fname][lineno].push(core_utilization)

        gpu_stats.gpu_samples[fname][lineno] += gpu_load * elapsed.wallclock
        gpu_stats.n_gpu_samples[fname][lineno] += elapsed.wallclock
        gpu_stats.gpu_mem_samples[fname][lineno].push(gpu_mem_used)

    def _update_thread_stats(
        self,
        fname: Filename,
        lineno: LineNumber,
        orig_frame: FrameType,
        normalized_time: float,
        cpu_utilization: float,
        core_utilization: float,
    ) -> None:
        """Update statistics for non-main threads."""
        cpu_stats = self._stats.cpu_stats

        # Check if the original caller is stuck inside a call
        if ScaleneFuncUtils.is_call_function(
            orig_frame.f_code,
            ByteCodeIndex(orig_frame.f_lasti),
        ):
            # Attribute time to native
            cpu_stats.cpu_samples_c[fname][lineno] += normalized_time
        else:
            # Attribute time to Python
            cpu_stats.cpu_samples_python[fname][lineno] += normalized_time

        cpu_stats.cpu_samples[fname] += normalized_time
        cpu_stats.cpu_utilization[fname][lineno].push(cpu_utilization)
        cpu_stats.core_utilization[fname][lineno].push(core_utilization)
