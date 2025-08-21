"""
Signal handling manager for Scalene profiler.

This module extracts signal handling functionality from the main Scalene class
to improve code organization and reduce complexity.
"""

import os
import signal
import sys
import threading
import time
from typing import Callable, List, Optional

from types import FrameType

from scalene.scalene_signals import ScaleneSignals
from scalene.scalene_sigqueue import ScaleneSigQueue


def _generate_exponential_sample(scale: float) -> float:
    import math
    import random
    u = random.random()  # Uniformly distributed random number between 0 and 1
    return -scale * math.log(1 - u)

class ScaleneSignalManager:
    """Manages signal handling for Scalene profiler."""
    
    def __init__(self) -> None:
        import queue
        self.__signals = ScaleneSignals()
        self.__sigqueues: List[ScaleneSigQueue] = []
        self.__windows_queue : Optional[queue.Queue] = None  # Will be initialized if needed
        
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
        
    def get_signals(self) -> ScaleneSignals:
        """Return the ScaleneSignals instance."""
        return self.__signals
        
    def set_timer_signals(self, enabled: bool) -> None:
        """Enable or disable timer signals."""
        self.timer_signals = enabled
        
    def add_signal_queue(self, sigqueue: ScaleneSigQueue) -> None:
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
            
    def enable_signals_win32(self, cpu_signal_handler: Callable, cpu_sampling_rate: float) -> None:
        """Enable signals for Windows platform."""
        assert sys.platform == "win32"
        import queue
        
        self.timer_signals = True
        self.__orig_signal(
            self.__signals.cpu_signal,
            cpu_signal_handler,
        )
        # On Windows, we simulate timer signals by running a background thread.
        self.timer_signals = True
        self.__windows_queue = queue.Queue()
        t = threading.Thread(target=lambda: self.windows_timer_loop(cpu_sampling_rate))
        t.start()
        self.__windows_queue.put(None)
        self.start_signal_queues()
        
    def windows_timer_loop(self, cpu_sampling_rate: float) -> None:
        """For Windows, send periodic timer signals; launch as a background thread."""
        assert sys.platform == "win32"
        self.timer_signals = True
        while self.timer_signals:
            if self.__windows_queue:
                self.__windows_queue.get()
            time.sleep(cpu_sampling_rate)
            self.__orig_raise_signal(self.__signals.cpu_signal)
            
    def enable_signals(self, 
                      malloc_signal_handler: Callable,
                      free_signal_handler: Callable, 
                      memcpy_signal_handler: Callable,
                      term_signal_handler: Callable,
                      cpu_signal_handler: Callable,
                      cpu_sampling_rate: float) -> None:
        """Set up the signal handlers to handle interrupts for profiling and start the
        timer interrupts."""
        if sys.platform == "win32":
            self.enable_signals_win32(cpu_signal_handler, cpu_sampling_rate)
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
            _generate_exponential_sample(cpu_sampling_rate),
        )
        
    def setup_lifecycle_signals(self, 
                               start_signal_handler: Callable,
                               stop_signal_handler: Callable,
                               interruption_handler: Callable) -> None:
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
        
    def send_signal_to_children(self, child_pids: set, signal_type: signal.Signals) -> None:
        """Send a signal to all child processes."""
        for pid in child_pids:
            self.__orig_kill(pid, signal_type)
            
    def send_signal_to_child(self, pid: int, signal_type: signal.Signals) -> None:
        """Send a signal to a specific child process."""
        self.__orig_kill(pid, signal_type)
            
    def restart_timer(self, interval: float) -> None:
        """Restart the CPU profiling timer with the specified interval."""
        interval = _generate_exponential_sample(interval)
        if sys.platform != "win32":
            self.__orig_setitimer(
                self.__signals.cpu_timer_signal,
                interval,
            )
        else:
            if self.__windows_queue:
                self.__windows_queue.put(None)
