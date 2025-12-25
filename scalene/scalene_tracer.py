"""Line tracer for Scalene's memory profiling.

This module provides a unified interface for enabling/disabling line tracing
for memory attribution. On Python 3.12+, it uses sys.monitoring for lower
overhead. On earlier versions, it falls back to the PyEval_SetTrace-based
implementation in pywhere.
"""

from __future__ import annotations

import contextlib
import sys
from types import CodeType, FrameType
from typing import TYPE_CHECKING, Any, Callable

import scalene.scalene_config

if TYPE_CHECKING:
    from scalene.scalene_statistics import ByteCodeIndex, Filename, LineNumber

# Check if we're running Python 3.12+ where sys.monitoring is available
_SYS_MONITORING_AVAILABLE = sys.version_info >= (3, 12)

# Check if we're running Python 3.13+ where the C API for sys.monitoring is available
_SYS_MONITORING_C_API_AVAILABLE = sys.version_info >= (3, 13)

# Flag to force legacy tracer mode (can be set via command-line argument)
_FORCE_LEGACY_TRACER = False

# Flag to force Python callback instead of C callback (for debugging)
_FORCE_PYTHON_CALLBACK = False

# Access sys.monitoring via getattr to avoid mypy issues across Python versions.
# On Python < 3.12, this will be None. On 3.12+, it's the monitoring module.
_monitoring: Any = getattr(sys, "monitoring", None)

# Unique tool ID for Scalene's sys.monitoring registration
# We use sys.monitoring.PROFILER_ID which is available for profiling tools
_SCALENE_TOOL_ID: int = 0
if _SYS_MONITORING_AVAILABLE:
    _SCALENE_TOOL_ID = _monitoring.PROFILER_ID


def set_use_legacy_tracer(use_legacy: bool) -> None:
    """Set whether to use the legacy PyEval_SetTrace tracer.

    This can be used to force the legacy tracer even on Python 3.12+
    for debugging or comparison purposes.
    """
    global _FORCE_LEGACY_TRACER
    _FORCE_LEGACY_TRACER = use_legacy


def set_use_python_callback(use_python: bool) -> None:
    """Set whether to use Python callback instead of C callback.

    This can be used to force the Python callback even on Python 3.13+
    for debugging or comparison purposes.
    """
    global _FORCE_PYTHON_CALLBACK
    _FORCE_PYTHON_CALLBACK = use_python


def _use_sys_monitoring() -> bool:
    """Return True if we should use sys.monitoring for line tracing."""
    return _SYS_MONITORING_AVAILABLE and not _FORCE_LEGACY_TRACER


def _use_c_callback() -> bool:
    """Return True if we should use the C callback for sys.monitoring."""
    return _SYS_MONITORING_C_API_AVAILABLE and not _FORCE_PYTHON_CALLBACK


def _on_stack_check(fname: str, lineno: int) -> bool:
    """Check if the given filename and line are on the current call stack.

    This walks up the call stack to check if we're still executing within
    a call that originated from the specified line. This is important for
    properly handling function calls - if line 10 calls a function, and
    we're now executing inside that function, we shouldn't finalize line 10
    yet because we're still logically "on" that line.

    Args:
        fname: The filename to check for
        lineno: The line number to check for

    Returns:
        True if the filename/lineno pair is found on the stack
    """
    frame: FrameType | None = sys._getframe()
    # Skip frames from the tracer itself
    while frame is not None:
        # Skip our own tracer frames
        if "scalene_tracer" in frame.f_code.co_filename:
            frame = frame.f_back
            continue
        if frame.f_code.co_filename == fname and frame.f_lineno == lineno:
            return True
        frame = frame.f_back
    return False


class ScaleneTracer:
    """Manages line tracing for memory profiling.

    This class handles enabling/disabling line-level tracing to properly
    attribute memory consumption per line. When a memory sample is taken,
    tracing is enabled. When execution moves to a different line, tracing
    is disabled and the memory for that line is accounted.
    """

    # Reference to the last profiled location [filename, lineno, bytecode_index]
    _last_profiled: list[Filename | LineNumber | ByteCodeIndex]

    # Queue for invalidated (completed) lines
    _invalidate_queue: list[tuple[Filename, LineNumber]]

    # Callback to check if a file/function should be traced
    _should_trace: Callable[[Filename, str], bool] | None = None

    # Whether tracing is currently active
    _tracing_active: bool = False

    # The pywhere module (for fallback and shared state)
    _pywhere: object | None = None

    # Whether the tracer has been initialized
    _initialized: bool = False

    # Whether we're using the C line callback (Python 3.13+)
    _use_c_line_callback: bool = False

    @classmethod
    def initialize(
        cls,
        last_profiled: list[Filename | LineNumber | ByteCodeIndex],
        invalidate_queue: list[tuple[Filename, LineNumber]],
        should_trace: Callable[[Filename, str], bool],
    ) -> None:
        """Initialize the tracer with references to Scalene's state.

        Args:
            last_profiled: Reference to the [filename, lineno, bytecode_index] list
            invalidate_queue: Queue for completed line records
            should_trace: Callback to check if a file/function should be traced
        """
        cls._last_profiled = last_profiled
        cls._invalidate_queue = invalidate_queue
        cls._should_trace = should_trace
        cls._initialized = True

        # Import pywhere for shared state access
        from scalene import pywhere  # type: ignore

        cls._pywhere = pywhere

        if _use_sys_monitoring():
            cls._setup_monitoring()

    @classmethod
    def _setup_monitoring(cls) -> None:
        """Set up sys.monitoring callbacks for Python 3.12+."""
        with contextlib.suppress(ValueError):
            # Register Scalene as a monitoring tool
            _monitoring.use_tool_id(_SCALENE_TOOL_ID, "scalene")

        # Choose between C callback (3.13+) and Python callback (3.12)
        if _use_c_callback() and cls._pywhere is not None:
            # Use the C callback from pywhere for better performance
            with contextlib.suppress(AttributeError, NotImplementedError):
                cls._pywhere.setup_sysmon(cls._pywhere.sysmon_line_callback)  # type: ignore[attr-defined]
                cls._use_c_line_callback = True
                return

        # Register the Python LINE event callback
        cls._use_c_line_callback = False
        _monitoring.register_callback(
            _SCALENE_TOOL_ID,
            _monitoring.events.LINE,
            cls._line_callback,
        )

    @classmethod
    def _line_callback(
        cls,
        code: CodeType,
        line_number: int,
    ) -> object:
        """Callback for sys.monitoring LINE events.

        This is called whenever a new line of code is about to execute.
        We check if we've moved to a different line than the last profiled
        one, and if so, finalize the memory accounting for that line.

        Args:
            code: The code object being executed
            line_number: The line number about to execute

        Returns:
            sys.monitoring.DISABLE to disable further LINE events for this code location
        """
        if not cls._tracing_active or not _SYS_MONITORING_AVAILABLE:
            return _monitoring.DISABLE

        # Get the last profiled location
        last_fname = str(cls._last_profiled[0])
        last_lineno = int(cls._last_profiled[1])

        current_fname = code.co_filename

        # Check if we're still on the same line
        if line_number == last_lineno and current_fname == last_fname:
            # Still on the same line, keep tracing
            return None

        # We've moved to a different line.
        # Check if the original line is still on the call stack.
        # This handles cases where line 10 calls a function - we shouldn't
        # finalize line 10 until that function returns.
        if _on_stack_check(last_fname, last_lineno):
            # The original line is still on the stack (we're in a call from it)
            return None

        # We've moved to a genuinely different line - finalize the previous line
        cls._finalize_line()

        return _monitoring.DISABLE

    @classmethod
    def _finalize_line(cls) -> None:
        """Finalize memory accounting for the current line."""
        cls._tracing_active = False

        # Disable LINE events globally
        if _SYS_MONITORING_AVAILABLE:
            _monitoring.set_events(_SCALENE_TOOL_ID, 0)

        # Get the last profiled location before resetting
        last_fname = cls._last_profiled[0]
        last_lineno = cls._last_profiled[1]

        # Reset last profiled to sentinel values
        # Use the same sentinel values as the C++ code
        cls._last_profiled[0] = "NADA"  # type: ignore
        cls._last_profiled[1] = 0  # type: ignore
        cls._last_profiled[2] = 0  # type: ignore

        # Allocate the NEWLINE trigger to signal the C++ side
        # This matches allocate_newline() in pywhere.cpp
        bytearray(scalene.scalene_config.NEWLINE_TRIGGER_LENGTH)

        # Mark as invalidated in pywhere
        if cls._pywhere:
            cls._pywhere.set_last_profiled_invalidated_true()  # type: ignore

        # Add to the invalidate queue
        cls._invalidate_queue.append((last_fname, last_lineno))  # type: ignore

    @classmethod
    def enable(cls, frame: FrameType) -> None:
        """Enable line tracing starting from the given frame.

        Args:
            frame: The frame to start tracing from
        """
        if _use_sys_monitoring() and cls._initialized:
            cls._enable_monitoring(frame)
        else:
            # Fall back to legacy PyEval_SetTrace if not initialized,
            # if running on Python < 3.12, or if legacy mode is forced
            cls._enable_legacy(frame)

    @classmethod
    def _enable_monitoring(cls, frame: FrameType) -> None:
        """Enable tracing using sys.monitoring (Python 3.12+)."""
        cls._tracing_active = True

        # Use C implementation if available (Python 3.13+)
        if cls._use_c_line_callback and cls._pywhere is not None:
            try:
                cls._pywhere.enable_sysmon()  # type: ignore
                return
            except (AttributeError, NotImplementedError):
                pass

        # Enable LINE events globally for this tool (Python callback)
        _monitoring.set_events(_SCALENE_TOOL_ID, _monitoring.events.LINE)

    @classmethod
    def _enable_legacy(cls, frame: FrameType) -> None:
        """Enable tracing using PyEval_SetTrace (Python < 3.12)."""
        if cls._pywhere is None:
            # Lazy import pywhere if not already loaded
            from scalene import pywhere  # type: ignore

            cls._pywhere = pywhere
        cls._pywhere.enable_settrace(frame)  # type: ignore

    @classmethod
    def disable(cls) -> None:
        """Disable line tracing."""
        if _use_sys_monitoring() and cls._initialized:
            cls._disable_monitoring()
        else:
            cls._disable_legacy()

    @classmethod
    def _disable_monitoring(cls) -> None:
        """Disable tracing using sys.monitoring (Python 3.12+)."""
        cls._tracing_active = False

        # Use C implementation if available (Python 3.13+)
        if cls._use_c_line_callback and cls._pywhere is not None:
            with contextlib.suppress(AttributeError, NotImplementedError):
                cls._pywhere.disable_sysmon()  # type: ignore
                return

        with contextlib.suppress(ValueError, RuntimeError):
            _monitoring.set_events(_SCALENE_TOOL_ID, 0)

    @classmethod
    def _disable_legacy(cls) -> None:
        """Disable tracing using PyEval_SetTrace (Python < 3.12)."""
        if cls._pywhere is None:
            # Lazy import pywhere if not already loaded
            from scalene import pywhere  # type: ignore

            cls._pywhere = pywhere
        cls._pywhere.disable_settrace()  # type: ignore

    @classmethod
    def cleanup(cls) -> None:
        """Clean up monitoring resources."""
        cls._initialized = False
        if _SYS_MONITORING_AVAILABLE:
            with contextlib.suppress(ValueError, RuntimeError):
                # Disable all events
                _monitoring.set_events(_SCALENE_TOOL_ID, 0)
                # Unregister the callback
                _monitoring.register_callback(
                    _SCALENE_TOOL_ID,
                    _monitoring.events.LINE,
                    None,
                )
                # Free the tool ID
                _monitoring.free_tool_id(_SCALENE_TOOL_ID)


def enable_tracing(frame: FrameType) -> None:
    """Enable line tracing starting from the given frame.

    This is the main entry point for enabling line tracing.
    """
    ScaleneTracer.enable(frame)


def disable_tracing() -> None:
    """Disable line tracing.

    This is the main entry point for disabling line tracing.
    """
    ScaleneTracer.disable()


def initialize_tracer(
    last_profiled: list[Filename | LineNumber | ByteCodeIndex],
    invalidate_queue: list[tuple[Filename, LineNumber]],
    should_trace: Callable[[Filename, str], bool],
) -> None:
    """Initialize the tracer with Scalene's state.

    This must be called before enable_tracing can be used effectively
    on Python 3.12+.
    """
    ScaleneTracer.initialize(last_profiled, invalidate_queue, should_trace)


def cleanup_tracer() -> None:
    """Clean up tracer resources."""
    ScaleneTracer.cleanup()


def using_sys_monitoring() -> bool:
    """Return True if using sys.monitoring (Python 3.12+).

    This returns True if sys.monitoring is available AND we're not
    forcing legacy tracer mode.
    """
    return _use_sys_monitoring()


def using_c_callback() -> bool:
    """Return True if using the C callback for sys.monitoring (Python 3.13+).

    This returns True if:
    - sys.monitoring is being used
    - The C API is available (Python 3.13+)
    - We're not forcing Python callback mode
    - The C callback was successfully registered
    """
    return (
        _use_sys_monitoring()
        and _use_c_callback()
        and ScaleneTracer._use_c_line_callback
    )
