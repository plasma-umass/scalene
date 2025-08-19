"""Process management functionality for Scalene profiler."""

from __future__ import annotations

import os
import tempfile
import pathlib
from typing import Set

from scalene.scalene_preload import ScalenePreload


class ProcessManager:
    """Manages multiprocessing and child process functionality."""
    
    def __init__(self, args):
        self._args = args
        self._child_pids: Set[int] = set()
        self._is_child = -1
        self._parent_pid = -1
        self._pid = os.getpid()
        self._python_alias_dir: pathlib.Path
        self._orig_python = ""
        
        # Set up process-specific configuration
        self._setup_process_config()
        
    def _setup_process_config(self) -> None:
        """Set up process-specific configuration."""
        if self._args.pid:
            # Child process
            self._is_child = 1
            self._parent_pid = self._args.pid
            # Use the same directory as the parent
            dirname = os.environ["PATH"].split(os.pathsep)[0]
            self._python_alias_dir = pathlib.Path(dirname)
        else:
            # Parent process
            self._is_child = 0
            self._parent_pid = self._pid
            # Create a temporary directory for Python aliases
            self._python_alias_dir = pathlib.Path(
                tempfile.mkdtemp(prefix="scalene")
            )
            
    def get_child_pids(self) -> Set[int]:
        """Get the set of child process IDs."""
        return self._child_pids
        
    def add_child_pid(self, pid: int) -> None:
        """Add a child process ID to tracking."""
        self._child_pids.add(pid)
        
    def remove_child_pid(self, pid: int) -> None:
        """Remove a child process ID from tracking."""
        self._child_pids.discard(pid)
        
    def is_child_process(self) -> bool:
        """Check if this is a child process."""
        return self._is_child == 1
        
    def get_parent_pid(self) -> int:
        """Get the parent process ID."""
        return self._parent_pid
        
    def get_current_pid(self) -> int:
        """Get the current process ID."""
        return self._pid
        
    def get_python_alias_dir(self) -> pathlib.Path:
        """Get the directory containing Python aliases."""
        return self._python_alias_dir
        
    def set_original_python_executable(self, executable: str) -> None:
        """Set the original Python executable path."""
        self._orig_python = executable
        
    def get_original_python_executable(self) -> str:
        """Get the original Python executable path."""
        return self._orig_python
        
    def before_fork(self) -> None:
        """Handle operations before forking a new process."""
        # Disable signals before forking to avoid race conditions
        pass
        
    def after_fork_in_parent(self, child_pid: int) -> None:
        """Handle operations in parent process after forking."""
        self.add_child_pid(child_pid)
        
    def after_fork_in_child(self) -> None:
        """Handle operations in child process after forking."""
        # Reset child process state
        self._child_pids.clear()
        self._is_child = 1
        self._pid = os.getpid()
        
        # Set up preloading for child process
        if hasattr(self._args, 'preload') and self._args.preload:
            ScalenePreload.setup_preload(
                preload_libs=self._args.preload,
                python_alias_dir=self._python_alias_dir
            )
            
    def setup_multiprocessing_redirection(self) -> None:
        """Set up redirection for multiprocessing calls."""
        # This would contain the logic for redirecting Python calls
        # to go through Scalene for child processes
        pass
        
    def cleanup_process_resources(self) -> None:
        """Clean up process-specific resources."""
        # Clean up temporary directories and aliases
        if not self.is_child_process() and self._python_alias_dir.exists():
            try:
                import shutil
                shutil.rmtree(self._python_alias_dir)
            except Exception:
                pass  # Best effort cleanup