"""Tests for refactored scalene profiler components."""

import pytest
from scalene.scalene_profiler_core import ProfilerCore
from scalene.scalene_signal_handler import SignalHandler
from scalene.scalene_trace_manager import TraceManager
from scalene.scalene_process_manager import ProcessManager
from scalene.scalene_profiler_lifecycle import ProfilerLifecycle
from scalene.scalene_statistics import ScaleneStatistics, Filename, LineNumber
from scalene.scalene_arguments import ScaleneArguments


def test_profiler_core_initialization():
    """Test that ProfilerCore initializes properly."""
    stats = ScaleneStatistics()
    core = ProfilerCore(stats)
    
    # Test that last profiled is initialized
    last_profiled = core.get_last_profiled()
    assert len(last_profiled) == 3
    assert last_profiled[0] == Filename("NADA")
    assert last_profiled[1] == LineNumber(0)
    
    # Test setting last profiled
    core.set_last_profiled(Filename("test.py"), LineNumber(10), 0)
    last_profiled = core.get_last_profiled()
    assert last_profiled[0] == Filename("test.py")
    assert last_profiled[1] == LineNumber(10)


def test_signal_handler_initialization():
    """Test that SignalHandler initializes properly."""
    handler = SignalHandler()
    
    # Test that signals are accessible
    signals = handler.get_signals()
    assert signals is not None
    
    # Test that signal manager is accessible
    signal_manager = handler.get_signal_manager()
    assert signal_manager is not None


def test_trace_manager_initialization():
    """Test that TraceManager initializes properly."""
    # Create mock args
    args = ScaleneArguments()
    args.profile_exclude = ""
    args.profile_only = ""
    args.profile_all = False
    args.profile_jupyter_cells = True
    
    manager = TraceManager(args)
    
    # Test files to profile management
    test_file = Filename("test.py")
    manager.add_file_to_profile(test_file)
    files = manager.get_files_to_profile()
    assert test_file in files
    
    # Test profile_this_code with no files
    manager = TraceManager(args)  # Fresh instance
    assert manager.profile_this_code(Filename("any.py"), LineNumber(1)) == True


def test_process_manager_initialization():
    """Test that ProcessManager initializes properly."""
    # Create mock args
    args = ScaleneArguments()
    args.pid = None  # Parent process
    
    manager = ProcessManager(args)
    
    # Test child PID management
    manager.add_child_pid(12345)
    child_pids = manager.get_child_pids()
    assert 12345 in child_pids
    
    manager.remove_child_pid(12345)
    child_pids = manager.get_child_pids()
    assert 12345 not in child_pids


def test_profiler_lifecycle_initialization():
    """Test that ProfilerLifecycle initializes properly."""
    stats = ScaleneStatistics()
    args = ScaleneArguments()
    
    lifecycle = ProfilerLifecycle(stats, args)
    
    # Test initial state
    assert not lifecycle.is_initialized()
    assert not lifecycle.is_running()
    assert lifecycle.get_start_time() == 0
    
    # Test initialization
    lifecycle.set_initialized()
    assert lifecycle.is_initialized()


def test_integration_components_work_together():
    """Test that components can work together."""
    # Create all components
    stats = ScaleneStatistics()
    args = ScaleneArguments()
    args.profile_exclude = ""
    args.profile_only = ""
    args.profile_all = False
    args.profile_jupyter_cells = True
    args.pid = None
    
    core = ProfilerCore(stats)
    signal_handler = SignalHandler()
    trace_manager = TraceManager(args)
    process_manager = ProcessManager(args)
    lifecycle = ProfilerLifecycle(stats, args)
    
    # Test that they can be used together
    test_file = Filename("test.py")
    trace_manager.add_file_to_profile(test_file)
    
    # Test profile_this_code
    result = trace_manager.profile_this_code(test_file, LineNumber(1))
    assert isinstance(result, bool)
    
    # Test signal handler methods
    signals = signal_handler.get_signals()
    assert signals is not None
    
    # Test process manager
    process_manager.add_child_pid(999)
    assert 999 in process_manager.get_child_pids()
    
    print("All component integration tests passed!")


if __name__ == "__main__":
    test_profiler_core_initialization()
    test_signal_handler_initialization()
    test_trace_manager_initialization()
    test_process_manager_initialization()
    test_profiler_lifecycle_initialization()
    test_integration_components_work_together()
    print("All tests passed!")