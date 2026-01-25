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

from __future__ import annotations

import contextlib
import gzip
import json
import os
import shutil
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any


class ScaleneLibraryProfiler(ABC):
    """Base class for library-specific profilers.

    Subclasses implement profiling for specific libraries (PyTorch, JAX, TensorFlow)
    by wrapping the library's built-in profiling API and extracting per-line timing.

    Attributes:
        line_times: CPU time per source line in microseconds
        gpu_line_times: GPU time per source line in microseconds
    """

    def __init__(self) -> None:
        # dict[filename, dict[lineno, total_time_us]] for CPU time
        self.line_times: dict[str, dict[int, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        # dict[filename, dict[lineno, total_time_us]] for GPU time
        self.gpu_line_times: dict[str, dict[int, float]] = defaultdict(
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

    def get_all_times(self) -> list[tuple[str, int, float, float]]:
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
                result.append(
                    (filename, lineno, cpu_us / 1_000_000, gpu_us / 1_000_000)
                )
        return result

    def clear(self) -> None:
        """Clear all collected timing data."""
        self.line_times.clear()
        self.gpu_line_times.clear()


class ChromeTraceProfiler(ScaleneLibraryProfiler):
    """Base class for profilers that parse Chrome trace event format.

    JAX and TensorFlow both write traces in Chrome trace event format
    (TensorBoard format). This class provides common parsing logic.

    Subclasses should implement:
    - is_available(): Check if the library is installed
    - start(): Start the library's profiler
    - stop(): Stop profiler and call _process_traces()
    - name property: Return the profiler name
    """

    def __init__(self) -> None:
        super().__init__()
        self._trace_dir: str | None = None
        self._profiling_active: bool = False

    def _process_traces(self) -> None:
        """Parse trace files to extract timing information.

        Traces are in Chrome trace event format. We look for .json and
        .json.gz files and parse them for timing data.
        """
        if not self._trace_dir or not os.path.exists(self._trace_dir):
            return

        try:
            for root, _, files in os.walk(self._trace_dir):
                for filename in files:
                    if filename.endswith(".json") or filename.endswith(".json.gz"):
                        trace_path = os.path.join(root, filename)
                        self._parse_trace_file(trace_path)
        except Exception:
            pass  # Silently handle parse errors to avoid disrupting user code

    def _parse_trace_file(self, trace_path: str) -> None:
        """Parse a Chrome trace event format file.

        The trace file contains events with timing information.
        We extract events and try to attribute them to Python source.

        Args:
            trace_path: Path to the trace JSON file.
        """
        try:
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

    def _process_trace_event(self, event: dict[str, Any]) -> None:
        """Process a single trace event and extract timing.

        Chrome trace events have the following relevant fields:
        - name: Event name (e.g., operation name)
        - ph: Phase (B=begin, E=end, X=complete, etc.)
        - ts: Timestamp in microseconds
        - dur: Duration in microseconds (only for X events)
        - args: Additional arguments (may contain Python source info)

        Note: We only process "X" (complete) events because they have
        duration. Begin (B) and End (E) events would require pairing logic.

        Args:
            event: A trace event dictionary.
        """
        # Only process complete events (X) - these have duration
        # B (begin) and E (end) events don't have 'dur' and would need pairing
        phase = event.get("ph", "")
        if phase != "X":
            return

        duration_us = event.get("dur", 0)
        if duration_us <= 0:
            return

        # Extract source info and attribute timing
        filename, lineno = self._extract_source_info(event)
        if filename and lineno:
            with contextlib.suppress(ValueError, TypeError):
                lineno = int(lineno)
                # Route to GPU or CPU timing based on event metadata
                if self._is_gpu_event(event):
                    self.gpu_line_times[filename][lineno] += duration_us
                else:
                    self.line_times[filename][lineno] += duration_us

    def _is_gpu_event(self, event: dict[str, Any]) -> bool:
        """Determine if a trace event represents GPU execution.

        Chrome trace events may include device/stream information indicating
        whether an operation ran on CPU or GPU. This method checks common
        indicators used by JAX and TensorFlow.

        Subclasses can override this for library-specific GPU detection.

        Args:
            event: A trace event dictionary.

        Returns:
            True if the event appears to be a GPU operation.
        """
        args = event.get("args", {})
        name = event.get("name", "").lower()
        cat = event.get("cat", "").lower()

        # Check for explicit device type in args
        device_type = str(args.get("device_type", "")).lower()
        if device_type in ("gpu", "cuda", "xla:gpu"):
            return True

        # Check stream name for GPU indicators
        stream = str(args.get("stream", "")).lower()
        if any(gpu_ind in stream for gpu_ind in ("gpu", "cuda", "device")):
            return True

        # Check event name/category for GPU kernel indicators
        gpu_indicators = ("gpu", "cuda", "kernel", "xla:gpu", "device:")
        if any(ind in name for ind in gpu_indicators):
            return True
        return any(ind in cat for ind in gpu_indicators)

    def _extract_source_info(
        self, event: dict[str, Any]
    ) -> tuple[str | None, int | None]:
        """Extract Python source file and line from a trace event.

        Subclasses can override this to handle library-specific trace formats.

        Args:
            event: A trace event dictionary.

        Returns:
            Tuple of (filename, lineno) or (None, None) if not found.
        """
        args = event.get("args", {})

        # Look for source file/line information in common field names
        filename = args.get("file") or args.get("filename") or args.get("source_file")
        lineno = args.get("line") or args.get("lineno") or args.get("source_line")

        return filename, lineno

    def _cleanup_trace_dir(self) -> None:
        """Remove temporary trace directory and its contents."""
        if not self._trace_dir:
            return

        with contextlib.suppress(Exception):
            if os.path.exists(self._trace_dir):
                shutil.rmtree(self._trace_dir)
        self._trace_dir = None

    def clear(self) -> None:
        """Clear all collected timing data."""
        super().clear()
        self._cleanup_trace_dir()
