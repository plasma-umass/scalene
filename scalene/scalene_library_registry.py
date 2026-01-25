"""Registry for managing multiple library profilers.

This module is separate from scalene_library_profiler to avoid cyclic imports.
The registry imports profiler implementations, while profiler implementations
import only the base classes from scalene_library_profiler.
"""

from __future__ import annotations

from scalene.scalene_library_profiler import ScaleneLibraryProfiler


class LibraryProfilerRegistry:
    """Registry for managing multiple library profilers.

    This class discovers available profilers, manages their lifecycle,
    and aggregates their timing data.
    """

    def __init__(self) -> None:
        self._profilers: list[ScaleneLibraryProfiler] = []
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

        # Import profilers here to allow graceful handling when libraries aren't installed
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
            pass  # JAX not installed, skip

        # Register TensorFlow profiler if available
        try:
            from scalene.scalene_tensorflow import TensorFlowProfiler

            tf_profiler = TensorFlowProfiler()
            self.register(tf_profiler)
        except ImportError:
            pass  # TensorFlow not installed, skip

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

    def get_profilers(self) -> list[ScaleneLibraryProfiler]:
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
