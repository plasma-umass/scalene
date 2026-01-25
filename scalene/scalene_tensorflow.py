"""TensorFlow profiler integration for Scalene.

This module wraps tf.profiler.experimental to capture TensorFlow operation
timing and attribute it back to Python source lines. TensorFlow's profiler
writes traces to disk (TensorBoard format), so this integration parses
those traces to extract timing information.

Note: TensorFlow profiling requires TensorBoard trace format parsing,
which provides less detailed per-line attribution than PyTorch.
This is a basic implementation that captures overall timing.

See https://www.tensorflow.org/guide/profiler
"""

from __future__ import annotations

import tempfile
from typing import Any

from scalene.scalene_library_profiler import ChromeTraceProfiler

# Check if TensorFlow is available at import time
_tf_available = False
_tf: Any = None
_gpu_available = False
try:
    import tensorflow as tf

    _tf = tf
    _tf_available = True
    # Check for GPU availability
    _gpu_available = len(tf.config.list_physical_devices("GPU")) > 0
except ImportError:
    pass  # TensorFlow not installed


def is_tensorflow_available() -> bool:
    """Check if TensorFlow is available."""
    return _tf_available


def is_gpu_available() -> bool:
    """Check if GPU is available for TensorFlow."""
    return _gpu_available


class TensorFlowProfiler(ChromeTraceProfiler):
    """Wraps tf.profiler.experimental to capture operation timing.

    TensorFlow's profiler writes traces to a directory in TensorBoard format.
    This profiler creates a temporary directory for traces and attempts
    to parse them to extract timing information.

    Note: TensorFlow's trace format is optimized for TensorBoard visualization
    rather than programmatic access, so per-line attribution is limited
    compared to PyTorch's profiler.
    """

    def is_available(self) -> bool:
        """Check if TensorFlow is available for profiling."""
        return _tf_available

    @property
    def name(self) -> str:
        return "TensorFlow"

    def start(self) -> None:
        """Start the TensorFlow profiler."""
        if not _tf_available or _tf is None:
            return

        try:
            # Create a temporary directory for traces
            self._trace_dir = tempfile.mkdtemp(prefix="scalene_tf_")

            # Configure profiler options for Python tracing
            options = _tf.profiler.experimental.ProfilerOptions(
                python_tracer_level=1,  # Enable Python tracing
                host_tracer_level=2,  # Include high-level execution details
            )

            # Start profiling - TensorFlow will write traces to this directory
            _tf.profiler.experimental.start(self._trace_dir, options=options)
            self._enabled = True
            self._profiling_active = True
        except Exception:
            # Profiler failed to start; disable silently to avoid disrupting user code
            self._enabled = False
            self._profiling_active = False
            # Clean up any trace directory that may have been created before failure
            self._cleanup_trace_dir()

    def stop(self) -> None:
        """Stop the TensorFlow profiler and process collected traces."""
        if not self._profiling_active:
            return

        try:
            # Stop profiling
            _tf.profiler.experimental.stop()

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

    def _extract_source_info(
        self, event: dict[str, Any]
    ) -> tuple[str | None, int | None]:
        """Extract Python source file and line from a TensorFlow trace event.

        TensorFlow may include Python stack information in trace events,
        which we use to attribute timing to source lines.

        Args:
            event: A trace event dictionary.

        Returns:
            Tuple of (filename, lineno) or (None, None) if not found.
        """
        args = event.get("args", {})

        # Look for source file/line information in common field names
        filename = args.get("file") or args.get("filename") or args.get("source_file")
        lineno = args.get("line") or args.get("lineno") or args.get("source_line")

        # TensorFlow sometimes includes Python stack in annotations
        if not filename:
            python_stack = args.get("python_stack")
            if python_stack and isinstance(python_stack, list) and python_stack:
                # Take the first frame from the stack
                frame = python_stack[0]
                if isinstance(frame, dict):
                    filename = frame.get("file") or frame.get("filename")
                    lineno = frame.get("line") or frame.get("lineno")

        return filename, lineno
