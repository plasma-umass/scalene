# Import the necessary libraries.
import signal
import sys
from typing import List, Tuple


class ScaleneSignals:
    """
    ScaleneSignals class to configure timer signals for CPU profiling and
    to get various types of signals.
    """

    def __init__(self) -> None:
        # Configure timer signals using set_timer_signals method (defined below).
        self.set_timer_signals(use_virtual_time=True)
        # Set profiling signals depending upon the platform.
        if sys.platform != "win32":
            self.start_profiling_signal = signal.SIGILL
            self.stop_profiling_signal = signal.SIGBUS
            self.memcpy_signal = signal.SIGPROF
            # Malloc and free signals are generated by include/sampleheap.hpp.
            self.malloc_signal = signal.SIGXCPU
            self.free_signal = signal.SIGXFSZ
        else:
            # Currently, only CPU profiling signals are activated for Windows
            self.start_profiling_signal = None
            self.stop_profiling_signal = None
            self.memcpy_signal = None
            self.malloc_signal = None
            self.free_signal = None

    def set_timer_signals(self, use_virtual_time: bool = True) -> None:
        """
        Set up timer signals for CPU profiling.

        use_virtual_time: bool, default True
            If True, sets virtual timer signals, otherwise sets real timer signals.
        """
        if sys.platform == "win32":
            self.cpu_signal = signal.SIGBREAK
            self.cpu_timer_signal = None
            return
        if use_virtual_time:
            self.cpu_timer_signal = signal.ITIMER_VIRTUAL
            self.cpu_signal = signal.SIGVTALRM
        else:
            self.cpu_timer_signal = signal.ITIMER_REAL
            self.cpu_signal = signal.SIGALRM

    def get_timer_signals(self) -> Tuple[int, signal.Signals]:
        """
        Return the signals used for CPU profiling.

        Returns:
        --------
        Tuple[int, signal.Signals]
            Returns 2-tuple of the integers representing the CPU timer signal and the CPU signal.
        """
        return self.cpu_timer_signal, self.cpu_signal
    def get_lifecycle_signals(self):
        return (self.start_profiling_signal, self.stop_profiling_signal)
    def get_all_signals(self) -> List[int]:
        """
        Return all the signals used for controlling profiling, except the CPU timer.

        Returns:
        --------
        List[int]
            Returns a list of integers representing all the profiling signals except the CPU timer.
        """
        return [
            self.start_profiling_signal,
            self.stop_profiling_signal,
            self.memcpy_signal,
            self.malloc_signal,
            self.free_signal,
            self.cpu_signal,
        ]
