"""Scalene async profiling support.

Tracks suspended coroutines and provides await-time attribution.
When enabled (via --async), integrates with the CPU signal handler
to detect when the main thread is in the event loop and snapshot
which coroutines are suspended at which await points.
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any, NamedTuple


class SuspendedTaskInfo(NamedTuple):
    """Information about a suspended async task."""

    filename: str
    lineno: int
    suspend_time_ns: int
    task_name: str


class ScaleneAsync:
    """Tracks async/await profiling state.

    Two instrumentation strategies:
    - Strategy A (3.9+): When CPU signal fires and main thread is in event loop,
      poll asyncio.all_tasks() to find suspended coroutines.
    - Strategy B (3.12+): Use sys.monitoring PY_YIELD/PY_RESUME for precise tracking.
    """

    _enabled: bool = False

    # Task ID -> suspended task info (for Strategy B / sys.monitoring)
    _suspended_tasks: dict[int, SuspendedTaskInfo] = {}
    _MAX_SUSPENDED_TASKS = 10000  # Cap to prevent unbounded growth

    # Currently active task ID (for Strategy B)
    _active_task_id: int | None = None

    # Module names that indicate event loop internals
    _EVENT_LOOP_MODULES: set[str] = frozenset(
        {  # type: ignore[assignment]
            "asyncio.base_events",
            "asyncio.events",
            "asyncio.runners",
            "asyncio.selector_events",
            "asyncio.proactor_events",
            "asyncio.unix_events",
            "asyncio.windows_events",
            "selectors",
            "_selector",
        }
    )

    # Function names within event loop modules that indicate idle/selecting
    _EVENT_LOOP_FUNCTIONS: set[str] = frozenset(
        {  # type: ignore[assignment]
            "_run_once",
            "select",
            "_poll",
            "run_forever",
            "run_until_complete",
        }
    )

    @classmethod
    def enable(cls) -> None:
        """Enable async profiling."""
        cls._enabled = True
        cls._suspended_tasks = {}
        cls._active_task_id = None
        if sys.version_info >= (3, 12):
            cls._install_sys_monitoring()

    @classmethod
    def disable(cls) -> None:
        """Disable async profiling."""
        if sys.version_info >= (3, 12):
            cls._uninstall_sys_monitoring()
        cls._enabled = False
        cls._suspended_tasks = {}
        cls._active_task_id = None

    @classmethod
    def is_in_event_loop(cls, frame: Any) -> bool:
        """Check if the given frame (or its callers) is inside the asyncio event loop.

        Walks up the frame chain looking for frames from asyncio internals
        or selector modules. This is a heuristic used to detect when the
        main thread is idle waiting for I/O in the event loop.
        """
        current = frame
        depth = 0
        max_depth = 20  # Don't walk too far up
        while current is not None and depth < max_depth:
            module = current.f_globals.get("__name__", "")
            func_name = current.f_code.co_name
            if module in cls._EVENT_LOOP_MODULES:
                return True
            if module.startswith("asyncio.") and func_name in cls._EVENT_LOOP_FUNCTIONS:
                return True
            current = current.f_back
            depth += 1
        return False

    @classmethod
    def get_suspended_snapshot(cls) -> list[SuspendedTaskInfo]:
        """Return a snapshot of currently suspended tasks.

        This is designed to be lightweight and safe to call from
        a signal handler context - it just reads the dict.
        For Strategy B (sys.monitoring), returns the tracked state directly.
        For Strategy A (polling), calls _poll_suspended_tasks().
        """
        if sys.version_info >= (3, 12) and cls._suspended_tasks:
            return list(cls._suspended_tasks.values())
        # Fall back to polling
        return cls._poll_suspended_tasks()

    @classmethod
    def _poll_suspended_tasks(cls) -> list[SuspendedTaskInfo]:
        """Strategy A: Poll asyncio.all_tasks() to find suspended coroutines.

        This is called from the signal queue processor (daemon thread),
        not from the signal handler itself. By the time this runs, some
        tasks may have changed state, but over many samples this gives
        correct proportional attribution.
        """
        result: list[SuspendedTaskInfo] = []
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                return result
        except RuntimeError:
            return result

        try:
            tasks = asyncio.all_tasks(loop)
        except RuntimeError:
            return result

        now_ns = time.monotonic_ns()
        for task in tasks:
            if task.done():
                continue
            coro = task.get_coro()
            if coro is None:
                continue
            # Get the frame where the coroutine is suspended
            cr_frame = getattr(coro, "cr_frame", None)
            if cr_frame is None:
                # Coroutine is currently executing (not suspended) or finished
                continue
            filename = cr_frame.f_code.co_filename
            lineno = (
                cr_frame.f_lineno
                if cr_frame.f_lineno is not None
                else cr_frame.f_code.co_firstlineno
            )
            task_name = task.get_name()
            result.append(SuspendedTaskInfo(filename, lineno, now_ns, task_name))
        return result

    @classmethod
    def walk_await_chain(cls, coro: Any) -> list[tuple[str, int, str]]:
        """Walk the await chain of a coroutine.

        Returns a list of (filename, lineno, function_name) tuples
        representing the logical async call chain from outermost to innermost.
        """
        chain: list[tuple[str, int, str]] = []
        visited: set[int] = set()
        current = coro
        while current is not None:
            coro_id = id(current)
            if coro_id in visited:
                break
            visited.add(coro_id)

            cr_frame = getattr(current, "cr_frame", None)
            if cr_frame is not None:
                filename = cr_frame.f_code.co_filename
                lineno = (
                    cr_frame.f_lineno
                    if cr_frame.f_lineno is not None
                    else cr_frame.f_code.co_firstlineno
                )
                func_name = cr_frame.f_code.co_name
                chain.append((filename, lineno, func_name))

            # Follow cr_await to the inner awaitable
            current = getattr(current, "cr_await", None)
        return chain

    @classmethod
    def is_coroutine_function(cls, code: Any) -> bool:
        """Check if a code object is for a coroutine function."""
        CO_COROUTINE = 0x100
        return bool(getattr(code, "co_flags", 0) & CO_COROUTINE)

    # --- Strategy B: sys.monitoring (Python 3.12+) ---

    # Use OPTIMIZER_ID (5) to avoid conflict with PROFILER_ID (2) used by scalene_tracer
    _MONITORING_TOOL_ID = 5

    @classmethod
    def _install_sys_monitoring(cls) -> None:
        """Install sys.monitoring callbacks for PY_YIELD and PY_RESUME."""
        if sys.version_info < (3, 12):
            return
        try:
            monitoring = sys.monitoring
            tool_id = cls._MONITORING_TOOL_ID
            monitoring.use_tool_id(tool_id, "scalene_async")
            # Enable PY_YIELD and PY_RESUME events
            monitoring.set_events(
                tool_id,
                monitoring.events.PY_YIELD | monitoring.events.PY_RESUME,
            )
            monitoring.register_callback(
                tool_id,
                monitoring.events.PY_YIELD,
                cls._on_yield,
            )
            monitoring.register_callback(
                tool_id,
                monitoring.events.PY_RESUME,
                cls._on_resume,
            )
        except (ValueError, AttributeError):
            # Tool ID already in use or sys.monitoring not available
            pass

    @classmethod
    def _uninstall_sys_monitoring(cls) -> None:
        """Remove sys.monitoring callbacks."""
        if sys.version_info < (3, 12):
            return
        try:
            monitoring = sys.monitoring
            tool_id = cls._MONITORING_TOOL_ID
            monitoring.set_events(tool_id, 0)
            monitoring.register_callback(
                tool_id,
                monitoring.events.PY_YIELD,
                None,
            )
            monitoring.register_callback(
                tool_id,
                monitoring.events.PY_RESUME,
                None,
            )
            monitoring.free_tool_id(tool_id)
        except (ValueError, AttributeError):
            # Best-effort cleanup: tool ID may already be freed or monitoring unavailable.
            pass

    @classmethod
    def _on_yield(cls, code: Any, instruction_offset: int, retval: Any = None) -> None:
        """Called when a coroutine yields (suspends at an await point).

        Only tracks coroutine code objects (CO_COROUTINE flag set).
        """
        if not cls.is_coroutine_function(code):
            return
        # Try to find the current task
        try:
            task = asyncio.current_task()
            if task is None:
                return
        except RuntimeError:
            return

        task_id = id(task)
        filename = code.co_filename
        # We don't have the frame here, so use the code object's first line
        # as a fallback. The actual line will be refined from cr_frame later.
        lineno = code.co_firstlineno
        now_ns = time.monotonic_ns()
        task_name = task.get_name()
        # Prune stale entries if dict grows too large (tasks that yielded
        # but were cancelled/GC'd without resuming)
        if len(cls._suspended_tasks) >= cls._MAX_SUSPENDED_TASKS:
            cls._suspended_tasks.clear()
        cls._suspended_tasks[task_id] = SuspendedTaskInfo(
            filename, lineno, now_ns, task_name
        )

    @classmethod
    def _on_resume(cls, code: Any, instruction_offset: int) -> None:
        """Called when a coroutine resumes from an await point."""
        if not cls.is_coroutine_function(code):
            return
        try:
            task = asyncio.current_task()
            if task is None:
                return
        except RuntimeError:
            return

        task_id = id(task)
        cls._suspended_tasks.pop(task_id, None)
        cls._active_task_id = task_id
