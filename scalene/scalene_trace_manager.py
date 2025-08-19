"""Trace management functionality for Scalene profiler."""

from __future__ import annotations

import os
from typing import Set, List, Tuple, Any

from scalene.scalene_statistics import Filename, LineNumber


class TraceManager:
    """Manages which files and lines should be traced during profiling."""
    
    def __init__(self, args):
        self._args = args
        self._files_to_profile: Set[Filename] = set()
        self._line_info: dict = {}
        
    def get_files_to_profile(self) -> Set[Filename]:
        """Get the set of files that should be profiled."""
        return self._files_to_profile
        
    def add_file_to_profile(self, filename: Filename) -> None:
        """Add a file to the profiling set."""
        self._files_to_profile.add(filename)
        
    def get_line_info(self, filename: Filename) -> List[Tuple[List[str], int]]:
        """Get line information for a file."""
        return self._line_info.get(filename, [])
        
    def profile_this_code(self, fname: Filename, lineno: LineNumber) -> bool:
        """Check if a specific file and line should be profiled.
        
        When using @profile, only profile files & lines that have been decorated.
        """
        if not self._files_to_profile:
            return True
        if fname not in self._files_to_profile:
            return False
        # Now check to see if it's the right line range.
        line_info = self.get_line_info(fname)
        found_function = any(
            line_start <= lineno < line_start + len(lines)
            for (lines, line_start) in line_info
        )
        return found_function
        
    def should_trace(self, filename: Filename, func: str) -> bool:
        """Determine if a file should be traced based on various criteria."""
        # Handle decorated functions
        if self._should_trace_decorated_function(filename, func):
            return True
            
        # Apply exclusion rules
        if not self._passes_exclusion_rules(filename):
            return False
            
        # Handle Jupyter cells
        if not self._handle_jupyter_cell(filename):
            return False
            
        # Apply profile-only rules
        if not self._passes_profile_only_rules(filename):
            return False
            
        # Check location-based rules
        return self._should_trace_by_location(filename)
        
    def _should_trace_decorated_function(self, filename: Filename, func: str) -> bool:
        """Check if we should trace a decorated function."""
        if self._files_to_profile:
            # Only trace files that have been specifically marked for profiling
            return filename in self._files_to_profile
        return False
        
    def _passes_exclusion_rules(self, filename: Filename) -> bool:
        """Check if filename passes exclusion patterns."""
        if not self._args.profile_exclude:
            return True
            
        # Check explicit exclude patterns
        profile_exclude_list = self._args.profile_exclude.split(",")
        return not any(prof in filename for prof in profile_exclude_list if prof != "")
            
    def _handle_jupyter_cell(self, filename: Filename) -> bool:
        """Handle Jupyter cell tracing rules."""
        # If in a Jupyter cell but cells are disabled, don't trace
        if "<ipython-input-" in filename and not self._args.profile_jupyter_cells:
            return False
        return True
        
    def _passes_profile_only_rules(self, filename: Filename) -> bool:
        """Check if filename passes profile-only patterns."""
        if not self._args.profile_only:
            return True
            
        profile_only_set = set(self._args.profile_only.split(","))
        return not (profile_only_set and all(
            prof not in filename for prof in profile_only_set
        ))
          
    def _should_trace_by_location(self, filename: Filename) -> bool:
        """Check if we should trace based on file location."""
        # Don't trace standard library files unless explicitly requested
        if not self._args.profile_all:
            # Skip files in site-packages unless explicitly included
            if "site-packages" in filename:
                return False
                
            # Skip files in the Python standard library
            import sysconfig
            stdlib_paths = [
                sysconfig.get_path('stdlib'),
                sysconfig.get_path('platstdlib')
            ]
            for stdlib_path in stdlib_paths:
                if stdlib_path and os.path.commonpath([filename, stdlib_path]) == stdlib_path:
                    return False
                    
        return True
        
    def register_files_to_profile(self, file_patterns: List[str]) -> None:
        """Register files that should be profiled based on patterns."""
        for pattern in file_patterns:
            # For now, treat patterns as exact filenames
            # In a full implementation, this would support glob patterns
            self._files_to_profile.add(Filename(pattern))