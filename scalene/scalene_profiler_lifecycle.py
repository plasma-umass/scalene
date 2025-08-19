"""Profiler lifecycle management for Scalene."""

from __future__ import annotations

import atexit
import sys
import time
import threading
from typing import Optional, Any

from scalene.scalene_statistics import ScaleneStatistics


class ProfilerLifecycle:
    """Manages the lifecycle of the profiler (start, stop, cleanup)."""
    
    def __init__(self, stats: ScaleneStatistics, args):
        self._stats = stats
        self._args = args
        self._initialized = False
        self._start_time = 0
        self._stop_time = 0
        self._running = False
        self._cleanup_registered = False
        
    def is_initialized(self) -> bool:
        """Check if the profiler has been initialized."""
        return self._initialized
        
    def set_initialized(self) -> None:
        """Mark the profiler as initialized."""
        self._initialized = True
        
    def is_running(self) -> bool:
        """Check if the profiler is currently running."""
        return self._running
        
    def get_start_time(self) -> float:
        """Get the profiler start time in nanoseconds."""
        return self._start_time
        
    def get_elapsed_time(self) -> float:
        """Get the elapsed time since profiling started."""
        if self._start_time == 0:
            return 0.0
        current_time = time.perf_counter_ns()
        return (current_time - self._start_time) / 1e9
        
    def start(self, signal_handler, process_manager) -> None:
        """Start the profiler."""
        if self._running:
            return
            
        # Record start time
        self._start_time = time.perf_counter_ns()
        self._running = True
        
        # Register cleanup handler if not already done
        if not self._cleanup_registered:
            atexit.register(self.exit_handler)
            self._cleanup_registered = True
            
        # Enable signal handling
        signal_handler.enable_signals()
        signal_handler.start_signal_queues()
        
        # Set timer signals
        signal_handler.get_signals().set_timer_signals(self._args.use_virtual_time)
        
        # Clear any existing statistics
        self._stats.clear_all()
        
    def stop(self, signal_handler) -> None:
        """Stop the profiler."""
        if not self._running:
            return
            
        # Record stop time
        self._stop_time = time.perf_counter_ns()
        self._running = False
        
        # Disable signal handling
        signal_handler.disable_signals()
        signal_handler.stop_signal_queues()
        
    def is_done(self) -> bool:
        """Check if profiling is complete."""
        return not self._running and self._stop_time > 0
        
    def exit_handler(self) -> None:
        """Handle cleanup when the program exits."""
        try:
            if self._running:
                # Generate final output if needed
                self._generate_final_output()
        except Exception:
            # Best effort cleanup - don't let exceptions propagate
            pass
            
    def _generate_final_output(self) -> None:
        """Generate final profiling output."""
        # This would contain the logic for generating the final report
        # when the profiler is shutting down
        pass
        
    def clear_metrics(self) -> None:
        """Clear all profiling metrics."""
        self._stats.clear_all()
        
    def reset(self) -> None:
        """Reset the profiler state."""
        self._start_time = 0
        self._stop_time = 0
        self._running = False
        self._stats.clear_all()
        
    def profile_code(self, 
                    code_object: Any, 
                    local_vars: dict, 
                    global_vars: dict, 
                    program_args: list,
                    signal_handler,
                    process_manager) -> int:
        """Profile execution of code object."""
        exit_status = 0
        
        try:
            # Start profiling
            self.start(signal_handler, process_manager)
            
            # Execute the code
            exec(code_object, global_vars, local_vars)
            
        except SystemExit as e:
            exit_status = e.code if isinstance(e.code, int) else 1
        except Exception as e:
            print(f"Error during profiling: {e}", file=sys.stderr)
            exit_status = 1
        finally:
            # Stop profiling
            self.stop(signal_handler)
            
        return exit_status
        
    def force_cleanup(self, process_manager, mapfiles: list) -> None:
        """Force cleanup of all resources."""
        try:
            # Stop profiling if running
            if self._running:
                self._running = False
                
            # Clean up mapfiles
            for mapfile in mapfiles:
                try:
                    mapfile.close()
                    if not process_manager.is_child_process():
                        mapfile.cleanup()
                except Exception:
                    pass
                    
            # Clean up process resources
            process_manager.cleanup_process_resources()
            
        except Exception:
            # Best effort cleanup
            pass