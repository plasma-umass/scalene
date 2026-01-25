"""JAX profiler integration for Scalene.

This module wraps jax.profiler to capture JAX operation timing and
attribute it back to Python source lines. JAX's profiler writes
traces to disk (TensorBoard format), so this integration parses
those traces to extract timing information.

Note: JAX profiling requires TensorBoard trace format parsing,
which provides less detailed per-line attribution than PyTorch.
This is a basic implementation that captures overall timing.

See https://jax.readthedocs.io/en/latest/profiling.html
"""

from __future__ import annotations

import tempfile
from typing import Any

from scalene.scalene_library_profiler import ChromeTraceProfiler

# Check if JAX is available at import time
_jax_available = False
_jax: Any = None
try:
    import jax

    _jax = jax
    _jax_available = True
except ImportError:
    pass  # JAX not installed


def is_jax_available() -> bool:
    """Check if JAX is available."""
    return _jax_available


class JaxProfiler(ChromeTraceProfiler):
    """Wraps jax.profiler to capture operation timing.

    JAX's profiler writes traces to a directory in TensorBoard format.
    This profiler creates a temporary directory for traces and attempts
    to parse them to extract timing information.

    Note: JAX's trace format is optimized for TensorBoard visualization
    rather than programmatic access, so per-line attribution is limited
    compared to PyTorch's profiler.
    """

    def is_available(self) -> bool:
        """Check if JAX is available for profiling."""
        return _jax_available

    @property
    def name(self) -> str:
        return "JAX"

    def start(self) -> None:
        """Start the JAX profiler."""
        if not _jax_available or _jax is None:
            return

        try:
            # Create a temporary directory for traces
            self._trace_dir = tempfile.mkdtemp(prefix="scalene_jax_")

            # Start profiling - JAX will write traces to this directory
            _jax.profiler.start_trace(self._trace_dir)
            self._enabled = True
            self._profiling_active = True
        except Exception:
            # Profiler failed to start; disable silently to avoid disrupting user code
            self._enabled = False
            self._profiling_active = False
            # Clean up any trace directory that may have been created before failure
            self._cleanup_trace_dir()

    def stop(self) -> None:
        """Stop the JAX profiler and process collected traces."""
        if not self._profiling_active:
            return

        try:
            # Stop profiling
            _jax.profiler.stop_trace()

            # Process the traces to extract timing
            if self._trace_dir:
                self._process_traces()
        except Exception:
            pass  # Silently handle errors during shutdown to avoid disrupting user code
        finally:
            self._enabled = False
            self._profiling_active = False
            # Clean up trace directory
            self._cleanup_trace_dir()
