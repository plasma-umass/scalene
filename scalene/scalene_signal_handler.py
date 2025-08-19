"""Signal handling functionality for Scalene profiler."""

from __future__ import annotations

import signal
import threading
import contextlib
from typing import Set, Tuple, Optional, Any, List

from scalene.scalene_signals import ScaleneSignals
from scalene.scalene_signal_manager import ScaleneSignalManager
from scalene.scalene_sigqueue import ScaleneSigQueue


class SignalHandler:
    """Handles signal management and processing for profiling."""
    
    def __init__(self):
        self._signals = ScaleneSignals()
        self._signal_manager = ScaleneSignalManager()
        self._original_lock = threading.Lock()
        self._all_signals_set: Set[int] = set()
        self._lifecycle_disabled = False
        
        # Signal queues for different types of events
        self._alloc_sigq: Optional[ScaleneSigQueue] = None
        self._memcpy_sigq: Optional[ScaleneSigQueue] = None
        self._sigqueues: List[ScaleneSigQueue] = []
        
    def get_signals(self) -> ScaleneSignals:
        """Get the signals manager."""
        return self._signals
        
    def get_signal_manager(self) -> ScaleneSignalManager:
        """Get the signal manager."""
        return self._signal_manager
        
    def get_original_lock(self) -> threading.Lock:
        """Get the original threading lock."""
        return self._original_lock
        
    def setup_signal_queues(self, alloc_processor, memcpy_processor) -> None:
        """Set up signal queues for memory profiling events."""
        self._alloc_sigq = ScaleneSigQueue(alloc_processor)
        self._memcpy_sigq = ScaleneSigQueue(memcpy_processor)
        self._sigqueues = [self._alloc_sigq, self._memcpy_sigq]
        
        # Add signal queues to the signal manager
        self._signal_manager.add_signal_queue(self._alloc_sigq)
        self._signal_manager.add_signal_queue(self._memcpy_sigq)
        
    def get_alloc_sigqueue(self) -> Optional[ScaleneSigQueue]:
        """Get the allocation signal queue."""
        return self._alloc_sigq
        
    def get_memcpy_sigqueue(self) -> Optional[ScaleneSigQueue]:
        """Get the memcpy signal queue."""
        return self._memcpy_sigq
        
    def get_all_signals_set(self) -> Set[int]:
        """Get all signals that are being handled."""
        return self._all_signals_set
        
    def get_lifecycle_signals(self) -> Tuple[signal.Signals, signal.Signals]:
        """Get the lifecycle signals (start and stop)."""
        return self._signals.start_signal, self._signals.stop_signal
        
    def disable_lifecycle(self) -> None:
        """Disable lifecycle signal handling."""
        self._lifecycle_disabled = True
        
    def get_lifecycle_disabled(self) -> bool:
        """Check if lifecycle signals are disabled."""
        return self._lifecycle_disabled
        
    def get_timer_signals(self) -> Tuple[int, signal.Signals]:
        """Get timer signals for profiling."""
        return self._signals.cpu_timer_signal, self._signals.cpu_signal
        
    def start_signal_queues(self) -> None:
        """Start all signal queues."""
        for sigqueue in self._sigqueues:
            sigqueue.start()
            
    def stop_signal_queues(self) -> None:
        """Stop all signal queues."""
        for sigqueue in self._sigqueues:
            sigqueue.stop()
            
    def enable_signals(self) -> None:
        """Enable signal handling for profiling."""
        self._signals.enable_signals()
        
    def disable_signals(self, retry: bool = True) -> None:
        """Disable signal handling for profiling."""
        try:
            self._signals.disable_signals()
        except Exception:
            if retry:
                # Try once more
                with contextlib.suppress(Exception):
                    self._signals.disable_signals()
                    
    def setup_signal_handlers(self, 
                            malloc_handler, 
                            free_handler, 
                            memcpy_handler,
                            start_handler,
                            stop_handler,
                            term_handler) -> None:
        """Set up signal handlers for profiling events."""
        # Set up memory profiling signal handlers
        self._signals.set_malloc_signal_handler(malloc_handler)
        self._signals.set_free_signal_handler(free_handler)
        self._signals.set_memcpy_signal_handler(memcpy_handler)
        
        # Set up lifecycle signal handlers
        self._signals.set_start_signal_handler(start_handler)
        self._signals.set_stop_signal_handler(stop_handler)
        self._signals.set_term_signal_handler(term_handler)