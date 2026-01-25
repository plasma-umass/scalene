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

import json
import os
import tempfile
from typing import Any, Optional

from scalene.scalene_library_profiler import ScaleneLibraryProfiler

# Check if JAX is available at import time
_jax_available = False
_jax: Any = None
try:
    import jax

    _jax = jax
    _jax_available = True
except ImportError:
    pass


def is_jax_available() -> bool:
    """Check if JAX is available."""
    return _jax_available


class JaxProfiler(ScaleneLibraryProfiler):
    """Wraps jax.profiler to capture operation timing.

    JAX's profiler writes traces to a directory in TensorBoard format.
    This profiler creates a temporary directory for traces and attempts
    to parse them to extract timing information.

    Note: JAX's trace format is optimized for TensorBoard visualization
    rather than programmatic access, so per-line attribution is limited
    compared to PyTorch's profiler.
    """

    def __init__(self) -> None:
        super().__init__()
        self._trace_dir: Optional[str] = None
        self._profiling_active: bool = False

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
            # If profiler fails to start, just disable it
            self._enabled = False
            self._profiling_active = False
            self._trace_dir = None

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
            # Silently handle any errors during profiler shutdown
            pass
        finally:
            self._enabled = False
            self._profiling_active = False
            # Clean up trace directory
            self._cleanup_trace_dir()

    def _process_traces(self) -> None:
        """Parse JAX trace files to extract timing information.

        JAX traces are in TensorBoard/Chrome trace event format.
        We look for trace.json files and parse them for timing data.
        """
        if not self._trace_dir or not os.path.exists(self._trace_dir):
            return

        try:
            # Look for trace files (Chrome trace event format)
            for root, _, files in os.walk(self._trace_dir):
                for filename in files:
                    if filename.endswith(".json") or filename.endswith(".json.gz"):
                        trace_path = os.path.join(root, filename)
                        self._parse_trace_file(trace_path)
        except Exception:
            # Silently handle parse errors
            pass

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
            # Silently handle parse errors
            pass

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
        # JAX may include this in various forms
        filename = args.get("file") or args.get("filename") or args.get("source_file")
        lineno = args.get("line") or args.get("lineno") or args.get("source_line")

        if filename and lineno:
            try:
                lineno = int(lineno)
                # Attribute the duration to this source line
                self.line_times[filename][lineno] += duration_us
            except (ValueError, TypeError):
                pass

    def _cleanup_trace_dir(self) -> None:
        """Remove temporary trace directory and its contents."""
        if not self._trace_dir:
            return

        try:
            import shutil

            if os.path.exists(self._trace_dir):
                shutil.rmtree(self._trace_dir)
        except Exception:
            pass
        finally:
            self._trace_dir = None

    def clear(self) -> None:
        """Clear all collected timing data."""
        super().clear()
        self._cleanup_trace_dir()
