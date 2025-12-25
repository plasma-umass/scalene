"""Profiler lifecycle management for Scalene."""

from __future__ import annotations

import contextlib
import os
import signal
import sys
import time
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from pathlib import Path
    from types import FrameType

    from scalene.scalene_arguments import ScaleneArguments
    from scalene.scalene_json import ScaleneJSON
    from scalene.scalene_output import ScaleneOutput
    from scalene.scalene_signal_manager import ScaleneSignalManager
    from scalene.scalene_signals import SignumType
    from scalene.scalene_statistics import ScaleneStatistics


class ScaleneLifecycle:
    """Manages the profiler lifecycle (start, stop, signals)."""

    def __init__(
        self,
        args: ScaleneArguments,
        stats: ScaleneStatistics,
        signal_manager: ScaleneSignalManager[Any],
        output: ScaleneOutput,
        json_output: ScaleneJSON,
    ) -> None:
        """Initialize the lifecycle manager.

        Args:
            args: Scalene arguments.
            stats: Statistics object.
            signal_manager: Signal manager instance.
            output: Output handler.
            json_output: JSON output handler.
        """
        self._args = args
        self._stats = stats
        self._signal_manager = signal_manager
        self._output = output
        self._json = json_output
        self._start_time: int = 0
        self._initialized: bool = False
        self._is_child: bool = False
        self._python_alias_dir: Path | None = None
        self._pid: int = 0

        # Store original functions for cleanup
        if sys.platform != "win32":
            self._orig_setitimer = signal.setitimer
        self._orig_signal = signal.signal

    def set_initialized(self) -> None:
        """Mark the profiler as initialized."""
        self._initialized = True

    @property
    def initialized(self) -> bool:
        """Check if the profiler is initialized."""
        return self._initialized

    @property
    def start_time(self) -> int:
        """Get the profiling start time in nanoseconds."""
        return self._start_time

    def set_child_info(self, is_child: bool, pid: int) -> None:
        """Set child process information."""
        self._is_child = is_child
        self._pid = pid

    def set_python_alias_dir(self, path: Path) -> None:
        """Set the Python alias directory for cleanup."""
        self._python_alias_dir = path

    def start(
        self,
        enable_signals_func: Callable[[], None],
        accelerator: Any | None = None,
    ) -> None:
        """Initiate profiling.

        Args:
            enable_signals_func: Function to enable profiler signals.
            accelerator: Optional GPU accelerator.
        """
        if not self._initialized:
            print(
                "ERROR: Do not try to invoke `start` if you have not called Scalene using one of the methods\n"
                "in https://github.com/plasma-umass/scalene#using-scalene\n"
                "(The most likely issue is that you need to run your code with `scalene`, not `python`).",
                file=sys.stderr,
            )
            sys.exit(1)

        self._stats.start_clock()
        enable_signals_func()
        self._start_time = time.monotonic_ns()

        # Start neuron monitor if using Neuron accelerator
        if accelerator is not None and hasattr(accelerator, "start_monitor"):
            accelerator.start_monitor()

        if self._args.memory:
            from scalene import pywhere  # type: ignore

            pywhere.set_scalene_done_false()

    def stop(
        self,
        disable_signals_func: Callable[[], None],
        profile_filename: str,
        find_browser_func: Callable[[], bool] | None = None,
    ) -> None:
        """Complete profiling.

        Args:
            disable_signals_func: Function to disable profiler signals.
            profile_filename: Default profile filename.
            find_browser_func: Optional function to check for browser availability.
        """
        if self._args.memory:
            from scalene import pywhere  # type: ignore

            pywhere.set_scalene_done_true()

        disable_signals_func()
        self._stats.stop_clock()

        if self._args.outfile:
            profile_filename = os.path.join(
                os.path.dirname(self._args.outfile),
                os.path.basename(profile_filename),
            )

        if self._args.web and not self._args.cli and not self._is_child:
            self._setup_web_output(find_browser_func, profile_filename)

    def _setup_web_output(
        self,
        find_browser_func: Callable[[], bool] | None,
        profile_filename: str,
    ) -> None:
        """Set up web output if browser is available."""
        if find_browser_func is None:
            return

        try:
            if not find_browser_func():
                self._args.web = False
            else:
                self._args.json = True
                self._output.html = False
                self._output.output_file = profile_filename
        except Exception:
            self._args.web = False

    def disable_signals(self, retry: bool = True) -> None:
        """Turn off the profiling signals."""
        if sys.platform == "win32":
            self._signal_manager.set_timer_signals(False)
            self._signal_manager.stop_windows_memory_polling()
            self._signal_manager.stop_signal_queues()
            return

        try:
            signals = self._signal_manager.get_signals()
            assert signals.cpu_timer_signal is not None
            self._orig_setitimer(signals.cpu_timer_signal, 0)
            for sig in [
                signals.malloc_signal,
                signals.free_signal,
                signals.memcpy_signal,
            ]:
                self._orig_signal(sig, signal.SIG_IGN)
            self._signal_manager.stop_signal_queues()
        except Exception:
            if retry:
                self.disable_signals(retry=False)

    def exit_handler(self) -> None:
        """When we exit, disable all signals and clean up."""
        self.disable_signals()

        # Delete the temporary directory
        with contextlib.suppress(Exception):
            if not self._pid and self._python_alias_dir:
                self._python_alias_dir.cleanup()  # type: ignore

        with contextlib.suppress(Exception):
            os.remove(f"/tmp/scalene-malloc-lock{os.getpid()}")
