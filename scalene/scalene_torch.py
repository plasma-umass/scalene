"""PyTorch profiler integration for Scalene.

This module wraps torch.profiler to capture PyTorch operation timing and
attribute it back to Python source lines, enabling accurate profiling of
JIT-compiled PyTorch code on both CPU and GPU.

See https://github.com/plasma-umass/scalene/issues/908
"""

from collections import defaultdict
from typing import Any, Dict, List

# Check if PyTorch is available at import time
_torch_available = False
_cuda_available = False
_torch = None
try:
    import torch as _torch

    _torch_available = True
    _cuda_available = _torch.cuda.is_available()
except ImportError:
    pass


def is_torch_available() -> bool:
    """Check if PyTorch is available."""
    return _torch_available


def is_cuda_available() -> bool:
    """Check if CUDA is available for GPU profiling."""
    return _cuda_available


class TorchProfiler:
    """Wraps torch.profiler to capture operation timing on CPU and GPU.

    This profiler uses PyTorch's built-in profiling infrastructure with
    stack trace collection to attribute operation time back to the Python
    source lines that initiated them. When CUDA is available, it also
    captures GPU kernel execution time.
    """

    def __init__(self) -> None:
        self._profiler: Any = None
        self._enabled: bool = False
        self._gpu_enabled: bool = False
        # Dict[filename, Dict[lineno, total_time_us]] for CPU time
        self.line_times: Dict[str, Dict[int, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        # Dict[filename, Dict[lineno, total_time_us]] for GPU/CUDA time
        self.gpu_line_times: Dict[str, Dict[int, float]] = defaultdict(
            lambda: defaultdict(float)
        )

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
        except Exception:
            # If profiler fails to start, just disable it
            self._enabled = False
            self._gpu_enabled = False
            self._profiler = None

    def stop(self) -> None:
        """Stop the PyTorch profiler and process collected events."""
        if not self._enabled or self._profiler is None:
            return
        try:
            self._profiler.__exit__(None, None, None)
            self._process_events()
        except Exception:
            # Silently handle any errors during profiler shutdown
            pass
        finally:
            self._enabled = False

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
                                    self.line_times[filename][lineno] += event.cpu_time_total

                                # Attribute CUDA/GPU time if available
                                # cuda_time_total is the total GPU kernel time in microseconds
                                if self._gpu_enabled and hasattr(event, "cuda_time_total"):
                                    cuda_time = event.cuda_time_total
                                    if cuda_time > 0:
                                        self.gpu_line_times[filename][lineno] += cuda_time
        except Exception:
            # Silently handle any errors during event processing
            pass

    def get_line_time(self, filename: str, lineno: int) -> float:
        """Get total PyTorch CPU operation time (in seconds) for a source line."""
        return self.line_times.get(filename, {}).get(lineno, 0.0) / 1_000_000

    def get_gpu_line_time(self, filename: str, lineno: int) -> float:
        """Get total PyTorch GPU/CUDA time (in seconds) for a source line."""
        return self.gpu_line_times.get(filename, {}).get(lineno, 0.0) / 1_000_000

    def has_gpu_timing(self) -> bool:
        """Check if any GPU timing was captured."""
        return len(self.gpu_line_times) > 0

    def clear(self) -> None:
        """Clear all collected timing data."""
        self.line_times.clear()
        self.gpu_line_times.clear()
