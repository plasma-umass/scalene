"""Abstract base class for library-specific profilers.

This module provides a common interface for integrating profiling APIs
from various ML/scientific computing libraries (PyTorch, JAX, TensorFlow, etc.)
into Scalene. Each library profiler captures timing information and attributes
it back to Python source lines.

The key advantage of library-specific profilers is that they avoid the
signal delivery limitation: they use the library's built-in instrumentation
rather than relying on signal handlers that can't see native frames during
execution.
"""

from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


class ScaleneLibraryProfiler(ABC):
    """Base class for library-specific profilers.

    Subclasses implement profiling for specific libraries (PyTorch, JAX, TensorFlow)
    by wrapping the library's built-in profiling API and extracting per-line timing.

    Attributes:
        line_times: CPU time per source line in microseconds
        gpu_line_times: GPU time per source line in microseconds
    """

    def __init__(self) -> None:
        # Dict[filename, Dict[lineno, total_time_us]] for CPU time
        self.line_times: Dict[str, Dict[int, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        # Dict[filename, Dict[lineno, total_time_us]] for GPU time
        self.gpu_line_times: Dict[str, Dict[int, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        self._enabled: bool = False

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the library is installed and profiling is available.

        Returns:
            True if the library can be used for profiling, False otherwise.
        """
        pass

    @abstractmethod
    def start(self) -> None:
        """Start profiling.

        This should initialize the library's profiler and begin collecting
        timing data. If the library is not available or profiling fails to
        start, this should fail silently.
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop profiling and process collected events.

        This should stop the library's profiler, extract timing information,
        and populate line_times and gpu_line_times dictionaries.
        """
        pass

    @property
    def name(self) -> str:
        """Return the name of this profiler for display purposes."""
        return self.__class__.__name__

    @property
    def enabled(self) -> bool:
        """Return True if profiling is currently active."""
        return self._enabled

    def get_line_time(self, filename: str, lineno: int) -> float:
        """Get CPU time in seconds for a source line.

        Args:
            filename: The source file path
            lineno: The line number

        Returns:
            Total CPU time in seconds spent on operations from this line.
        """
        return self.line_times.get(filename, {}).get(lineno, 0.0) / 1_000_000

    def get_gpu_line_time(self, filename: str, lineno: int) -> float:
        """Get GPU time in seconds for a source line.

        Args:
            filename: The source file path
            lineno: The line number

        Returns:
            Total GPU time in seconds spent on operations from this line.
        """
        return self.gpu_line_times.get(filename, {}).get(lineno, 0.0) / 1_000_000

    def has_gpu_timing(self) -> bool:
        """Check if any GPU timing was captured.

        Returns:
            True if gpu_line_times contains any data.
        """
        return len(self.gpu_line_times) > 0

    def get_all_times(self) -> List[Tuple[str, int, float, float]]:
        """Get all timing data as a list of (filename, lineno, cpu_time, gpu_time).

        Returns:
            List of tuples with timing data for each profiled line.
        """
        result = []
        all_files = set(self.line_times.keys()) | set(self.gpu_line_times.keys())
        for filename in all_files:
            cpu_times = self.line_times.get(filename, {})
            gpu_times = self.gpu_line_times.get(filename, {})
            all_lines = set(cpu_times.keys()) | set(gpu_times.keys())
            for lineno in all_lines:
                cpu_us = cpu_times.get(lineno, 0.0)
                gpu_us = gpu_times.get(lineno, 0.0)
                # Convert to seconds
                result.append((filename, lineno, cpu_us / 1_000_000, gpu_us / 1_000_000))
        return result

    def clear(self) -> None:
        """Clear all collected timing data."""
        self.line_times.clear()
        self.gpu_line_times.clear()


class LibraryProfilerRegistry:
    """Registry for managing multiple library profilers.

    This class discovers available profilers, manages their lifecycle,
    and aggregates their timing data.
    """

    def __init__(self) -> None:
        self._profilers: List[ScaleneLibraryProfiler] = []
        self._initialized: bool = False

    def register(self, profiler: ScaleneLibraryProfiler) -> None:
        """Register a profiler if its library is available.

        Args:
            profiler: The profiler instance to register.
        """
        if profiler.is_available():
            self._profilers.append(profiler)

    def initialize(self) -> None:
        """Initialize the registry with all available profilers.

        This method discovers and registers all available library profilers.
        Call this once before profiling starts.
        """
        if self._initialized:
            return

        # Import profilers here to avoid circular imports
        from scalene.scalene_torch import TorchProfiler

        # Register PyTorch profiler
        torch_profiler = TorchProfiler()
        self.register(torch_profiler)

        # Register JAX profiler if available
        try:
            from scalene.scalene_jax import JaxProfiler

            jax_profiler = JaxProfiler()
            self.register(jax_profiler)
        except ImportError:
            pass

        # Register TensorFlow profiler if available
        try:
            from scalene.scalene_tensorflow import TensorFlowProfiler

            tf_profiler = TensorFlowProfiler()
            self.register(tf_profiler)
        except ImportError:
            pass

        self._initialized = True

    def start_all(self) -> None:
        """Start all registered profilers."""
        for profiler in self._profilers:
            profiler.start()

    def stop_all(self) -> None:
        """Stop all registered profilers."""
        for profiler in self._profilers:
            profiler.stop()

    def clear_all(self) -> None:
        """Clear timing data from all profilers."""
        for profiler in self._profilers:
            profiler.clear()

    def get_profilers(self) -> List[ScaleneLibraryProfiler]:
        """Get all registered profilers."""
        return self._profilers

    def get_line_time(self, filename: str, lineno: int) -> float:
        """Get total CPU time across all profilers for a source line.

        Args:
            filename: The source file path
            lineno: The line number

        Returns:
            Total CPU time in seconds from all library profilers.
        """
        return sum(p.get_line_time(filename, lineno) for p in self._profilers)

    def get_gpu_line_time(self, filename: str, lineno: int) -> float:
        """Get total GPU time across all profilers for a source line.

        Args:
            filename: The source file path
            lineno: The line number

        Returns:
            Total GPU time in seconds from all library profilers.
        """
        return sum(p.get_gpu_line_time(filename, lineno) for p in self._profilers)
