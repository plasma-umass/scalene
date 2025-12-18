"""
Windows-specific functionality for Scalene memory profiling.

On Windows, we can't use LD_PRELOAD or DYLD_INSERT_LIBRARIES to
interpose on malloc/free. Instead, we load libscalene.dll at runtime
and it patches the CRT functions using inline hooks.

We also use Windows Events instead of Unix signals to communicate
between the native code and Python.
"""

import ctypes
import os
import sys
from typing import Optional

if sys.platform != "win32":
    raise ImportError("scalene_windows is only for Windows")


class WindowsMemoryProfiler:
    """Handles Windows-specific memory profiling setup."""

    def __init__(self) -> None:
        self._dll: Optional[ctypes.CDLL] = None
        self._malloc_event: Optional[int] = None
        self._free_event: Optional[int] = None
        self._initialized = False

    def load_dll(self, dll_path: Optional[str] = None) -> bool:
        """
        Load the libscalene DLL for memory profiling.

        Args:
            dll_path: Path to libscalene.dll. If None, looks for it in
                     the scalene package directory or SCALENE_WINDOWS_DLL env var.

        Returns:
            True if the DLL was loaded successfully, False otherwise.
        """
        if self._dll is not None:
            return True

        if dll_path is None:
            dll_path = os.environ.get("SCALENE_WINDOWS_DLL")

        if dll_path is None:
            # Try to find in the scalene package directory
            import scalene
            dll_path = os.path.join(scalene.__path__[0], "libscalene.dll")

        if not os.path.exists(dll_path):
            return False

        try:
            self._dll = ctypes.CDLL(dll_path)
            return True
        except OSError as e:
            print(f"Warning: Failed to load libscalene.dll: {e}", file=sys.stderr)
            return False

    def initialize(self) -> bool:
        """
        Initialize the Windows memory profiler.

        This sets up the Windows Events for malloc/free signaling
        and calls the DLL's init function.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._initialized:
            return True

        if self._dll is None and not self.load_dll():
            return False

        try:
            # Call the DLL's init function
            if hasattr(self._dll, "scalene_init"):
                self._dll.scalene_init()

            # Open the Windows Events created by the DLL
            pid = os.getpid()
            kernel32 = ctypes.windll.kernel32

            # Event names must match those in sampleheap_win.hpp
            malloc_event_name = f"Local\\scalene-malloc-event{pid}"
            free_event_name = f"Local\\scalene-free-event{pid}"

            # OpenEvent returns 0 on failure
            SYNCHRONIZE = 0x00100000
            self._malloc_event = kernel32.OpenEventW(
                SYNCHRONIZE, False, malloc_event_name
            )
            self._free_event = kernel32.OpenEventW(
                SYNCHRONIZE, False, free_event_name
            )

            self._initialized = True
            return True

        except Exception as e:
            print(f"Warning: Failed to initialize Windows memory profiler: {e}")
            return False

    def set_where_in_python(self, func) -> None:
        """
        Set the whereInPython callback function.

        This function is called by the native code to determine the
        current Python source location during memory operations.
        """
        if self._dll is None:
            return

        if hasattr(self._dll, "scalene_set_where_in_python"):
            # Create a C callback wrapper
            # The function signature is: int (string&, int&, int&)
            # But we need to handle this carefully with ctypes
            self._dll.scalene_set_where_in_python(func)

    def set_done(self, done: bool) -> None:
        """Signal that profiling is done (or starting)."""
        if self._dll is None:
            return

        if hasattr(self._dll, "scalene_set_done"):
            self._dll.scalene_set_done(done)

    def wait_for_malloc_event(self, timeout_ms: int = 100) -> bool:
        """
        Wait for a malloc sampling event.

        Args:
            timeout_ms: Maximum time to wait in milliseconds.

        Returns:
            True if the event was signaled, False on timeout or error.
        """
        if self._malloc_event is None or self._malloc_event == 0:
            return False

        kernel32 = ctypes.windll.kernel32
        WAIT_OBJECT_0 = 0

        result = kernel32.WaitForSingleObject(self._malloc_event, timeout_ms)
        return result == WAIT_OBJECT_0

    def wait_for_free_event(self, timeout_ms: int = 100) -> bool:
        """
        Wait for a free sampling event.

        Args:
            timeout_ms: Maximum time to wait in milliseconds.

        Returns:
            True if the event was signaled, False on timeout or error.
        """
        if self._free_event is None or self._free_event == 0:
            return False

        kernel32 = ctypes.windll.kernel32
        WAIT_OBJECT_0 = 0

        result = kernel32.WaitForSingleObject(self._free_event, timeout_ms)
        return result == WAIT_OBJECT_0

    def dump_stats(self) -> None:
        """Dump debug stats from the DLL."""
        if self._dll is not None and hasattr(self._dll, "scalene_dump_stats"):
            self._dll.scalene_dump_stats()

    def cleanup(self) -> None:
        """Clean up Windows resources."""
        kernel32 = ctypes.windll.kernel32

        if self._malloc_event and self._malloc_event != 0:
            kernel32.CloseHandle(self._malloc_event)
            self._malloc_event = None

        if self._free_event and self._free_event != 0:
            kernel32.CloseHandle(self._free_event)
            self._free_event = None

        self._dll = None
        self._initialized = False

    def get_shared_memory_name(self, name_template: str) -> str:
        """
        Convert a Unix-style /tmp path to a Windows named object path.

        Args:
            name_template: Template like "/tmp/scalene-malloc-signal%d"

        Returns:
            Windows named object path like "Local\\scalene-malloc-signal<pid>"
        """
        pid = os.getpid()
        name = name_template % pid

        # Convert /tmp/ prefix to Local\\
        if name.startswith("/tmp/"):
            name = "Local\\" + name[5:]
        elif name.startswith("/"):
            name = "Local\\" + name[1:]

        # Replace remaining slashes
        name = name.replace("/", "_")

        return name


# Global instance
_windows_profiler: Optional[WindowsMemoryProfiler] = None


def get_windows_profiler() -> WindowsMemoryProfiler:
    """Get the global WindowsMemoryProfiler instance."""
    global _windows_profiler
    if _windows_profiler is None:
        _windows_profiler = WindowsMemoryProfiler()
    return _windows_profiler


def is_memory_profiling_available() -> bool:
    """Check if memory profiling is available on Windows."""
    profiler = get_windows_profiler()
    return profiler.load_dll()
