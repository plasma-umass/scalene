"""PyTorch profiler integration for Scalene.

This module wraps torch.profiler to capture PyTorch operation timing and
attribute it back to Python source lines, enabling accurate profiling of
JIT-compiled PyTorch code on both CPU and GPU.

See https://github.com/plasma-umass/scalene/issues/908
"""

import time
from typing import Any, List

from scalene.scalene_library_profiler import ScaleneLibraryProfiler

# Check if PyTorch is available at import time
_torch_available = False
_cuda_available = False
_mps_available = False
_torch: Any = None
try:
    import torch

    _torch = torch
    _torch_available = True
    _cuda_available = torch.cuda.is_available()
    # Check for MPS (Apple Silicon GPU) availability
    if hasattr(torch.backends, "mps"):
        _mps_available = torch.backends.mps.is_available()
except ImportError:
    pass


def is_torch_available() -> bool:
    """Check if PyTorch is available."""
    return _torch_available


def is_cuda_available() -> bool:
    """Check if CUDA is available for GPU profiling."""
    return _cuda_available


def is_mps_available() -> bool:
    """Check if MPS (Apple Silicon GPU) is available for GPU profiling."""
    return _mps_available


class TorchProfiler(ScaleneLibraryProfiler):
    """Wraps torch.profiler to capture operation timing on CPU and GPU.

    This profiler uses PyTorch's built-in profiling infrastructure with
    stack trace collection to attribute operation time back to the Python
    source lines that initiated them. When CUDA is available, it also
    captures GPU kernel execution time.
    """

    def __init__(self) -> None:
        super().__init__()
        self._profiler: Any = None
        self._gpu_enabled: bool = False
        # MPS (Apple Silicon GPU) timing
        self._mps_enabled: bool = False
        self._mps_start_time: float = 0.0
        self._mps_total_time: float = 0.0  # Total MPS GPU time in seconds
        # Note: line_times and gpu_line_times are inherited from base class

    def is_available(self) -> bool:
        """Check if PyTorch is available for profiling."""
        return _torch_available

    @property
    def name(self) -> str:
        return "PyTorch"

    def start(self) -> None:
        """Start the PyTorch profiler."""
        if not _torch_available or _torch is None:
            return
        try:
            # Build list of activities to profile
            activities: List[Any] = [_torch.profiler.ProfilerActivity.CPU]

            # Add CUDA activity if available
            if _cuda_available:
                activities.append(_torch.profiler.ProfilerActivity.CUDA)
                self._gpu_enabled = True

            # Use torch.profiler (newer API) with stack recording
            self._profiler = _torch.profiler.profile(
                activities=activities,
                with_stack=True,  # Capture Python call stacks
                record_shapes=False,
            )
            self._profiler.__enter__()
            self._enabled = True

            # Start MPS timing if available (and CUDA is not)
            # This gives us per-process GPU time on Apple Silicon
            if _mps_available and not _cuda_available:
                try:
                    _torch.mps.synchronize()  # Ensure GPU is idle before starting
                    self._mps_start_time = time.perf_counter()
                    self._mps_enabled = True
                except Exception:
                    self._mps_enabled = False
        except Exception:
            # If profiler fails to start, just disable it
            self._enabled = False
            self._gpu_enabled = False
            self._mps_enabled = False
            self._profiler = None

    def stop(self) -> None:
        """Stop the PyTorch profiler and process collected events."""
        if not self._enabled or self._profiler is None:
            return

        # Capture MPS timing before stopping profiler
        if self._mps_enabled:
            try:
                _torch.mps.synchronize()  # Wait for all GPU work to complete
                self._mps_total_time = time.perf_counter() - self._mps_start_time
            except Exception:
                self._mps_total_time = 0.0
            finally:
                self._mps_enabled = False

        try:
            self._profiler.__exit__(None, None, None)
            self._process_events()
        except Exception:
            # Silently handle any errors during profiler shutdown
            pass
        finally:
            self._enabled = False
            self._gpu_enabled = False
            self._profiler = None

    def _process_events(self) -> None:
        """Extract timing from profiler events and attribute to source lines."""
        if self._profiler is None:
            return

        import re

        try:
            events = self._profiler.key_averages(group_by_stack_n=10)
            for event in events:
                # Get the stack trace for this event
                if hasattr(event, "stack") and event.stack:
                    # Stack is a list of strings like "filename(lineno): funcname"
                    for frame_str in event.stack:
                        # Parse the frame string
                        # Format: "filename(lineno): funcname"
                        match = re.match(r"(.+)\((\d+)\):", frame_str)
                        if match:
                            filename = match.group(1)
                            lineno = int(match.group(2))
                            # Skip <string> entries (from interactive/exec)
                            if filename != "<string>":
                                # Attribute CPU time (in microseconds) to this line
                                if hasattr(event, "cpu_time_total"):
                                    self.line_times[filename][
                                        lineno
                                    ] += event.cpu_time_total

                                # Attribute CUDA/GPU time if available
                                # cuda_time_total is the total GPU kernel time in microseconds
                                if self._gpu_enabled and hasattr(
                                    event, "cuda_time_total"
                                ):
                                    cuda_time = event.cuda_time_total
                                    if cuda_time > 0:
                                        self.gpu_line_times[filename][
                                            lineno
                                        ] += cuda_time
        except Exception:
            # Silently handle any errors during event processing
            pass

    # Note: get_line_time, get_gpu_line_time, has_gpu_timing inherited from base class

    def get_mps_total_time(self) -> float:
        """Get total MPS (Apple Silicon GPU) time in seconds.

        This is the wall-clock time during which GPU work was performed,
        providing per-process GPU timing on Apple Silicon.
        """
        return self._mps_total_time

    def has_mps_timing(self) -> bool:
        """Check if MPS timing was captured."""
        return self._mps_total_time > 0

    def clear(self) -> None:
        """Clear all collected timing data."""
        super().clear()
        self._mps_total_time = 0.0
