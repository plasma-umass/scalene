"""
Memory profiling processor for Scalene profiler.

This module extracts memory profiling functionality from the main Scalene class
to improve code organization and reduce complexity.
"""

import contextlib
import os
from typing import List, Optional


import scalene.scalene_config
from scalene.scalene_statistics import (
    ByteCodeIndex,
    Filename,
    LineNumber,
    ScaleneStatistics,
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