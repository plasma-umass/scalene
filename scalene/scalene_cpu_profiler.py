"""CPU profiling logic for Scalene."""

from __future__ import annotations

import math
import sys
from typing import TYPE_CHECKING, Any, Callable

from scalene.runningstats import RunningStats
from scalene.scalene_funcutils import ScaleneFuncUtils
from scalene.scalene_statistics import (
    ByteCodeIndex,
    Filename,
    LineNumber,
    PerThreadNativeStack,
    ScaleneStatistics,
)
from scalene.scalene_utility import (
    _main_thread_id,
    add_async_await_run,
    add_combined_stack,
    add_stack,
    enter_function_meta,
    get_python_thread_id_for_native,
)
from scalene.time_info import TimeInfo

if TYPE_CHECKING:
    from types import FrameType


# Arrival-to-handler delay above which a signal-path sample counts as native.
# Measured (macOS): pure Python 10 us median, 1% above 0.05 ms; C calls and
# operators running C 2-40 ms, 97-100% above 0.2 ms.
#
# Windows (native timer thread, see start_cpu_timer_thread()) uses 0.05 ms:
# pure Python there is deferred 3-11 us (p99, also with every core busy),
# and before Python 3.11, which checks for signals after almost every
# bytecode, samples in the last 0.2 ms of a short operator (numpy `a *= x`)
# made 3.9 report numpy loops as half Python. Above 0.05 ms: 98% of numpy
# operator samples vs 18% of them below 0.2 ms.
NATIVE_DEFERRAL_THRESHOLD = 0.00005 if sys.platform == "win32" else 0.0002


class ScaleneCPUProfiler:
    """Handles CPU profiling sample processing."""

    def __init__(
        self,
        stats: ScaleneStatistics,
        available_cpus: int,
        use_virtual_time: bool,
        thread_sampled: bool = False,
    ) -> None:
        """Initialize the CPU profiler.

        Args:
            stats: The statistics object to update with CPU samples.
            available_cpus: Number of available CPUs for utilization calculations.
            use_virtual_time: Whether we're using virtual time (SIGVTALRM) or
                wall clock time (SIGALRM) for CPU sampling.
            thread_sampled: True when CPU samples are produced by a background
                helper thread on a wall-clock cadence rather than a timer
                signal (Apple SME path, issue #1056). In that mode there is no
                virtual-timer deferral to exploit, so Python-vs-C time is
                attributed purely from the bytecode at f_lasti (a CALL* opcode
                means we're in a native call) — exactly as wall-clock mode
                already does, regardless of the --use-virtual-time flag.
        """
        self._stats = stats
        self._available_cpus = available_cpus
        self._use_virtual_time = use_virtual_time
        self._thread_sampled = thread_sampled
        # Function of the main thread's sampled line, for lines that get
        # time without being sampled themselves (see _update_main_thread_stats).
        self._main_function: Filename | None = None

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
        native_drains: list[tuple[int, ...]] | None = None,
        suspended_async_tasks: list[Any] | None = None,
        perthread_drains: list[PerThreadNativeStack] | None = None,
        signal_deferral: float | None = None,
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
            native_drains: Native (C/C++) stacks captured by the C-level
                signal-handler unwinder during this sampling pass; used to
                build stitched Python+native stacks (combined_stacks).
            perthread_drains: Per-thread native stacks from worker threads.
                List of (thread_id, (ip, ip, ...)) tuples.
            signal_deferral: wall seconds between the timer signal's arrival
                (recorded by a C-level handler) and this sample, or None.
                CPython defers the Python-level handler only while C code
                runs: ~10 us for pure Python, milliseconds for C calls and
                for operators running C (numpy, list concatenation).
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

        # Clamp to [0, 1]: measurement noise between user and wallclock
        # accounting can push the ratio slightly above 1.0 on multi-core systems.
        core_utilization = min(cpu_utilization / self._available_cpus, 1.0)
        if cpu_utilization > 1.0:
            cpu_utilization = 1.0
            elapsed.wallclock = elapsed.user

        # Handle NaN GPU load
        if math.isnan(gpu_load):
            gpu_load = 0.0
        assert 0.0 <= gpu_load <= 1.0

        gpu_time = gpu_load * elapsed.wallclock
        self._stats.gpu_stats.total_gpu_samples += gpu_time

        # Compute Python vs C (native) time attribution.
        #
        # The interval-based formula assumes python_time ≈ last_cpu_interval
        # and c_time is the "excess" CPU time beyond that (from deferred signals
        # during C calls). This works when signals are deferred, but when the
        # signal happens to fire while Python is running, c_time ≈ 0 even if
        # significant C time occurred earlier in the interval.
        #
        # In wall clock mode, we augment this with instruction-based detection:
        # if we're at a CALL instruction (just returned from C), we attribute
        # ALL time to native since the signal was likely deferred during the call.
        python_time = last_cpu_interval
        c_time = max(elapsed.virtual - python_time, 0)
        total_time = python_time + c_time
        if signal_deferral is not None and not self._thread_sampled:
            # Signal path with an arrival timestamp. Classify the whole
            # sample by what was running when the signal arrived: native if
            # CPython had to defer the handler (C code was running), else
            # Python. Unlike "time beyond the interval is native", this
            # ignores OS timer leeway (2-3x the interval on macOS CI
            # runners), and it catches operators running C (numpy `a @ b`,
            # `big_list + big_list`), which the CALL test can't see. The
            # total is unchanged.
            if signal_deferral > NATIVE_DEFERRAL_THRESHOLD:
                python_time, c_time = 0.0, total_time
            else:
                python_time, c_time = total_time, 0.0
        if self._thread_sampled:
            # A sampler thread (Windows, Apple SME) is late whenever it waits
            # for the GIL, even while the main thread runs pure Python, so
            # lateness says nothing about native code here. Treat the whole
            # sample as Python; the CALL*-bytecode test below moves it to
            # native when the main thread is in (or just returned from) a
            # native call.
            python_time = total_time
            c_time = 0.0

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
        main_thread_sleeping = is_thread_sleeping[_main_thread_id]

        if stacks_enabled and not main_thread_sleeping:
            add_stack(
                main_thread_frame,
                should_trace,
                self._stats.stacks,
                average_python_time,
                average_c_time,
                average_cpu_time,
            )
            if native_drains:
                # Async-aware path: when this sample landed inside the
                # event loop with coroutines suspended, the raw stack is
                # misleading (the main thread is blocked in
                # epoll/select while no task is using CPU). Mirror the
                # existing per-line "await %" attribution by emitting
                # one synthetic stitched run per suspended task at its
                # await point. Falls through to the regular combined
                # stack path when no tasks are suspended.
                wrote_async_runs = False
                if suspended_async_tasks:
                    wrote_async_runs = add_async_await_run(
                        suspended_async_tasks,
                        should_trace,
                        self._stats.combined_stacks,
                        self._stats,
                        timeline=self._stats.combined_stacks_timeline,
                        timeline_cap=self._stats.combined_stacks_timeline_max_runs,
                        timestamp=now.wallclock,
                        thread_id=_main_thread_id,
                    )
                if not wrote_async_runs:
                    add_combined_stack(
                        main_thread_frame,
                        should_trace,
                        native_drains,
                        self._stats.combined_stacks,
                        self._stats,
                        timeline=self._stats.combined_stacks_timeline,
                        timeline_cap=self._stats.combined_stacks_timeline_max_runs,
                        timestamp=now.wallclock,
                        thread_id=_main_thread_id,
                    )

        enter_function_meta(main_thread_frame, should_trace, self._stats)
        fname = Filename(main_thread_frame.f_code.co_filename)
        lineno = (
            LineNumber(main_thread_frame.f_lineno)
            if main_thread_frame.f_lineno is not None
            else LineNumber(main_thread_frame.f_code.co_firstlineno)
        )
        self._main_function = self._stats.function_map[fname].get(lineno)

        # A sampler thread (thread_sampled) only gets the GIL from Python code
        # at a GIL handoff point (RESUME, a loop back-edge, or after a call;
        # Python 3.11+). If it finds the main thread stopped anywhere else,
        # the main thread released the GIL inside that instruction: it is
        # running native code (e.g. a numpy operator doing BLAS work), so
        # the whole sample is native, on this line.
        released_gil_mid_instruction = (
            self._thread_sampled
            and sys.version_info >= (3, 11)
            and not ScaleneFuncUtils.is_gil_handoff_point(
                main_thread_frame.f_code,
                ByteCodeIndex(main_thread_frame.f_lasti),
            )
        )

        if not is_thread_sleeping[_main_thread_id]:
            # Check for loop-top sampling bias.  CPython checks eval_breaker
            # at JUMP_BACKWARD, so signals are preferentially delivered at the
            # first body line of tight loops.  When detected, redistribute the
            # sample evenly across all loop lines.
            loop_lines = ScaleneFuncUtils.get_loop_body_lines(
                main_thread_frame.f_code, lineno
            )
            if released_gil_mid_instruction:
                self._update_main_thread_stats(
                    fname,
                    lineno,
                    now,
                    0.0,
                    average_cpu_time,
                    average_cpu_time,
                    cpu_utilization,
                    core_utilization,
                    gpu_load,
                    gpu_mem_used,
                    elapsed,
                )
            elif loop_lines is not None and len(loop_lines) > 1:
                n = len(loop_lines)
                for ll in loop_lines:
                    self._update_main_thread_stats(
                        fname,
                        LineNumber(ll),
                        now,
                        average_python_time / n,
                        average_c_time / n,
                        average_cpu_time / n,
                        cpu_utilization,
                        core_utilization,
                        gpu_load,
                        gpu_mem_used,
                        elapsed,
                        gpu_weight=1.0 / n,
                    )
            else:
                # Determine Python vs C time attribution.
                #
                # The interval-based formula gives us:
                #   python_time = last_cpu_interval (timer interval)
                #   c_time = elapsed.virtual - python_time (excess from deferral)
                #
                # When c_time > 0, the signal was deferred during a C call, so
                # attribute C time to the preceding CALL line (if found).
                #
                # In wall clock mode, we also check if we're currently AT a CALL
                # instruction. If so, the signal was likely deferred during that
                # call, and ALL time (including python_time) should go to native.
                # This handles the case where elapsed.virtual ≈ last_cpu_interval
                # (c_time ≈ 0) but we're still returning from C code.
                #
                # The thread-sampled (Apple SME) path always uses this
                # bytecode-based test: it has no virtual-timer deferral to
                # measure c_time from, so the CALL* opcode at f_lasti is the
                # sole signal for "this sample landed in a native call". This
                # is the same classifier already used for worker threads.
                is_at_call = ScaleneFuncUtils.is_call_function(
                    main_thread_frame.f_code,
                    ByteCodeIndex(main_thread_frame.f_lasti),
                )

                use_call_attribution = (
                    not self._use_virtual_time or self._thread_sampled
                )
                if use_call_attribution and is_at_call:
                    # At a CALL instruction: attribute all time to native on
                    # this line. The sample landed inside the C call, so even
                    # python_time was spent in C, not Python.
                    self._update_main_thread_stats(
                        fname,
                        lineno,
                        now,
                        0.0,
                        average_cpu_time,
                        average_cpu_time,
                        cpu_utilization,
                        core_utilization,
                        gpu_load,
                        gpu_mem_used,
                        elapsed,
                    )
                elif average_c_time > 0:
                    # Signal was deferred (c_time > 0). Find the preceding CALL
                    # line to attribute C time correctly.
                    preceding_call_line = ScaleneFuncUtils.find_preceding_call_line(
                        main_thread_frame.f_code,
                        ByteCodeIndex(main_thread_frame.f_lasti),
                    )
                    if (
                        preceding_call_line is not None
                        and LineNumber(preceding_call_line) != lineno
                    ):
                        # Split: C time on the CALL line, Python time on f_lineno.
                        self._update_main_thread_stats(
                            fname,
                            LineNumber(preceding_call_line),
                            now,
                            0.0,
                            average_c_time,
                            average_c_time,
                            cpu_utilization,
                            core_utilization,
                            gpu_load,
                            gpu_mem_used,
                            elapsed,
                        )
                        self._update_main_thread_stats(
                            fname,
                            lineno,
                            now,
                            average_python_time,
                            0.0,
                            average_python_time,
                            cpu_utilization,
                            core_utilization,
                            gpu_load,
                            gpu_mem_used,
                            elapsed,
                        )
                    else:
                        # CALL is on the same line or not found; keep together.
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
                else:
                    # No C time detected; attribute as computed.
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

        # Build a mapping from Python thread ID to native stacks for this sample
        perthread_native_by_python_tid: dict[int, list[tuple[int, ...]]] = {}
        if perthread_drains:
            for entry in perthread_drains:
                python_tid = get_python_thread_id_for_native(entry.thread_id)
                if python_tid is not None:
                    perthread_native_by_python_tid.setdefault(python_tid, []).append(
                        entry.stack
                    )

        # Process other threads
        for frame, tident, orig_frame in new_frames:
            if frame == main_thread_frame:
                continue

            # Skip stacks for sleeping threads - they're not doing CPU work
            thread_sleeping = is_thread_sleeping[tident]
            if not thread_sleeping:
                add_stack(
                    frame,
                    should_trace,
                    self._stats.stacks,
                    average_python_time,
                    average_c_time,
                    average_cpu_time,
                )

                # If we have per-thread native stacks for this thread, build combined stacks
                if stacks_enabled and tident in perthread_native_by_python_tid:
                    thread_native_drains = perthread_native_by_python_tid[tident]
                    add_combined_stack(
                        frame,
                        should_trace,
                        thread_native_drains,
                        self._stats.combined_stacks,
                        self._stats,
                        timeline=self._stats.combined_stacks_timeline,
                        timeline_cap=self._stats.combined_stacks_timeline_max_runs,
                        timestamp=now.wallclock,
                        thread_id=tident,
                    )

            fname = Filename(frame.f_code.co_filename)
            lineno = (
                LineNumber(frame.f_lineno)
                if frame.f_lineno is not None
                else LineNumber(frame.f_code.co_firstlineno)
            )
            enter_function_meta(frame, should_trace, self._stats)

            if thread_sleeping:
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
        gpu_weight: float = 1.0,
    ) -> None:
        """Update statistics for the main thread."""
        # Time can land on lines other than the sampled one, all in the
        # sampled frame's code: spread across a loop body, or moved to the
        # preceding call. function_map only knows lines that were sampled,
        # and function totals sum only those, so register these lines too.
        # Otherwise a loop's unsampled body lines (in a tight loop, every
        # line but the loop header) drop out of its function's total (#1131).
        fn_lines = self._stats.function_map[fname]
        if self._main_function is not None and lineno not in fn_lines:
            fn_lines[lineno] = self._main_function
        cpu_stats = self._stats.cpu_stats
        gpu_stats = self._stats.gpu_stats

        cpu_stats.cpu_samples_list[fname][lineno].append(now.wallclock)
        cpu_stats.cpu_samples_python[fname][lineno] += average_python_time
        cpu_stats.cpu_samples_c[fname][lineno] += average_c_time
        cpu_stats.cpu_samples[fname] += average_cpu_time
        cpu_stats.cpu_utilization[fname][lineno].push(cpu_utilization)
        cpu_stats.core_utilization[fname][lineno].push(core_utilization)

        gpu_stats.gpu_samples[fname][lineno] += (
            gpu_load * elapsed.wallclock * gpu_weight
        )
        gpu_stats.n_gpu_samples[fname][lineno] += elapsed.wallclock * gpu_weight
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
