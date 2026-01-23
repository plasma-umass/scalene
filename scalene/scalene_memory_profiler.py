"""
Memory profiling processor for Scalene profiler.

This module extracts memory profiling functionality from the main Scalene class
to improve code organization and reduce complexity.
"""

import contextlib
import os
import threading
import time
from typing import List, Optional, Tuple

import scalene.scalene_config
from scalene.scalene_arguments import ScaleneArguments
from scalene.scalene_mapfile import ScaleneMapFile
from scalene.scalene_statistics import (
    Address,
    ByteCodeIndex,
    Filename,
    LineNumber,
    MemcpyProfilingSample,
    ProfilingSample,
    ScaleneStatistics,
)


class ScaleneMemoryProfiler:
    """Handles memory profiling data processing for Scalene."""

    # Memory allocation action constants
    MALLOC_ACTION = "M"
    FREE_ACTION = "F"
    FREE_ACTION_SAMPLED = "f"

    # Class variable for storing MB conversion factor
    BYTES_PER_MB = 1024 * 1024

    def __init__(self, stats: ScaleneStatistics):
        self.__stats = stats
        self.__malloc_mapfile: Optional[ScaleneMapFile] = None
        self.__memcpy_mapfile: Optional[ScaleneMapFile] = None

    def set_mapfiles(
        self, malloc_mapfile: ScaleneMapFile, memcpy_mapfile: ScaleneMapFile
    ) -> None:
        """Set the memory map files for reading profiling data."""
        self.__malloc_mapfile = malloc_mapfile
        self.__memcpy_mapfile = memcpy_mapfile

    def process_memcpy_samples(self) -> None:
        """Process memcpy samples from the memcpy map file."""
        if not self.__memcpy_mapfile:
            return

        curr_pid = os.getpid()
        arr: List[MemcpyProfilingSample] = []

        # Process the input array
        with contextlib.suppress(ValueError):
            while self.__memcpy_mapfile.read():
                count_str = self.__memcpy_mapfile.get_str()
                try:
                    (
                        memcpy_time_str,
                        count_str2,
                        pid,
                        filename,
                        lineno,
                        bytei,
                    ) = count_str.split(",")
                except ValueError:
                    # Skip malformed entries
                    continue

                if int(curr_pid) != int(pid):
                    continue

                memcpy_profiling_sample = MemcpyProfilingSample(
                    memcpy_time=int(memcpy_time_str),
                    count=int(count_str2),
                    filename=Filename(filename),
                    lineno=LineNumber(int(lineno)),
                    bytecode_index=ByteCodeIndex(int(bytei)),
                )
                arr.append(memcpy_profiling_sample)

        arr.sort()

        for item in arr:
            # Add the byte index to the set for this line
            self.__stats.bytei_map[item.filename][item.lineno].add(item.bytecode_index)
            self.__stats.memory_stats.memcpy_samples[item.filename][item.lineno] += int(
                item.count
            )

    def process_malloc_free_samples(
        self,
        start_time: int,
        args: ScaleneArguments,
        invalidate_mutex: threading.Lock,
        invalidate_queue: List[Tuple[Filename, LineNumber]],
    ) -> None:
        """Handle interrupts for memory profiling (mallocs and frees)."""
        stats = self.__stats
        curr_pid = os.getpid()
        # Process the input array from where we left off reading last time.
        arr: List[ProfilingSample] = []
        with contextlib.suppress(FileNotFoundError):
            while self.__malloc_mapfile and self.__malloc_mapfile.read():
                count_str = self.__malloc_mapfile.get_str()
                if count_str.strip() == "":
                    # Skip empty/malformed samples but continue processing
                    # (don't break - there may be more valid samples)
                    continue
                try:
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
                except ValueError:
                    # Malformed sample - skip and continue
                    continue
                if int(curr_pid) != int(pid):
                    continue
                if int(reported_lineno) == -1:
                    continue
                profiling_sample = ProfilingSample(
                    action=action,
                    alloc_time=int(alloc_time_str),
                    count=int(count_str),
                    python_fraction=float(python_fraction_str),
                    pointer=Address(pointer),
                    filename=Filename(reported_fname),
                    lineno=LineNumber(int(reported_lineno)),
                    bytecode_index=ByteCodeIndex(int(bytei_str)),
                )
                arr.append(profiling_sample)

        # Cache memory_stats reference to avoid repeated attribute lookups
        mem_stats = stats.memory_stats
        mem_stats.alloc_samples += len(arr)

        # Iterate through the array to compute the new current footprint
        # and update the global __memory_footprint_samples. Since on some systems,
        # we get free events before mallocs, force `before` to always be at least 0.
        before = max(mem_stats.current_footprint, 0)
        prevmax = mem_stats.max_footprint
        freed_last_trigger = 0
        for item in arr:
            is_malloc = item.action == self.MALLOC_ACTION
            if item.count == scalene.scalene_config.NEWLINE_TRIGGER_LENGTH + 1:
                continue  # in previous implementations, we were adding NEWLINE to the footprint.
                # We should not account for this in the user-facing profile.
            count = item.count / self.BYTES_PER_MB
            if is_malloc:
                mem_stats.current_footprint += count
                if mem_stats.current_footprint > mem_stats.max_footprint:
                    mem_stats.max_footprint = mem_stats.current_footprint
                    mem_stats.max_footprint_python_fraction = item.python_fraction
                    mem_stats.max_footprint_loc = (item.filename, item.lineno)
            else:
                assert item.action in [
                    self.FREE_ACTION,
                    self.FREE_ACTION_SAMPLED,
                ]
                mem_stats.current_footprint -= count
                # Force current footprint to be non-negative; this
                # code is needed because Scalene can miss some initial
                # allocations at startup.
                mem_stats.current_footprint = max(0, mem_stats.current_footprint)
                if (
                    item.action == self.FREE_ACTION_SAMPLED
                    and mem_stats.last_malloc_triggered[2] == item.pointer
                ):
                    freed_last_trigger += 1
            timestamp = time.monotonic_ns() - start_time
            mem_stats.memory_footprint_samples.append(
                (timestamp, mem_stats.current_footprint)
            )
        after = mem_stats.current_footprint

        if freed_last_trigger:
            if freed_last_trigger <= 1:
                # We freed the last allocation trigger. Adjust scores.
                this_fn, this_ln, _this_ptr = mem_stats.last_malloc_triggered
                if this_ln != 0:
                    mallocs, frees = mem_stats.leak_score[this_fn][this_ln]
                    mem_stats.leak_score[this_fn][this_ln] = (mallocs, frees + 1)
            mem_stats.last_malloc_triggered = (
                Filename(""),
                LineNumber(0),
                Address("0x0"),
            )

        allocs = 0.0
        last_malloc = (Filename(""), LineNumber(0), Address("0x0"))
        malloc_pointer = Address("0x0")
        curr = before

        # Go through the array again and add each updated current footprint.
        for item in arr:
            is_malloc = item.action == self.MALLOC_ACTION
            if (
                is_malloc
                and item.count == scalene.scalene_config.NEWLINE_TRIGGER_LENGTH + 1
            ):
                with invalidate_mutex:
                    last_file, last_line = invalidate_queue.pop(0)

                mem_stats.memory_malloc_count[last_file][last_line] += 1
                mem_stats.memory_aggregate_footprint[last_file][
                    last_line
                ] += mem_stats.memory_current_highwater_mark[last_file][last_line]
                mem_stats.memory_current_footprint[last_file][last_line] = 0
                mem_stats.memory_current_highwater_mark[last_file][last_line] = 0
                continue

            # Cache per-item filename and lineno for repeated use
            fname = item.filename
            lineno = item.lineno

            # Add the byte index to the set for this line (if it's not there already).
            stats.bytei_map[fname][lineno].add(item.bytecode_index)
            count = item.count / self.BYTES_PER_MB
            if is_malloc:
                allocs += count
                curr += count
                assert curr <= mem_stats.max_footprint
                malloc_pointer = item.pointer

                # Cache inner dictionaries for this filename to reduce lookups
                malloc_samples_file = mem_stats.memory_malloc_samples[fname]
                python_samples_file = mem_stats.memory_python_samples[fname]
                current_footprint_file = mem_stats.memory_current_footprint[fname]
                highwater_file = mem_stats.memory_current_highwater_mark[fname]
                max_footprint_file = mem_stats.memory_max_footprint[fname]

                malloc_samples_file[lineno] += count
                python_samples_file[lineno] += item.python_fraction * count
                mem_stats.malloc_samples[fname] += 1
                mem_stats.total_memory_malloc_samples += count

                # Update current and max footprints for this file & line.
                current_footprint_file[lineno] += count
                new_current = current_footprint_file[lineno]
                highwater_file[lineno] = max(highwater_file[lineno], new_current)

                assert mem_stats.current_footprint <= mem_stats.max_footprint

                max_footprint_file[lineno] = max(
                    new_current, max_footprint_file[lineno]
                )
                # Ensure that the max footprint never goes above the true max footprint.
                max_footprint_file[lineno] = min(
                    mem_stats.max_footprint, max_footprint_file[lineno]
                )

                assert mem_stats.current_footprint <= mem_stats.max_footprint
                assert max_footprint_file[lineno] <= mem_stats.max_footprint
            else:
                assert item.action in [
                    self.FREE_ACTION,
                    self.FREE_ACTION_SAMPLED,
                ]
                curr -= count

                # Cache inner dictionaries for this filename
                free_samples_file = mem_stats.memory_free_samples[fname]
                free_count_file = mem_stats.memory_free_count[fname]
                current_footprint_file = mem_stats.memory_current_footprint[fname]

                free_samples_file[lineno] += count
                free_count_file[lineno] += 1
                mem_stats.total_memory_free_samples += count
                current_footprint_file[lineno] -= count
                # Ensure that we never drop the current footprint below 0.
                current_footprint_file[lineno] = max(0, current_footprint_file[lineno])

            mem_stats.per_line_footprint_samples[fname][lineno].append(
                [time.monotonic_ns() - start_time, max(0, curr)]
            )
            # If we allocated anything, then mark this as the last triggering malloc
            if allocs > 0:
                last_malloc = (fname, lineno, malloc_pointer)
        mem_stats.allocation_velocity = (
            mem_stats.allocation_velocity[0] + (after - before),
            mem_stats.allocation_velocity[1] + allocs,
        )
        if (
            args.memory_leak_detector
            and prevmax < mem_stats.max_footprint
            and mem_stats.max_footprint > 100
        ):
            mem_stats.last_malloc_triggered = last_malloc
            leak_fname, leak_lineno, _ = last_malloc
            mallocs, frees = mem_stats.leak_score[leak_fname][leak_lineno]
            mem_stats.leak_score[leak_fname][leak_lineno] = (mallocs + 1, frees)
