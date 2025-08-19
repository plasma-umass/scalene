"""
Memory profiling processor for Scalene profiler.

This module extracts memory profiling functionality from the main Scalene class
to improve code organization and reduce complexity.
"""

import contextlib
import os
from typing import List, Optional, Union, Callable

from types import FrameType

import scalene.scalene_config
from scalene.scalene_statistics import (
    Address,
    ByteCodeIndex,
    Filename,
    LineNumber,
    ScaleneStatistics,
    ProfilingSample,
    MemcpyProfilingSample,
)
from scalene.scalene_mapfile import ScaleneMapFile


class ScaleneMemoryProfiler:
    """Handles memory profiling data processing for Scalene."""
    
    def __init__(self, stats: ScaleneStatistics):
        self.__stats = stats
        self.__malloc_mapfile: Optional[ScaleneMapFile] = None
        self.__memcpy_mapfile: Optional[ScaleneMapFile] = None
        
    def set_mapfiles(self, malloc_mapfile: ScaleneMapFile, memcpy_mapfile: ScaleneMapFile) -> None:
        """Set the memory map files for reading profiling data."""
        self.__malloc_mapfile = malloc_mapfile
        self.__memcpy_mapfile = memcpy_mapfile
        
    def process_malloc_free_samples(self, invalidate_queue: List) -> None:
        """Process allocation and free samples from the malloc map file."""
        if not self.__malloc_mapfile:
            return
            
        curr_pid = os.getpid()
        arr: List[ProfilingSample] = []
        
        # Read and parse malloc/free events from the map file
        with contextlib.suppress(FileNotFoundError):
            while self.__malloc_mapfile.read():
                count_str = self.__malloc_mapfile.get_str()
                if count_str.strip() == "":
                    break
                    
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
                    # Skip malformed entries
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
                    bytecode_index=ByteCodeIndex(int(bytei_str))
                )
                arr.append(profiling_sample)

        self.__stats.memory_stats.alloc_samples += len(arr)
        
        # Process the allocation/free samples
        self._process_allocation_events(arr, invalidate_queue)
        
    def _process_allocation_events(self, arr: List[ProfilingSample], invalidate_queue: List) -> None:
        """Process individual allocation and free events."""
        BYTES_PER_MB = 1024 * 1024
        MALLOC_ACTION = "M"
        FREE_ACTION = "F"
        FREE_ACTION_SAMPLED = "f"
        
        for item in arr:
            is_malloc = item.action in [MALLOC_ACTION]
            
            # Handle special newline trigger case
            if (
                is_malloc
                and item.count == scalene.scalene_config.NEWLINE_TRIGGER_LENGTH + 1
            ):
                if invalidate_queue:
                    last_file, last_line = invalidate_queue.pop(0)
                    self.__stats.memory_stats.memory_malloc_count[last_file][last_line] += 1
                    self.__stats.memory_stats.memory_aggregate_footprint[last_file][
                        last_line
                    ] += self.__stats.memory_stats.memory_current_highwater_mark[last_file][last_line]
                    self.__stats.memory_stats.memory_current_footprint[last_file][last_line] = 0
                    self.__stats.memory_stats.memory_current_highwater_mark[last_file][last_line] = 0
                continue

            # Add the byte index to the set for this line
            self.__stats.bytei_map[item.filename][item.lineno].add(item.bytecode_index)
            
            # Skip newline triggers for user-facing profile
            if item.count == scalene.scalene_config.NEWLINE_TRIGGER_LENGTH + 1:
                continue
                
            count = item.count / BYTES_PER_MB
            
            if is_malloc:
                self._process_malloc_event(item, count)
            else:
                assert item.action in [FREE_ACTION, FREE_ACTION_SAMPLED]
                self._process_free_event(item, count)
                
    def _process_malloc_event(self, item: ProfilingSample, count: float) -> None:
        """Process a malloc event."""
        self.__stats.memory_stats.current_footprint += count
        
        if self.__stats.memory_stats.current_footprint > self.__stats.memory_stats.max_footprint:
            self.__stats.memory_stats.max_footprint = self.__stats.memory_stats.current_footprint
            self.__stats.memory_stats.max_footprint_python_fraction = item.python_fraction
            self.__stats.memory_stats.max_footprint_loc = (item.filename, item.lineno)
            
        # Update per-line statistics
        self.__stats.memory_stats.memory_malloc_count[item.filename][item.lineno] += 1
        self.__stats.memory_stats.memory_malloc_samples[item.filename][item.lineno] += count
        
        if item.python_fraction > 0:
            self.__stats.memory_stats.memory_python_samples[item.filename][item.lineno] += count
            
        self.__stats.memory_stats.memory_current_footprint[item.filename][item.lineno] += count
        self.__stats.memory_stats.memory_current_highwater_mark[item.filename][item.lineno] = max(
            self.__stats.memory_stats.memory_current_highwater_mark[item.filename][item.lineno],
            self.__stats.memory_stats.memory_current_footprint[item.filename][item.lineno]
        )
        
    def _process_free_event(self, item: ProfilingSample, count: float) -> None:
        """Process a free event."""
        self.__stats.memory_stats.current_footprint -= count
        self.__stats.memory_stats.memory_free_count[item.filename][item.lineno] += 1
        self.__stats.memory_stats.memory_free_samples[item.filename][item.lineno] += count
        
        before = self.__stats.memory_stats.memory_current_footprint[item.filename][item.lineno]
        before = max(0, before)
        
        self.__stats.memory_stats.memory_current_footprint[item.filename][item.lineno] = max(
            0, before - count
        )
        
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
                    bytecode_index=ByteCodeIndex(int(bytei))
                )
                arr.append(memcpy_profiling_sample)
                
        arr.sort()

        for item in arr:
            # Add the byte index to the set for this line
            self.__stats.bytei_map[item.filename][item.lineno].add(item.bytecode_index)
            self.__stats.memory_stats.memcpy_samples[item.filename][item.lineno] += int(item.count)