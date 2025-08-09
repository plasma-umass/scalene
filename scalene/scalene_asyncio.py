import asyncio
import sys
import threading
import gc

from types import (
    AsyncGeneratorType,
    FrameType
)
from typing import (
    Optional,
    List,
    Tuple,
    cast,
)


class ScaleneAsyncio:
    """Provides a set of methods to collect idle task frames."""

    should_trace = None
    loops: List[Tuple[asyncio.AbstractEventLoop, int]] = []
    current_task = None

    @staticmethod
    def current_task_exists(tident) -> bool:
        """Given TIDENT, returns true if a current task exists.  Returns
        true if no event loop is running on TIDENT."""
        current = True
        for loop, t in ScaleneAsyncio.loops:
            if t == tident:
                current = asyncio.current_task(loop)
                break
        return bool(current)

    @staticmethod
    def compute_suspended_frames_to_record(should_trace) -> \
            List[Tuple[FrameType, int, FrameType]]:
        """Collect all frames which belong to suspended tasks."""
        # TODO this is an ugly way to access the function
        ScaleneAsyncio.should_trace = should_trace
        ScaleneAsyncio.loops = ScaleneAsyncio._get_event_loops()

        return ScaleneAsyncio._get_frames_from_loops(ScaleneAsyncio.loops)

    @staticmethod
    def _get_event_loops() -> List[Tuple[asyncio.AbstractEventLoop, int]]:
        """Returns each thread's event loop. If there are none, returns
        the empty array."""
        loops = []
        for t in threading.enumerate():
            frame = sys._current_frames().get(t.ident)
            if frame:
                loop = ScaleneAsyncio._walk_back_until_loop(frame)
                # duplicates shouldn't be possible, but just in case...
                if loop and loop not in loops:
                    loops.append((loop, cast(int, t.ident)))
        return loops

    @staticmethod
    def _walk_back_until_loop(frame) -> asyncio.AbstractEventLoop:
        """Helper for get_event_loops.

        Walks back the callstack until we are in a method named '_run_once'.
        If this becomes true and the 'self' variable is an instance of
        AbstractEventLoop, then we return that variable.

        This works because _run_once is one of the main methods asyncio uses
        to facilitate its event loop, and is always on the stack while the
        loop runs."""
        while frame:
            if frame.f_code.co_name == '_run_once' and \
               'self' in frame.f_locals:
                loop = frame.f_locals['self']
                if isinstance(loop, asyncio.AbstractEventLoop):
                    return loop
            else:
                frame = frame.f_back
        return None

    @staticmethod
    def _get_frames_from_loops(loops) -> \
            List[Tuple[FrameType, int, FrameType]]:
        """Given LOOPS, returns a flat list of frames corresponding to idle
        tasks."""
        return [
            (frame, tident, None) for loop, tident in loops
            for frame in ScaleneAsyncio._get_idle_task_frames(loop)
        ]

    @staticmethod
    def _get_idle_task_frames(loop) -> List[FrameType]:
        """Given an asyncio event loop, returns the list of idle task frames.
        We only care about idle task frames, as running tasks are already
        included elsewhere.

        A task is considered 'idle' if it is pending and not the current
        task."""
        idle = []

        # required later
        ScaleneAsyncio.current_task = asyncio.current_task(loop)

        for task in asyncio.all_tasks(loop):
            if not ScaleneAsyncio._task_is_valid(task) or \
               task == ScaleneAsyncio.current_task:
                continue

            coro = task.get_coro()

            frame = ScaleneAsyncio._get_deepest_traceable_frame(coro)
            if frame:
                idle.append(cast(FrameType, frame))

        return idle

    @staticmethod
    def _get_deepest_traceable_frame(coro) -> FrameType:
        """Get the deepest frame of coro we care to trace.
        This is possible because each corooutine keeps a reference to the
        coroutine it is waiting on.

        Note that it cannot be the case that a task is suspended in a frame
        that does not belong to a coroutine, asyncio is very particular about
        that! This is also why we only track idle tasks this way."""
        curr = coro
        deepest_frame = None
        while curr:
            frame, curr = ScaleneAsyncio._trace_down(curr)

            if frame is None:
                break

            if ScaleneAsyncio.should_trace(frame.f_code.co_filename,
                                           frame.f_code.co_name):
                deepest_frame = frame

        # if this task is found to point to another task we're profiling,
        # then we will get the deepest frame later and should return nothing.
        # this is specific to gathering futures, i.e., gather statement.
        if curr is not None:
            tasks = getattr(curr, '_children', [])
            if any(
                    ScaleneAsyncio._task_is_valid(task)
                    for task in tasks
            ):
                return None

        return deepest_frame

    @staticmethod
    def _task_is_valid(task) -> bool:
        """Returns FALSE if TASK is uninteresting to the user.

        A task is interesting if it has actually started executing, and if
        a child task did not originate from it.
        """
        if not isinstance(task, asyncio.Task):
            return False

        if task._state != 'PENDING':
            return False

        coro = task.get_coro()

        # the task hasn't even run yet
        # assumes that all started tasks are sitting at an await
        # statement.
        # if this isn't the case, the associated coroutine will
        # be 'waiting' on the coroutine declaration. No! Bad!
        frame, awaitable = ScaleneAsyncio._trace_down(coro)
        if task != ScaleneAsyncio.current_task and \
           (frame is None or awaitable is None):
            return False

        return True

    @staticmethod
    def _trace_down(awaitable) -> \
            Tuple[Optional[FrameType], Optional[asyncio.Future]]:
        """Helper for _get_deepest_traceable_frame
        Given AWAITABLE, returns its associated frame and the future it is
        waiting on, if any."""
        if asyncio.iscoroutine(awaitable) and \
           hasattr(awaitable, 'cr_await') and \
           hasattr(awaitable, 'cr_frame'):
            return getattr(awaitable, 'cr_frame', None), \
                getattr(awaitable, 'cr_await', None)

        # attempt to obtain an async-generator
        # can gc be avoided here?
        refs = gc.get_referents(awaitable)
        if refs:
            awaitable = refs[0]

        if isinstance(awaitable, AsyncGeneratorType):
            return getattr(awaitable, 'ag_frame', None), \
                getattr(awaitable, 'ag_await', None)

        if isinstance(awaitable, asyncio.Future):
            # return whatever future we found.
            return None, awaitable

        return None, None
