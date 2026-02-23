"""Tests for async profiling support (ScaleneAsync, AsyncStatistics)."""

import asyncio
import sys
from unittest.mock import MagicMock

import pytest

from scalene.scalene_async import ScaleneAsync, SuspendedTaskInfo
from scalene.scalene_statistics import AsyncStatistics


# --- SuspendedTaskInfo tests ---


class TestSuspendedTaskInfo:
    def test_creation(self) -> None:
        info = SuspendedTaskInfo("test.py", 42, 1000000, "Task-1")
        assert info.filename == "test.py"
        assert info.lineno == 42
        assert info.suspend_time_ns == 1000000
        assert info.task_name == "Task-1"

    def test_namedtuple_unpacking(self) -> None:
        info = SuspendedTaskInfo("test.py", 10, 500, "my_task")
        filename, lineno, ns, name = info
        assert filename == "test.py"
        assert lineno == 10
        assert ns == 500
        assert name == "my_task"


# --- ScaleneAsync tests ---


class TestScaleneAsyncState:
    def setup_method(self) -> None:
        """Reset ScaleneAsync state before each test."""
        ScaleneAsync._enabled = False
        ScaleneAsync._suspended_tasks = {}
        ScaleneAsync._active_task_id = None

    def test_enable_disable(self) -> None:
        assert not ScaleneAsync._enabled
        ScaleneAsync.enable()
        assert ScaleneAsync._enabled
        ScaleneAsync.disable()
        assert not ScaleneAsync._enabled

    def test_enable_clears_state(self) -> None:
        ScaleneAsync._suspended_tasks = {1: SuspendedTaskInfo("a.py", 1, 0, "t")}
        ScaleneAsync._active_task_id = 42
        ScaleneAsync.enable()
        assert ScaleneAsync._suspended_tasks == {}
        assert ScaleneAsync._active_task_id is None

    def test_disable_clears_state(self) -> None:
        ScaleneAsync._enabled = True
        ScaleneAsync._suspended_tasks = {1: SuspendedTaskInfo("a.py", 1, 0, "t")}
        ScaleneAsync.disable()
        assert ScaleneAsync._suspended_tasks == {}
        assert ScaleneAsync._active_task_id is None

    def test_get_suspended_snapshot_empty(self) -> None:
        ScaleneAsync.enable()
        snapshot = ScaleneAsync.get_suspended_snapshot()
        assert snapshot == []
        ScaleneAsync.disable()

    def test_get_suspended_snapshot_with_tasks(self) -> None:
        ScaleneAsync.enable()
        info1 = SuspendedTaskInfo("a.py", 10, 100, "Task-1")
        info2 = SuspendedTaskInfo("b.py", 20, 200, "Task-2")
        ScaleneAsync._suspended_tasks = {1: info1, 2: info2}
        if sys.version_info >= (3, 12):
            # Strategy B: reads directly from _suspended_tasks
            snapshot = ScaleneAsync.get_suspended_snapshot()
            assert len(snapshot) == 2
            assert info1 in snapshot
            assert info2 in snapshot
        ScaleneAsync.disable()


class TestIsInEventLoop:
    def _make_frame(
        self, module_name: str, func_name: str, f_back: object = None
    ) -> MagicMock:
        """Create a mock frame with the given module and function name."""
        frame = MagicMock()
        frame.f_globals = {"__name__": module_name}
        frame.f_code.co_name = func_name
        frame.f_back = f_back
        return frame

    def test_asyncio_base_events(self) -> None:
        frame = self._make_frame("asyncio.base_events", "_run_once")
        assert ScaleneAsync.is_in_event_loop(frame)

    def test_selectors_module(self) -> None:
        frame = self._make_frame("selectors", "select")
        assert ScaleneAsync.is_in_event_loop(frame)

    def test_asyncio_selector_events(self) -> None:
        frame = self._make_frame("asyncio.selector_events", "sock_recv")
        assert ScaleneAsync.is_in_event_loop(frame)

    def test_user_code_not_event_loop(self) -> None:
        frame = self._make_frame("my_module", "my_function")
        assert not ScaleneAsync.is_in_event_loop(frame)

    def test_walks_frame_chain(self) -> None:
        """Event loop frame deeper in the chain should still be detected."""
        inner_frame = self._make_frame("asyncio.base_events", "_run_once")
        outer_frame = self._make_frame("my_module", "main", f_back=inner_frame)
        assert ScaleneAsync.is_in_event_loop(outer_frame)

    def test_none_frame(self) -> None:
        assert not ScaleneAsync.is_in_event_loop(None)

    def test_max_depth_limit(self) -> None:
        """Should stop walking after max_depth frames."""
        # Build a chain of 25 user frames with event loop at the bottom
        frames = [self._make_frame("user", "func")]
        for i in range(24):
            frames.append(self._make_frame("user", f"func_{i}", f_back=frames[-1]))
        # The event loop frame is more than 20 frames deep - should not be found
        result = ScaleneAsync.is_in_event_loop(frames[-1])
        assert not result


class TestIsCoroutineFunction:
    def test_regular_function(self) -> None:
        code = MagicMock()
        code.co_flags = 0
        assert not ScaleneAsync.is_coroutine_function(code)

    def test_coroutine_function(self) -> None:
        code = MagicMock()
        code.co_flags = 0x100  # CO_COROUTINE
        assert ScaleneAsync.is_coroutine_function(code)

    def test_coroutine_with_other_flags(self) -> None:
        code = MagicMock()
        code.co_flags = 0x100 | 0x20  # CO_COROUTINE | CO_GENERATOR
        assert ScaleneAsync.is_coroutine_function(code)

    def test_no_co_flags(self) -> None:
        """Object without co_flags attribute should return False."""
        assert not ScaleneAsync.is_coroutine_function(object())


class TestWalkAwaitChain:
    def test_empty_chain(self) -> None:
        chain = ScaleneAsync.walk_await_chain(None)
        assert chain == []

    def test_single_coroutine(self) -> None:
        coro = MagicMock()
        frame = MagicMock()
        frame.f_code.co_filename = "test.py"
        frame.f_lineno = 42
        frame.f_code.co_name = "my_coro"
        coro.cr_frame = frame
        coro.cr_await = None
        chain = ScaleneAsync.walk_await_chain(coro)
        assert len(chain) == 1
        assert chain[0] == ("test.py", 42, "my_coro")

    def test_nested_coroutines(self) -> None:
        inner = MagicMock()
        inner_frame = MagicMock()
        inner_frame.f_code.co_filename = "inner.py"
        inner_frame.f_lineno = 10
        inner_frame.f_code.co_name = "inner_coro"
        inner.cr_frame = inner_frame
        inner.cr_await = None

        outer = MagicMock()
        outer_frame = MagicMock()
        outer_frame.f_code.co_filename = "outer.py"
        outer_frame.f_lineno = 20
        outer_frame.f_code.co_name = "outer_coro"
        outer.cr_frame = outer_frame
        outer.cr_await = inner

        chain = ScaleneAsync.walk_await_chain(outer)
        assert len(chain) == 2
        assert chain[0] == ("outer.py", 20, "outer_coro")
        assert chain[1] == ("inner.py", 10, "inner_coro")

    def test_cycle_detection(self) -> None:
        """Should handle circular await chains without infinite loop."""
        coro = MagicMock()
        frame = MagicMock()
        frame.f_code.co_filename = "test.py"
        frame.f_lineno = 1
        frame.f_code.co_name = "coro"
        coro.cr_frame = frame
        # Make it point back to itself
        coro.cr_await = coro
        chain = ScaleneAsync.walk_await_chain(coro)
        assert len(chain) == 1  # Should only visit once


# --- AsyncStatistics tests ---


class TestAsyncStatistics:
    def test_init(self) -> None:
        stats = AsyncStatistics()
        assert stats.total_async_await_samples == 0.0
        assert len(stats.async_await_samples) == 0
        assert len(stats.async_task_names) == 0
        assert len(stats.is_coroutine) == 0
        assert len(stats.async_concurrency) == 0

    def test_accumulation(self) -> None:
        stats = AsyncStatistics()
        stats.async_await_samples["test.py"][10] += 0.5
        stats.async_await_samples["test.py"][20] += 0.3
        stats.total_async_await_samples += 0.8
        assert stats.async_await_samples["test.py"][10] == 0.5
        assert stats.async_await_samples["test.py"][20] == 0.3
        assert stats.total_async_await_samples == 0.8

    def test_task_names(self) -> None:
        stats = AsyncStatistics()
        stats.async_task_names["test.py"][10].add("Task-1")
        stats.async_task_names["test.py"][10].add("Task-2")
        stats.async_task_names["test.py"][10].add("Task-1")  # duplicate
        assert stats.async_task_names["test.py"][10] == {"Task-1", "Task-2"}

    def test_concurrency_tracking(self) -> None:
        stats = AsyncStatistics()
        stats.async_concurrency["test.py"][10].push(3)
        stats.async_concurrency["test.py"][10].push(5)
        stats.async_concurrency["test.py"][10].push(1)
        assert stats.async_concurrency["test.py"][10].mean() == pytest.approx(3.0)
        assert stats.async_concurrency["test.py"][10].peak() == 5.0
        assert stats.async_concurrency["test.py"][10].size() == 3

    def test_is_coroutine(self) -> None:
        stats = AsyncStatistics()
        stats.is_coroutine["my_module.my_coro"] = True
        stats.is_coroutine["my_module.regular_fn"] = False
        assert stats.is_coroutine["my_module.my_coro"] is True
        assert stats.is_coroutine["my_module.regular_fn"] is False

    def test_clear(self) -> None:
        stats = AsyncStatistics()
        stats.async_await_samples["test.py"][10] = 1.0
        stats.total_async_await_samples = 1.0
        stats.async_task_names["test.py"][10].add("Task-1")
        stats.is_coroutine["fn"] = True
        stats.async_concurrency["test.py"][10].push(3)
        stats.clear()
        assert stats.total_async_await_samples == 0.0
        assert len(stats.async_await_samples) == 0
        assert len(stats.async_task_names) == 0
        assert len(stats.is_coroutine) == 0
        assert len(stats.async_concurrency) == 0


# --- Polling strategy tests ---


class TestPollingStrategy:
    def test_poll_with_suspended_tasks(self) -> None:
        """Test that _poll_suspended_tasks finds suspended coroutines."""
        results: list[SuspendedTaskInfo] = []

        async def slow_task() -> None:
            await asyncio.sleep(10)  # Will be cancelled before completing

        async def runner() -> None:
            task = asyncio.create_task(slow_task(), name="slow")
            # Give the task a moment to start and then suspend
            await asyncio.sleep(0.01)
            # Now poll - slow_task should be suspended at the sleep
            snapshot = ScaleneAsync._poll_suspended_tasks()
            results.extend(snapshot)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # Expected: the task was explicitly cancelled as part of this test.
                pass

        asyncio.run(runner())
        # Should have found at least the slow_task suspended
        assert len(results) >= 1
        task_names = [r.task_name for r in results]
        assert "slow" in task_names

    def test_poll_no_running_loop(self) -> None:
        """_poll_suspended_tasks should return empty list outside event loop."""
        # Outside any event loop, should return empty
        result = ScaleneAsync._poll_suspended_tasks()
        assert isinstance(result, list)
        assert len(result) == 0


# --- sys.monitoring tests (Python 3.12+) ---


@pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason="sys.monitoring requires Python 3.12+",
)
class TestSysMonitoring:
    def setup_method(self) -> None:
        ScaleneAsync._enabled = False
        ScaleneAsync._suspended_tasks = {}
        ScaleneAsync._active_task_id = None

    def teardown_method(self) -> None:
        ScaleneAsync.disable()

    def test_install_uninstall(self) -> None:
        """Test that sys.monitoring callbacks can be installed and removed."""
        ScaleneAsync.enable()
        # Verify tool is registered
        name = sys.monitoring.get_tool(ScaleneAsync._MONITORING_TOOL_ID)
        assert name == "scalene_async"
        ScaleneAsync.disable()
        # After disable, tool should be freed
        name = sys.monitoring.get_tool(ScaleneAsync._MONITORING_TOOL_ID)
        assert name is None

    def test_on_yield_non_coroutine(self) -> None:
        """Non-coroutine code should be ignored by _on_yield."""
        code = MagicMock()
        code.co_flags = 0  # Not a coroutine
        ScaleneAsync._on_yield(code, 0)
        assert len(ScaleneAsync._suspended_tasks) == 0

    def test_on_resume_non_coroutine(self) -> None:
        """Non-coroutine code should be ignored by _on_resume."""
        code = MagicMock()
        code.co_flags = 0
        ScaleneAsync._on_resume(code, 0)
        assert ScaleneAsync._active_task_id is None
