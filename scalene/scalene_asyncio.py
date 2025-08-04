import asyncio
import sys
import threading

from types import FrameType
from typing import List


class ScaleneAsyncio:
    """Provides a set of methods to collect idle task frames."""

    @staticmethod
    def compute_suspended_frames_to_record() -> List[FrameType]:
        """Collect all frames which belong to suspended tasks."""
        loops = ScaleneAsyncio._get_event_loops()
        return ScaleneAsyncio._get_frames_from_loops(loops)

    @staticmethod
    def _get_event_loops() -> List[asyncio.AbstractEventLoop]:
        """Returns each thread's event loop. If there are none, returns
        the empty array."""
        loops = []
        for t in threading.enumerate():
            frame = sys._current_frames().get(t.ident)
            if frame:
                loop = ScaleneAsyncio._walk_back_until_loop(frame)
                # duplicates shouldn't be possible, but just in case...
                if loop and loop not in loops:
                    loops.append(loop)
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
    def _get_frames_from_loops(loops) -> List[FrameType]:
        """Given LOOPS, returns a flat list of frames corresponding to idle
        tasks."""
        return [
            frames for loop in loops
            for frames in ScaleneAsyncio._get_idle_task_frames(loop)
        ]

    @staticmethod
    def _get_idle_task_frames(loop) -> List[FrameType]:
        """Given an asyncio event loop, returns the list of idle task frames.
        We only care about idle task frames, as running tasks are already
        included elsewhere.

        A task is considered 'idle' if it is pending and not the current
        task."""
        idle = []
        current = asyncio.current_task(loop)
        for task in asyncio.all_tasks(loop):

            # the task is not idle
            if task == current:
                continue

            coro = task.get_coro()

            # the task is suspended but not waiting on any other coroutines.
            # this means it has not started---unstarted tasks do not report
            # meaningful line numbers, so they are also thrown out
            # (note that created tasks are scheduled and not run immediately)
            if getattr(coro, 'cr_await', None) is None:
                continue

            f = ScaleneAsyncio._get_deepest_traceable_frame(coro)
            if f:
                idle.append(f)

        # TODO
        # handle async generators
        # ideally, we would access these from _get_deepest_traceable_frame.
        # doing it this way causes us to also assign the generator's time to
        # the coroutine that called this generator in
        # _get_deepest_traceable_frame
        for ag in loop._asyncgens:
            f = getattr(ag, 'ag_frame', None)
            if f and should_trace(f.f_code.co_filename):
                idle.append(f)
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
            frame = getattr(curr, 'cr_frame', None)
            if frame and should_trace(frame.f_code.co_filename):
                deepest_frame = frame
            curr = getattr(curr, 'cr_await', None)
        return deepest_frame
