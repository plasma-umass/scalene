"""Tests for TensorFlow profiler integration.

These tests verify that Scalene's TensorFlow profiler correctly captures
timing information and attributes it back to Python source lines.
"""

import os
import tempfile

import pytest

# Note: JaxProfiler is imported here to serve as an additional concrete
# profiler implementation in the library profiler registry tests (e.g.,
# test_registry_aggregates_line_times). This allows verification that
# the registry correctly handles multiple profiler types, not just TensorFlow.
from scalene.scalene_jax import JaxProfiler
from scalene.scalene_library_profiler import ChromeTraceProfiler, ScaleneLibraryProfiler

# Import the profiler module (this should always work even without TensorFlow)
from scalene.scalene_tensorflow import TensorFlowProfiler, is_tensorflow_available


class TestTensorFlowProfilerUnit:
    """Unit tests for TensorFlowProfiler class."""

    def test_tensorflow_profiler_import(self):
        """Test that scalene_tensorflow module can be imported."""
        from scalene.scalene_tensorflow import (
            TensorFlowProfiler,
            is_tensorflow_available,
        )
        # is_tensorflow_available should return a boolean
        assert isinstance(is_tensorflow_available(), bool)

    def test_tensorflow_profiler_extends_base_class(self):
        """Test that TensorFlowProfiler extends ChromeTraceProfiler and ScaleneLibraryProfiler."""
        profiler = TensorFlowProfiler()
        assert isinstance(profiler, ChromeTraceProfiler)
        assert isinstance(profiler, ScaleneLibraryProfiler)

    def test_tensorflow_profiler_init(self):
        """Test TensorFlowProfiler initialization."""
        profiler = TensorFlowProfiler()
        assert profiler._enabled is False
        assert profiler._profiling_active is False
        assert profiler._trace_dir is None
        assert len(profiler.line_times) == 0
        assert len(profiler.gpu_line_times) == 0

    def test_tensorflow_profiler_is_available_matches_import(self):
        """Test is_available() matches module-level availability."""
        profiler = TensorFlowProfiler()
        assert profiler.is_available() == is_tensorflow_available()

    def test_tensorflow_profiler_name(self):
        """Test that profiler has correct name."""
        profiler = TensorFlowProfiler()
        assert profiler.name == "TensorFlow"

    def test_tensorflow_profiler_get_line_time_default(self):
        """Test get_line_time returns 0 for unknown lines."""
        profiler = TensorFlowProfiler()
        assert profiler.get_line_time("nonexistent.py", 1) == 0.0
        assert profiler.get_line_time("nonexistent.py", 999) == 0.0

    def test_tensorflow_profiler_get_gpu_line_time_default(self):
        """Test get_gpu_line_time returns 0 for unknown lines."""
        profiler = TensorFlowProfiler()
        assert profiler.get_gpu_line_time("nonexistent.py", 1) == 0.0

    def test_tensorflow_profiler_clear(self):
        """Test TensorFlowProfiler clear method."""
        profiler = TensorFlowProfiler()

        # Manually add some CPU data (in microseconds)
        profiler.line_times["test.py"][10] = 1000000.0
        assert len(profiler.line_times) == 1

        # Manually add some GPU data
        profiler.gpu_line_times["test.py"][10] = 500000.0
        assert len(profiler.gpu_line_times) == 1

        profiler.clear()
        assert len(profiler.line_times) == 0
        assert len(profiler.gpu_line_times) == 0

    def test_tensorflow_profiler_has_gpu_timing(self):
        """Test has_gpu_timing method."""
        profiler = TensorFlowProfiler()

        # Initially no GPU timing
        assert profiler.has_gpu_timing() is False

        # Add some GPU timing
        profiler.gpu_line_times["test.py"][10] = 1000.0
        assert profiler.has_gpu_timing() is True

        # Clear and check again
        profiler.clear()
        assert profiler.has_gpu_timing() is False

    def test_tensorflow_profiler_line_time_conversion(self):
        """Test that line times are correctly converted from microseconds to seconds."""
        profiler = TensorFlowProfiler()

        # Add timing in microseconds
        profiler.line_times["test.py"][10] = 2_000_000.0  # 2 seconds

        # Should return time in seconds
        assert profiler.get_line_time("test.py", 10) == 2.0

    def test_tensorflow_profiler_gpu_line_time_conversion(self):
        """Test that GPU line times are correctly converted."""
        profiler = TensorFlowProfiler()

        # Add GPU timing in microseconds
        profiler.gpu_line_times["test.py"][10] = 3_000_000.0  # 3 seconds

        # Should return time in seconds
        assert profiler.get_gpu_line_time("test.py", 10) == 3.0

    def test_tensorflow_profiler_get_all_times(self):
        """Test get_all_times aggregates data correctly."""
        profiler = TensorFlowProfiler()

        # Add some timing data
        profiler.line_times["test.py"][10] = 1_000_000.0  # 1 second
        profiler.line_times["test.py"][20] = 2_000_000.0  # 2 seconds
        profiler.gpu_line_times["test.py"][10] = 500_000.0  # 0.5 seconds

        times = profiler.get_all_times()

        # Should have entries for both lines
        assert len(times) == 2

        # Check the data
        times_dict = {(f, l): (c, g) for f, l, c, g in times}
        assert ("test.py", 10) in times_dict
        assert ("test.py", 20) in times_dict

        # Check values (converted to seconds)
        cpu_10, gpu_10 = times_dict[("test.py", 10)]
        assert cpu_10 == 1.0
        assert gpu_10 == 0.5

        cpu_20, gpu_20 = times_dict[("test.py", 20)]
        assert cpu_20 == 2.0
        assert gpu_20 == 0.0


class TestTensorFlowProfilerWithoutTF:
    """Tests for TensorFlowProfiler when TensorFlow is not installed."""

    def test_start_without_tf_is_noop(self):
        """Test that start() is a no-op when TensorFlow is not available."""
        profiler = TensorFlowProfiler()

        if not profiler.is_available():
            profiler.start()
            assert profiler._enabled is False
            assert profiler._trace_dir is None

    def test_stop_without_start_is_safe(self):
        """Test that stop() is safe to call without start()."""
        profiler = TensorFlowProfiler()
        # Should not raise
        profiler.stop()
        assert profiler._enabled is False


@pytest.mark.skipif(not is_tensorflow_available(), reason="TensorFlow not installed")
class TestTensorFlowProfilerWithTF:
    """Tests that require TensorFlow to be installed."""

    def test_tensorflow_profiler_start_stop(self):
        """Test TensorFlowProfiler start and stop with TensorFlow installed."""
        import tensorflow as tf

        profiler = TensorFlowProfiler()
        profiler.start()
        assert profiler._enabled is True
        assert profiler._trace_dir is not None
        assert os.path.isdir(profiler._trace_dir)

        # Do some TensorFlow operations
        x = tf.ones((100, 100))
        y = tf.matmul(x, x)
        _ = tf.reduce_sum(y)

        profiler.stop()
        assert profiler._enabled is False
        # Trace dir should be cleaned up
        assert profiler._trace_dir is None

    def test_tensorflow_profiler_captures_operations(self):
        """Test that TensorFlowProfiler captures TensorFlow operations."""
        import tensorflow as tf

        profiler = TensorFlowProfiler()
        profiler.start()

        # Do some TensorFlow operations that should be traced
        @tf.function
        def compute(x):
            for _ in range(10):
                x = tf.matmul(x, tf.transpose(x))
                x = tf.nn.relu(x)
            return x

        x = tf.ones((100, 100))
        for _ in range(5):
            result = compute(x)
            # Force computation
            _ = result.numpy()

        profiler.stop()

        # The profiler should have run without error
        # Note: actual timing data may or may not be captured depending
        # on TensorFlow's trace format and whether it includes Python source info
        assert profiler._enabled is False

    def test_tensorflow_profiler_trace_dir_cleanup(self):
        """Test that trace directory is cleaned up after stop."""
        import tensorflow as tf

        profiler = TensorFlowProfiler()
        profiler.start()

        trace_dir = profiler._trace_dir
        assert trace_dir is not None
        assert os.path.isdir(trace_dir)

        # Do minimal work
        x = tf.ones(10)
        _ = tf.reduce_sum(x)

        profiler.stop()

        # Directory should be cleaned up
        assert not os.path.exists(trace_dir)

    def test_tensorflow_profiler_multiple_start_stop(self):
        """Test multiple start/stop cycles."""
        import tensorflow as tf

        profiler = TensorFlowProfiler()

        for i in range(3):
            profiler.start()
            assert profiler._enabled is True

            x = tf.ones((50, 50)) * float(i)
            _ = tf.matmul(x, x)

            profiler.stop()
            assert profiler._enabled is False

            # Clear for next iteration
            profiler.clear()


class TestTensorFlowProfilerAttribution:
    """Tests that verify precise line attribution works correctly.

    These tests verify the complete pipeline from trace events to
    line-level timing data that Scalene uses for profiling output.
    """

    def test_attribution_single_line(self):
        """Test that a single trace event correctly attributes time to a line."""
        profiler = TensorFlowProfiler()

        # Simulate a trace event from TensorFlow profiler
        event = {
            "ph": "X",  # Complete event
            "dur": 5_000_000,  # 5 seconds in microseconds
            "args": {
                "file": "/path/to/model.py",
                "line": 42
            }
        }

        profiler._process_trace_event(event)

        # Verify the time is attributed to the correct file:line
        assert profiler.line_times["/path/to/model.py"][42] == 5_000_000
        # Verify get_line_time converts to seconds
        assert profiler.get_line_time("/path/to/model.py", 42) == 5.0

    def test_attribution_multiple_lines_same_file(self):
        """Test attribution across multiple lines in the same file."""
        profiler = TensorFlowProfiler()

        events = [
            {"ph": "X", "dur": 1_000_000, "args": {"file": "train.py", "line": 10}},
            {"ph": "X", "dur": 2_000_000, "args": {"file": "train.py", "line": 20}},
            {"ph": "X", "dur": 3_000_000, "args": {"file": "train.py", "line": 30}},
        ]

        for event in events:
            profiler._process_trace_event(event)

        # Verify each line has correct timing
        assert profiler.get_line_time("train.py", 10) == 1.0
        assert profiler.get_line_time("train.py", 20) == 2.0
        assert profiler.get_line_time("train.py", 30) == 3.0

    def test_attribution_accumulates_repeated_calls(self):
        """Test that repeated calls to the same line accumulate time."""
        profiler = TensorFlowProfiler()

        # Simulate a loop calling the same line 100 times
        for _ in range(100):
            event = {
                "ph": "X",
                "dur": 10_000,  # 10ms each call
                "args": {"file": "loop.py", "line": 5}
            }
            profiler._process_trace_event(event)

        # Total should be 100 * 10ms = 1 second
        assert profiler.get_line_time("loop.py", 5) == 1.0

    def test_attribution_multiple_files(self):
        """Test attribution across multiple files."""
        profiler = TensorFlowProfiler()

        events = [
            {"ph": "X", "dur": 1_000_000, "args": {"file": "model.py", "line": 10}},
            {"ph": "X", "dur": 2_000_000, "args": {"file": "data.py", "line": 20}},
            {"ph": "X", "dur": 3_000_000, "args": {"file": "utils.py", "line": 30}},
        ]

        for event in events:
            profiler._process_trace_event(event)

        # Verify each file:line has correct timing
        assert profiler.get_line_time("model.py", 10) == 1.0
        assert profiler.get_line_time("data.py", 20) == 2.0
        assert profiler.get_line_time("utils.py", 30) == 3.0

    def test_attribution_get_all_times_returns_all_data(self):
        """Test that get_all_times returns all attributed timing data."""
        profiler = TensorFlowProfiler()

        events = [
            {"ph": "X", "dur": 1_000_000, "args": {"file": "a.py", "line": 1}},
            {"ph": "X", "dur": 2_000_000, "args": {"file": "a.py", "line": 2}},
            {"ph": "X", "dur": 3_000_000, "args": {"file": "b.py", "line": 1}},
        ]

        for event in events:
            profiler._process_trace_event(event)

        all_times = profiler.get_all_times()

        # Should have 3 entries
        assert len(all_times) == 3

        # Convert to dict for easier checking
        times_dict = {(f, l): (cpu, gpu) for f, l, cpu, gpu in all_times}

        assert times_dict[("a.py", 1)] == (1.0, 0.0)
        assert times_dict[("a.py", 2)] == (2.0, 0.0)
        assert times_dict[("b.py", 1)] == (3.0, 0.0)

    def test_attribution_filters_invalid_events(self):
        """Test that invalid events don't pollute attribution data."""
        profiler = TensorFlowProfiler()

        # Valid event
        profiler._process_trace_event({
            "ph": "X", "dur": 1_000_000,
            "args": {"file": "valid.py", "line": 10}
        })

        # Invalid: no source info
        profiler._process_trace_event({
            "ph": "X", "dur": 1_000_000, "args": {}
        })

        # Invalid: zero duration
        profiler._process_trace_event({
            "ph": "X", "dur": 0,
            "args": {"file": "zero.py", "line": 20}
        })

        # Invalid: wrong phase (metadata event)
        profiler._process_trace_event({
            "ph": "M", "dur": 1_000_000,
            "args": {"file": "meta.py", "line": 30}
        })

        # Only the valid event should be recorded
        assert len(profiler.line_times) == 1
        assert profiler.get_line_time("valid.py", 10) == 1.0
        assert profiler.get_line_time("zero.py", 20) == 0.0
        assert profiler.get_line_time("meta.py", 30) == 0.0

    def test_attribution_python_stack_extraction(self):
        """Test that Python stack info is correctly extracted for attribution."""
        profiler = TensorFlowProfiler()

        # TensorFlow sometimes includes Python stack in trace events
        event = {
            "ph": "X",
            "dur": 2_000_000,
            "args": {
                "python_stack": [
                    {"file": "innermost.py", "line": 100},
                    {"file": "caller.py", "line": 50},
                    {"file": "main.py", "line": 10}
                ]
            }
        }

        profiler._process_trace_event(event)

        # Should use first frame from python_stack
        assert profiler.get_line_time("innermost.py", 100) == 2.0
        # Other frames should not be attributed
        assert profiler.get_line_time("caller.py", 50) == 0.0
        assert profiler.get_line_time("main.py", 10) == 0.0

    def test_attribution_end_to_end_trace_file(self):
        """Test complete pipeline: trace file -> line attribution -> seconds."""
        import json

        profiler = TensorFlowProfiler()

        # Create a realistic trace file with multiple events
        trace_data = {
            "traceEvents": [
                {"ph": "X", "dur": 500_000, "args": {"file": "tf_code.py", "line": 10}},
                {"ph": "X", "dur": 500_000, "args": {"file": "tf_code.py", "line": 10}},
                {"ph": "X", "dur": 1_500_000, "args": {"file": "tf_code.py", "line": 20}},
                {"ph": "M", "name": "metadata", "args": {}},  # Should be filtered
                {"ph": "X", "dur": 0, "args": {"file": "tf_code.py", "line": 30}},  # Should be filtered
                {"ph": "X", "dur": 750_000, "args": {"python_stack": [{"file": "stack.py", "line": 5}]}},
            ]
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(trace_data, f)
            trace_file = f.name

        try:
            profiler._parse_trace_file(trace_file)

            # Line 10: 500ms + 500ms = 1s
            assert profiler.get_line_time("tf_code.py", 10) == 1.0
            # Line 20: 1.5s
            assert profiler.get_line_time("tf_code.py", 20) == 1.5
            # Line 30: filtered (zero duration)
            assert profiler.get_line_time("tf_code.py", 30) == 0.0
            # Python stack extraction: 750ms = 0.75s
            assert profiler.get_line_time("stack.py", 5) == 0.75
        finally:
            os.unlink(trace_file)


class TestTensorFlowTraceFileParsing:
    """Tests for trace file parsing logic."""

    def test_parse_trace_event_complete_event(self):
        """Test parsing a complete (X) trace event."""
        profiler = TensorFlowProfiler()

        event = {
            "ph": "X",
            "dur": 1000000,  # 1 second in microseconds
            "args": {
                "file": "test_script.py",
                "line": 42
            }
        }

        profiler._process_trace_event(event)

        # Should have captured the timing
        assert profiler.line_times["test_script.py"][42] == 1000000

    def test_parse_trace_event_no_source_info(self):
        """Test parsing event without source info is skipped."""
        profiler = TensorFlowProfiler()

        event = {
            "ph": "X",
            "dur": 1000000,
            "args": {}  # No file/line info
        }

        profiler._process_trace_event(event)

        # Should not have added any timing
        assert len(profiler.line_times) == 0

    def test_parse_trace_event_zero_duration(self):
        """Test that zero-duration events are skipped."""
        profiler = TensorFlowProfiler()

        event = {
            "ph": "X",
            "dur": 0,
            "args": {
                "file": "test.py",
                "line": 10
            }
        }

        profiler._process_trace_event(event)

        # Should not have added any timing
        assert len(profiler.line_times) == 0

    def test_parse_trace_event_wrong_phase(self):
        """Test that non-duration events are skipped."""
        profiler = TensorFlowProfiler()

        event = {
            "ph": "M",  # Metadata event, not duration
            "dur": 1000,
            "args": {
                "file": "test.py",
                "line": 10
            }
        }

        profiler._process_trace_event(event)

        # Should not have added any timing
        assert len(profiler.line_times) == 0

    def test_parse_trace_event_accumulates(self):
        """Test that multiple events for same line accumulate."""
        profiler = TensorFlowProfiler()

        event1 = {
            "ph": "X",
            "dur": 1000,
            "args": {"file": "test.py", "line": 10}
        }
        event2 = {
            "ph": "X",
            "dur": 2000,
            "args": {"file": "test.py", "line": 10}
        }

        profiler._process_trace_event(event1)
        profiler._process_trace_event(event2)

        # Should have accumulated
        assert profiler.line_times["test.py"][10] == 3000

    def test_parse_trace_event_with_python_stack(self):
        """Test parsing event with Python stack information."""
        profiler = TensorFlowProfiler()

        # TensorFlow sometimes includes Python stack in trace events
        event = {
            "ph": "X",
            "dur": 5000,
            "args": {
                "python_stack": [
                    {"file": "model.py", "line": 25},
                    {"file": "train.py", "line": 100}
                ]
            }
        }

        profiler._process_trace_event(event)

        # Should use first frame from python_stack
        assert profiler.line_times["model.py"][25] == 5000

    def test_parse_trace_file_json(self):
        """Test parsing a JSON trace file."""
        import json

        profiler = TensorFlowProfiler()

        trace_data = {
            "traceEvents": [
                {"ph": "X", "dur": 1000, "args": {"file": "script.py", "line": 5}},
                {"ph": "X", "dur": 2000, "args": {"file": "script.py", "line": 10}},
            ]
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(trace_data, f)
            trace_file = f.name

        try:
            profiler._parse_trace_file(trace_file)

            assert profiler.line_times["script.py"][5] == 1000
            assert profiler.line_times["script.py"][10] == 2000
        finally:
            os.unlink(trace_file)

    def test_parse_trace_file_gzipped(self):
        """Test parsing a gzipped trace file."""
        import gzip
        import json

        profiler = TensorFlowProfiler()

        trace_data = [
            {"ph": "X", "dur": 5000, "args": {"file": "gzip_test.py", "line": 1}}
        ]

        with tempfile.NamedTemporaryFile(suffix='.json.gz', delete=False) as f:
            trace_file = f.name

        with gzip.open(trace_file, 'wt') as f:
            json.dump(trace_data, f)

        try:
            profiler._parse_trace_file(trace_file)

            assert profiler.line_times["gzip_test.py"][1] == 5000
        finally:
            os.unlink(trace_file)


class TestLibraryProfilerRegistry:
    """Tests for the library profiler registry with TensorFlow and JAX."""

    def test_registry_initialization(self):
        """Test that registry can be initialized."""
        from scalene.scalene_library_registry import LibraryProfilerRegistry

        registry = LibraryProfilerRegistry()
        registry.initialize()

        # Should have at least registered profilers for available libraries
        profilers = registry.get_profilers()
        # The number depends on which libraries are installed
        assert isinstance(profilers, list)

    def test_registry_aggregates_line_times(self):
        """Test that registry correctly aggregates line times from all profilers."""
        from scalene.scalene_library_registry import LibraryProfilerRegistry

        registry = LibraryProfilerRegistry()

        # Create mock profilers with data
        profiler1 = TensorFlowProfiler()
        profiler1.line_times["test.py"][10] = 1_000_000.0  # 1 second

        profiler2 = JaxProfiler()
        profiler2.line_times["test.py"][10] = 500_000.0  # 0.5 seconds

        # Manually register them
        registry._profilers = [profiler1, profiler2]

        # Aggregate should sum the times
        total = registry.get_line_time("test.py", 10)
        assert total == 1.5  # 1 + 0.5 seconds

    def test_registry_aggregates_gpu_times(self):
        """Test that registry correctly aggregates GPU times from all profilers."""
        from scalene.scalene_library_registry import LibraryProfilerRegistry

        registry = LibraryProfilerRegistry()

        # Create mock profilers with GPU data
        profiler1 = TensorFlowProfiler()
        profiler1.gpu_line_times["test.py"][10] = 2_000_000.0  # 2 seconds

        profiler2 = JaxProfiler()
        profiler2.gpu_line_times["test.py"][10] = 1_000_000.0  # 1 second

        # Manually register them
        registry._profilers = [profiler1, profiler2]

        # Aggregate should sum the times
        total = registry.get_gpu_line_time("test.py", 10)
        assert total == 3.0  # 2 + 1 seconds

    def test_registry_start_stop_all(self):
        """Test that registry can start and stop all profilers."""
        from scalene.scalene_library_registry import LibraryProfilerRegistry

        registry = LibraryProfilerRegistry()
        registry.initialize()

        # Start all
        registry.start_all()

        # Stop all (should not raise)
        registry.stop_all()

        # Clear all
        registry.clear_all()

    def test_registry_empty_line_times(self):
        """Test that registry returns 0 for empty profilers."""
        from scalene.scalene_library_registry import LibraryProfilerRegistry

        registry = LibraryProfilerRegistry()
        # Don't initialize, so no profilers registered

        assert registry.get_line_time("test.py", 10) == 0.0
        assert registry.get_gpu_line_time("test.py", 10) == 0.0
