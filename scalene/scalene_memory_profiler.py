"""
Memory profiling processor for Scalene profiler.

This module extracts memory profiling functionality from the main Scalene class
to improve code organization and reduce complexity.
"""

import contextlib
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

import scalene.scalene_config
from scalene.scalene_arguments import ScaleneArguments
from scalene.scalene_mapfile import ScaleneMapFile
from scalene.scalene_statistics import (
    Address,
    ByteCodeIndex,
    Filename,
    LineNumber,
    MemcpyProfilingSample,
    ScaleneStatistics,
    StackFrame,
)
from scalene.scalene_utility import (
    intern_stack_frame,
    line_has_alloc_opcode,
)

# One parsed malloc/free record: (action, count, python_fraction, pointer,
# filename, lineno, bytecode_index, stack). Plain tuples: building an object
# per sample was a measurable share of the per-record cost.
_Sample = Tuple[
    str,
    int,
    float,
    Address,
    Filename,
    LineNumber,
    ByteCodeIndex,
    Optional[Tuple[StackFrame, ...]],
]

_MALLOC = "M"
_FREE = "F"
_FREE_SAMPLED = "f"
_ACTIONS = frozenset((_MALLOC, _FREE, _FREE_SAMPLED))

# Byte count of the sentinel allocation the native side makes to mark a
# line boundary (see NEWLINE in sampleheap.hpp).
_NEWLINE_TRIGGER_COUNT = scalene.scalene_config.NEWLINE_TRIGGER_LENGTH + 1

# Parsed stack fields, keyed by their raw text. A program allocates from a
# limited set of call paths, so most records hit this cache instead of being
# re-split and re-interned. Bounded: cleared once it reaches the limit.
_STACK_CACHE_LIMIT = 10_000
_stack_cache: Dict[str, Optional[Tuple[StackFrame, ...]]] = {}


def _parse_stack(stack_field: str) -> Optional[Tuple[StackFrame, ...]]:
    """Parse a record's stack field into an outermost-first frame tuple.

    The field looks like ``|file1;lineno1|file2;lineno2|...`` (leaf
    first). Returns None when it has no well-formed frames.
    """
    try:
        return _stack_cache[stack_field]
    except KeyError:
        pass
    frames: List[StackFrame] = []
    if stack_field.startswith("|"):
        for segment in stack_field.split("|"):
            if not segment:
                continue
            sep = segment.rfind(";")
            if sep <= 0:
                continue
            try:
                ln = int(segment[sep + 1 :])
            except ValueError:
                continue
            frames.append(
                intern_stack_frame(
                    filename=segment[:sep],
                    function_name="",
                    line_number=ln,
                )
            )
        # Reverse so the tuple is outermost-first, matching the add_stack
        # convention used elsewhere.
        frames.reverse()
    stack = tuple(frames) if frames else None
    if len(_stack_cache) >= _STACK_CACHE_LIMIT:
        _stack_cache.clear()
    _stack_cache[stack_field] = stack
    return stack


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

        mapfile = self.__memcpy_mapfile
        curr_pid = str(os.getpid())
        arr: List[MemcpyProfilingSample] = []

        # Process the input array
        while True:
            records = mapfile.read_records()
            if not records:
                break
            for record in records:
                parts = record.split(",")
                # Skip malformed records and records from other processes
                # (forked children share this log).
                if len(parts) != 6 or parts[2] != curr_pid:
                    continue
                try:
                    memcpy_profiling_sample = MemcpyProfilingSample(
                        memcpy_time=int(parts[0]),
                        count=int(parts[1]),
                        filename=Filename(parts[3]),
                        lineno=LineNumber(int(parts[4])),
                        bytecode_index=ByteCodeIndex(int(parts[5])),
                    )
                except ValueError:
                    continue
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
        """Handle interrupts for memory profiling (mallocs and frees).

        This runs once per sample, on a thread that holds the GIL while
        it works, so time spent here is time the profiled program can't
        run. Keep the per-record work lean: records are parsed into plain
        tuples, attribute and global lookups are hoisted out of the loops,
        and parsed stacks are cached (allocation sites repeat).
        """
        stats = self.__stats
        mem_stats = stats.memory_stats
        curr_pid = str(os.getpid())
        newline_trigger = _NEWLINE_TRIGGER_COUNT
        # Process the input array from where we left off reading last time.
        arr: List[_Sample] = []
        mapfile = self.__malloc_mapfile
        if mapfile:
            append = arr.append
            read_records = mapfile.read_records
            with contextlib.suppress(FileNotFoundError):
                while records := read_records():
                    for record in records:
                        # Split into the 9 required fields plus an optional
                        # trailing stack field. The stack field (when present)
                        # starts with '|' and contains no unescaped commas, so
                        # maxsplit=9 keeps it intact even if filenames or the
                        # stack itself contained extra punctuation.
                        parts = record.split(",", 9)
                        # Skip blank and malformed records, and records from
                        # other processes (forked children share this log).
                        # The native side writes the pid with %d, so comparing
                        # the text is exact.
                        if (
                            len(parts) < 9
                            or parts[4] != curr_pid
                            or parts[0] not in _ACTIONS
                        ):
                            continue
                        try:
                            append(
                                (
                                    parts[0],  # action
                                    int(parts[2]),  # count
                                    float(parts[3]),  # python fraction
                                    Address(parts[5]),  # pointer
                                    Filename(parts[6]),
                                    LineNumber(int(parts[7])),
                                    ByteCodeIndex(int(parts[8])),
                                    (
                                        _parse_stack(parts[9])
                                        if len(parts) == 10
                                        else None
                                    ),
                                )
                            )
                        except ValueError:
                            continue

        mem_stats.alloc_samples += len(arr)

        # Iterate through the array to compute the new current footprint
        # and update the global __memory_footprint_samples. Since on some systems,
        # we get free events before mallocs, force `before` to always be at least 0.
        before = max(mem_stats.current_footprint, 0)
        prevmax = mem_stats.max_footprint
        bytes_per_mb = self.BYTES_PER_MB
        monotonic_ns = time.monotonic_ns
        footprint_samples_append = mem_stats.memory_footprint_samples.append
        last_trigger_pointer = mem_stats.last_malloc_triggered[2]
        current = mem_stats.current_footprint
        max_footprint = mem_stats.max_footprint
        freed_last_trigger = 0
        for action, count, python_fraction, pointer, fname, lineno, _, _ in arr:
            if count == newline_trigger:
                continue  # in previous implementations, we were adding NEWLINE to the footprint.
                # We should not account for this in the user-facing profile.
            mb = count / bytes_per_mb
            if action == _MALLOC:
                current += mb
                if current > max_footprint:
                    max_footprint = current
                    mem_stats.max_footprint_python_fraction = python_fraction
                    mem_stats.max_footprint_loc = (fname, lineno)
            else:
                current -= mb
                # Force current footprint to be non-negative; this
                # code is needed because Scalene can miss some initial
                # allocations at startup.
                if current <= 0:
                    current = 0
                if action == _FREE_SAMPLED and last_trigger_pointer == pointer:
                    freed_last_trigger += 1
            footprint_samples_append((monotonic_ns() - start_time, current))
        mem_stats.current_footprint = current
        mem_stats.max_footprint = max_footprint
        after = current

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

        # Hoist the per-line tables out of the loop below.
        bytei_map = stats.bytei_map
        memory_stacks = stats.memory_stacks
        malloc_samples = mem_stats.memory_malloc_samples
        python_samples = mem_stats.memory_python_samples
        malloc_count_by_file = mem_stats.malloc_samples
        free_samples = mem_stats.memory_free_samples
        free_count = mem_stats.memory_free_count
        current_footprint = mem_stats.memory_current_footprint
        highwater = mem_stats.memory_current_highwater_mark
        max_footprint_by_line = mem_stats.memory_max_footprint
        per_line_footprint_samples = mem_stats.per_line_footprint_samples
        total_malloc = mem_stats.total_memory_malloc_samples
        total_free = mem_stats.total_memory_free_samples

        # Go through the array again and add each updated current footprint.
        for action, count, python_fraction, pointer, fname, lineno, bytei, stack in arr:
            is_malloc = action == _MALLOC
            if is_malloc and count == newline_trigger:
                with invalidate_mutex:
                    if invalidate_queue:
                        last_file, last_line = invalidate_queue.pop(0)
                    else:
                        continue

                mem_stats.memory_malloc_count[last_file][last_line] += 1
                mem_stats.memory_aggregate_footprint[last_file][last_line] += highwater[
                    last_file
                ][last_line]
                current_footprint[last_file][last_line] = 0
                highwater[last_file][last_line] = 0
                continue

            mb = count / bytes_per_mb

            # Smear suppression. The C++ interposer stamps every sample
            # with the leaf user frame from ``whereInPython``, but
            # CPython internals (arena resizes, GC, scalene's own
            # bookkeeping under the GIL) emit raw mallocs whose bytes
            # land on whichever leaf line the eval loop happens to be
            # on. If that line's bytecode cannot have caused the alloc
            # (no CALL / BUILD_ / LIST_ / … opcode — see
            # ``line_has_alloc_opcode``), the sample is "smear".
            #
            # Earlier versions redirected smear up the captured stack
            # to the nearest alloc-capable caller. That puts the bytes
            # on whatever call site is currently active, which is
            # misleading: e.g. ``x = doit2(x)`` is a CALL but doit2
            # never allocates — the bytes really come from heap state
            # set up by doit1 in a prior frame that's no longer on the
            # stack. For the same reason, the captured stack itself
            # isn't trustworthy here: it records which user frames
            # were active at the moment of the malloc, none of which
            # caused it. So we drop the sample from every per-line
            # accumulator *and* from ``memory_stacks``. The bytes are
            # still counted in the global running footprint (so the
            # global peak / sparkline are accurate), but no line,
            # function, or flame-chart path takes the blame.
            if not line_has_alloc_opcode(fname, lineno):
                # Keep the running per-item ``curr`` accurate so the
                # next legitimate sparkline sample reflects the right
                # footprint. Everything else (memory_stacks, per-line
                # accumulators, allocs / last_malloc tracking) skips
                # this sample.
                if is_malloc:
                    curr += mb
                else:
                    curr -= mb
                continue

            # Add the byte index to the set for this line (if it's not there already).
            bytei_map[fname][lineno].add(bytei)
            if is_malloc:
                # Attribute the sampled bytes to the Python call stack
                # captured *synchronously* in C++ inside process_malloc
                # (the record's stack). Unlike the old async signal-time
                # capture, this stack reflects exactly where the allocation
                # occurred, so short-lived allocator frames don't disappear.
                #
                # We deliberately do NOT populate function_name here:
                # looking up enclosing-def names requires reading source
                # files via linecache, which allocates. Since this code
                # runs on the Scalene sigqueue worker thread, any heap
                # allocation it causes would be observed by the
                # interposer and show up as an artifact in the user's
                # profile. Name resolution happens at JSON serialization
                # time instead (see scalene_json.py), off the hot path.
                if stack:
                    memory_stacks[stack] += mb
                allocs += mb
                curr += mb
                assert curr <= max_footprint
                malloc_pointer = pointer

                malloc_samples[fname][lineno] += mb
                python_samples[fname][lineno] += python_fraction * mb
                malloc_count_by_file[fname] += 1
                total_malloc += mb

                # Update current and max footprints for this file & line.
                current_footprint_file = current_footprint[fname]
                new_current = current_footprint_file[lineno] + mb
                current_footprint_file[lineno] = new_current
                highwater_file = highwater[fname]
                highwater_file[lineno] = max(highwater_file[lineno], new_current)
                max_footprint_file = max_footprint_by_line[fname]
                # Ensure that the max footprint never goes above the true max footprint.
                max_footprint_file[lineno] = min(
                    max_footprint, max(new_current, max_footprint_file[lineno])
                )
            else:
                curr -= mb
                free_samples[fname][lineno] += mb
                free_count[fname][lineno] += 1
                total_free += mb
                current_footprint_file = current_footprint[fname]
                # Ensure that we never drop the current footprint below 0.
                current_footprint_file[lineno] = max(
                    0, current_footprint_file[lineno] - mb
                )

            per_line_footprint_samples[fname][lineno].append(
                [monotonic_ns() - start_time, max(0, curr)]
            )
            # If we allocated anything, then mark this as the last triggering malloc
            if allocs > 0:
                last_malloc = (fname, lineno, malloc_pointer)
        mem_stats.total_memory_malloc_samples = total_malloc
        mem_stats.total_memory_free_samples = total_free
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
