"""Core profiling functionality for Scalene profiler."""

from __future__ import annotations

import time
from typing import List, Tuple, Optional, Any, Set
from types import FrameType

from scalene.scalene_statistics import (
    Filename,
    LineNumber, 
    ByteCodeIndex,
    ScaleneStatistics,
    ProfilingSample,
)


class ProfilerCore:
    """Handles core profiling functionality including CPU sampling and frame processing."""
    
    def __init__(self, stats: ScaleneStatistics):
        self._stats = stats
        self._last_profiled = [Filename("NADA"), LineNumber(0), ByteCodeIndex(0)]
        self._last_profiled_invalidated = False
        
    def get_last_profiled(self) -> List[Any]:
        """Get the last profiled location."""
        return self._last_profiled
        
    def set_last_profiled(self, fname: Filename, lineno: LineNumber, bytecode_index: ByteCodeIndex) -> None:
        """Set the last profiled location."""
        self._last_profiled = [fname, lineno, bytecode_index]
        
    def get_last_profiled_invalidated(self) -> bool:
        """Check if last profiled location has been invalidated."""
        return self._last_profiled_invalidated
        
    def set_last_profiled_invalidated(self, value: bool) -> None:
        """Set the invalidated status of last profiled location."""
        self._last_profiled_invalidated = value
        
    def compute_frames_to_record(self) -> List[Tuple[FrameType, int, FrameType]]:
        """Compute which frames should be recorded for profiling.
        
        Returns:
            List of tuples containing (frame, line_number, outer_frame)
        """
        import sys
        
        frames_to_record: List[Tuple[FrameType, int, FrameType]] = []
        current_frame = sys._getframe(2)  # Skip this frame and the caller
        
        while current_frame:
            filename = Filename(current_frame.f_code.co_filename)
            lineno = LineNumber(current_frame.f_lineno)
            
            # Check if this frame should be profiled
            if self._should_profile_frame(filename, lineno, current_frame):
                frames_to_record.append((current_frame, lineno, current_frame.f_back or current_frame))
                
            current_frame = current_frame.f_back
            
        return frames_to_record
    
    def _should_profile_frame(self, filename: Filename, lineno: LineNumber, frame: FrameType) -> bool:
        """Determine if a frame should be profiled."""
        # This is a simplified version - in the full refactor, this would contain
        # the logic from the original should_trace method
        return True  # For now, profile all frames
        
    def process_cpu_sample(
        self,
        frame: FrameType,
        time_per_sample: float,
        python_elapsed: float,
        sys_elapsed: float
    ) -> None:
        """Process a CPU sample for profiling."""
        filename = Filename(frame.f_code.co_filename)
        lineno = LineNumber(frame.f_lineno)
        bytecode_index = ByteCodeIndex(frame.f_lasti)
        
        # Record CPU samples directly in statistics (like original code)
        self._stats.cpu_stats.cpu_samples_python[filename][lineno] += python_elapsed
        self._stats.cpu_stats.cpu_samples_c[filename][lineno] += sys_elapsed
        self._stats.cpu_stats.cpu_samples[filename] += time_per_sample
        self._stats.cpu_stats.total_cpu_samples += time_per_sample
        
        # Update last profiled location
        self.set_last_profiled(filename, lineno, bytecode_index)