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

import json
import os
import tempfile
from typing import Any

from scalene.scalene_library_profiler import ScaleneLibraryProfiler

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


class TensorFlowProfiler(ScaleneLibraryProfiler):
    """Wraps tf.profiler.experimental to capture operation timing.

    TensorFlow's profiler writes traces to a directory in TensorBoard format.
    This profiler creates a temporary directory for traces and attempts
    to parse them to extract timing information.

    Note: TensorFlow's trace format is optimized for TensorBoard visualization
    rather than programmatic access, so per-line attribution is limited
    compared to PyTorch's profiler.
    """

    def __init__(self) -> None:
        super().__init__()
        self._trace_dir: str | None = None
        self._profiling_active: bool = False

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
            self._trace_dir = None

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

    def _process_traces(self) -> None:
        """Parse TensorFlow trace files to extract timing information.

        TensorFlow traces are in TensorBoard/Chrome trace event format.
        We look for trace.json files and parse them for timing data.
        """
        if not self._trace_dir or not os.path.exists(self._trace_dir):
            return

        try:
            # Look for trace files (Chrome trace event format)
            # TensorFlow saves traces in plugins/profile/<run>/... structure
            for root, _, files in os.walk(self._trace_dir):
                for filename in files:
                    if filename.endswith(".json") or filename.endswith(".json.gz"):
                        trace_path = os.path.join(root, filename)
                        self._parse_trace_file(trace_path)
                    elif filename.endswith(".trace"):
                        # TensorFlow protobuf trace format
                        trace_path = os.path.join(root, filename)
                        self._parse_protobuf_trace(trace_path)
        except Exception:
            pass  # Silently handle parse errors to avoid disrupting user code

    def _parse_trace_file(self, trace_path: str) -> None:
        """Parse a Chrome trace event format file.

        The trace file contains events with timing information.
        We extract events and try to attribute them to Python source.

        Args:
            trace_path: Path to the trace JSON file.
        """
        import gzip

        try:
            # Handle gzipped files
            if trace_path.endswith(".gz"):
                with gzip.open(trace_path, "rt") as f:
                    data = json.load(f)
            else:
                with open(trace_path) as f:
                    data = json.load(f)

            # Chrome trace format can be an array or an object with traceEvents
            events = data if isinstance(data, list) else data.get("traceEvents", [])

            for event in events:
                self._process_trace_event(event)
        except Exception:
            pass  # Silently handle malformed trace files

    def _parse_protobuf_trace(self, trace_path: str) -> None:
        """Parse a TensorFlow protobuf trace file.

        TensorFlow can write traces in protobuf format which contains
        more detailed information than the JSON format.

        Args:
            trace_path: Path to the .trace file.
        """
        # Parsing protobuf traces requires TensorFlow's internal libraries
        # For now, we skip this and rely on JSON traces
        _ = trace_path  # Unused for now

    def _process_trace_event(self, event: dict[str, Any]) -> None:
        """Process a single trace event and extract timing.

        Chrome trace events have the following relevant fields:
        - name: Event name (e.g., operation name)
        - ph: Phase (B=begin, E=end, X=complete, etc.)
        - ts: Timestamp in microseconds
        - dur: Duration in microseconds (for X events)
        - args: Additional arguments (may contain Python source info)

        Args:
            event: A trace event dictionary.
        """
        # Only process complete events (X) or duration events
        phase = event.get("ph", "")
        if phase not in ("X", "B", "E"):
            return

        duration_us = event.get("dur", 0)
        if duration_us <= 0:
            return

        # Try to extract Python source information from args
        args = event.get("args", {})

        # Look for source file/line information
        # TensorFlow may include this in various forms
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

        if filename and lineno:
            try:
                lineno = int(lineno)
                # Attribute the duration to this source line
                self.line_times[filename][lineno] += duration_us
            except (ValueError, TypeError):
                pass  # Skip events with invalid line numbers

    def _cleanup_trace_dir(self) -> None:
        """Remove temporary trace directory and its contents."""
        if not self._trace_dir:
            return

        try:
            import shutil

            if os.path.exists(self._trace_dir):
                shutil.rmtree(self._trace_dir)
        except Exception:
            pass  # Best-effort cleanup; ignore errors
        finally:
            self._trace_dir = None

    def clear(self) -> None:
        """Clear all collected timing data."""
        super().clear()
        self._cleanup_trace_dir()
