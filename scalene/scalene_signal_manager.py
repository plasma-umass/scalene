"""
Signal handling manager for Scalene profiler.

This module extracts signal handling functionality from the main Scalene class
to improve code organization and reduce complexity.
"""

import contextlib
import os
import signal
import sys
import threading
import time
from typing import Generic, List, Optional, TypeVar

from scalene.scalene_signals import ScaleneSignals, SignalHandlerFunction
from scalene.scalene_sigqueue import ScaleneSigQueue

T = TypeVar("T")


class ScaleneSignalManager(Generic[T]):
    """Manages signal handling for Scalene profiler."""

    def __init__(self) -> None:
        self.__signals = ScaleneSignals()
        self.__sigqueues: List[ScaleneSigQueue[T]] = []

        # Store original signal functions
        self.__orig_signal = signal.signal
        self.__orig_exit = os._exit
        self.__orig_raise_signal = signal.raise_signal
        self.__orig_kill = os.kill

        if sys.platform != "win32":
            self.__orig_setitimer = signal.setitimer
            self.__orig_siginterrupt = signal.siginterrupt

        # Timer control for Windows
        self.timer_signals = True

        # Store CPU signal handler for direct calling on Windows
        # (signal.raise_signal cannot be called from background threads)
        self.__cpu_signal_handler: Optional[SignalHandlerFunction] = None

        # Timer thread reference for Windows (for proper cleanup)
        self.__timer_thread: Optional[threading.Thread] = None

    def get_signals(self) -> ScaleneSignals:
        """Return the ScaleneSignals instance."""
        return self.__signals

    def set_timer_signals(self, enabled: bool) -> None:
        """Enable or disable timer signals."""
        self.timer_signals = enabled

    def add_signal_queue(self, sigqueue: ScaleneSigQueue[T]) -> None:
        """Add a signal queue to be managed."""
        self.__sigqueues.append(sigqueue)

    def start_signal_queues(self) -> None:
        """Start the signal processing queues (i.e., their threads)."""
        for sigq in self.__sigqueues:
            sigq.start()

    def stop_signal_queues(self) -> None:
        """Stop the signal processing queues (i.e., their threads)."""
        for sigq in self.__sigqueues:
            sigq.stop()

    def stop_timer_thread(self) -> None:
        """Stop the Windows timer thread and wait for it to finish."""
        if sys.platform != "win32":
            return
        self.timer_signals = False
        if hasattr(self, "_ScaleneSignalManager__timer_thread") and self.__timer_thread:
            # Give the thread a short time to finish its current iteration
            self.__timer_thread.join(timeout=0.1)
            self.__timer_thread = None

    def enable_signals_win32(
        self,
        cpu_signal_handler: SignalHandlerFunction,
        cpu_sampling_rate: float,
        alloc_sigq: Optional[ScaleneSigQueue[T]] = None,
        memcpy_sigq: Optional[ScaleneSigQueue[T]] = None,
    ) -> None:
        """Enable signals for Windows platform."""
        assert sys.platform == "win32"

        self.timer_signals = True
        # Store the CPU signal handler for direct calling from the timer thread.
        # On Windows, signal.raise_signal() cannot be called from background threads
        # (it raises ValueError), so we call the handler directly instead.
        self.__cpu_signal_handler = cpu_signal_handler
        # Also register as actual signal handler for any external signal delivery
        self.__orig_signal(
            self.__signals.cpu_signal,
            cpu_signal_handler,
        )
        # On Windows, we simulate timer signals by running a non-daemon thread
        # that directly calls the CPU signal handler at the configured sampling rate.
        # The thread must be non-daemon so it can continue sampling while the main
        # thread is still running, even if main finishes early (short-running programs).
        # Cleanup is handled by stop_timer_thread() called from _disable_signals().
        self.__timer_thread = threading.Thread(
            target=lambda: self.windows_timer_loop(cpu_sampling_rate), daemon=False
        )
        self.__timer_thread.start()
        self.start_signal_queues()

        # On Windows, start a memory polling thread to periodically process
        # malloc/free samples since we don't have Unix signals
        if alloc_sigq is not None:
            self.__alloc_sigq_win = alloc_sigq
            self.__memcpy_sigq_win = memcpy_sigq
            self.__memory_polling_active = True
            mem_thread = threading.Thread(
                target=self._windows_memory_poll_loop, daemon=True
            )
            mem_thread.start()

    def windows_timer_loop(self, cpu_sampling_rate: float) -> None:
        """For Windows, periodically call the CPU signal handler from a background thread.

        Note: We cannot use signal.raise_signal() from background threads on Windows
        (it raises ValueError). Instead, we call the CPU signal handler directly.
        The handler uses sys._current_frames() which is thread-safe and works from
        any thread, giving us access to all thread stacks including the main thread.

        Unlike Unix where setitimer controls timing, on Windows we use a simple
        sleep-based loop at the user-configured sampling rate.
        """
        assert sys.platform == "win32"

        # Initial delay to let user code start executing before we begin sampling.
        # Without this, the first samples would be taken during Scalene's
        # initialization rather than during the user's actual code.
        time.sleep(0.01)  # 10ms initial delay

        while self.timer_signals:
            # Call the CPU signal handler first, then sleep.
            # This ensures we record samples even if the program exits quickly.
            if self.__cpu_signal_handler is not None:
                with contextlib.suppress(Exception):
                    self.__cpu_signal_handler(self.__signals.cpu_signal, None)
            time.sleep(cpu_sampling_rate)

    def _windows_memory_poll_loop(self) -> None:
        """For Windows, periodically poll for memory profiling data."""
        assert sys.platform == "win32"
        # Poll every 10ms for memory data
        poll_interval = 0.01
        while getattr(self, "_ScaleneSignalManager__memory_polling_active", False):
            time.sleep(poll_interval)
            # Trigger malloc/free processing
            if (
                hasattr(self, "_ScaleneSignalManager__alloc_sigq_win")
                and self.__alloc_sigq_win
            ):
                self.__alloc_sigq_win.put([0])  # type: ignore[arg-type]
            # Trigger memcpy processing
            if (
                hasattr(self, "_ScaleneSignalManager__memcpy_sigq_win")
                and self.__memcpy_sigq_win
            ):
                self.__memcpy_sigq_win.put((0, None))  # type: ignore[arg-type]

    def stop_windows_memory_polling(self) -> None:
        """Stop the Windows memory polling thread."""
        if hasattr(self, "_ScaleneSignalManager__memory_polling_active"):
            self.__memory_polling_active = False

    def enable_signals(
        self,
        malloc_signal_handler: SignalHandlerFunction,
        free_signal_handler: SignalHandlerFunction,
        memcpy_signal_handler: SignalHandlerFunction,
        term_signal_handler: SignalHandlerFunction,
        cpu_signal_handler: SignalHandlerFunction,
        cpu_sampling_rate: float,
        alloc_sigq: Optional[ScaleneSigQueue[T]] = None,
        memcpy_sigq: Optional[ScaleneSigQueue[T]] = None,
    ) -> None:
        """Set up the signal handlers to handle interrupts for profiling and start the
        timer interrupts."""
        if sys.platform == "win32":
            self.enable_signals_win32(
                cpu_signal_handler, cpu_sampling_rate, alloc_sigq, memcpy_sigq
            )
            return

        self.start_signal_queues()
        # Set signal handlers for various events.
        for sig, handler in [
            (self.__signals.malloc_signal, malloc_signal_handler),
            (self.__signals.free_signal, free_signal_handler),
            (self.__signals.memcpy_signal, memcpy_signal_handler),
            (signal.SIGTERM, term_signal_handler),
            (self.__signals.cpu_signal, cpu_signal_handler),
        ]:
            self.__orig_signal(sig, handler)
        # Set every signal to restart interrupted system calls.
        for s in self.__signals.get_all_signals():
            self.__orig_siginterrupt(s, False)
        self.__orig_setitimer(
            self.__signals.cpu_timer_signal,
            cpu_sampling_rate,
        )

    def setup_lifecycle_signals(
        self,
        start_signal_handler: SignalHandlerFunction,
        stop_signal_handler: SignalHandlerFunction,
        interruption_handler: SignalHandlerFunction,
    ) -> None:
        """Setup lifecycle control signals."""
        if sys.platform != "win32":
            for sig, handler in [
                (
                    self.__signals.start_profiling_signal,
                    start_signal_handler,
                ),
                (
                    self.__signals.stop_profiling_signal,
                    stop_signal_handler,
                ),
            ]:
                self.__orig_signal(sig, handler)
                self.__orig_siginterrupt(sig, False)
        self.__orig_signal(signal.SIGINT, interruption_handler)

    def send_signal_to_children(
        self, child_pids: "set[int]", signal_type: signal.Signals
    ) -> None:
        """Send a signal to all child processes."""
        for pid in child_pids:
            self.__orig_kill(pid, signal_type)

    def send_signal_to_child(self, pid: int, signal_type: signal.Signals) -> None:
        """Send a signal to a specific child process."""
        self.__orig_kill(pid, signal_type)

    def restart_timer(self, interval: float) -> None:
        """Restart the CPU profiling timer with the specified interval.

        On Windows, this is a no-op because the timer thread runs at a fixed
        sampling rate and doesn't need to be restarted after each sample.
        """
        if sys.platform != "win32":
            self.__orig_setitimer(
                self.__signals.cpu_timer_signal,
                interval,
            )
        # On Windows, the timer thread runs continuously at a fixed rate,
        # so there's nothing to restart.
