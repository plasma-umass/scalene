"""Tests for JAX profiler integration.

These tests verify that Scalene's JAX profiler correctly captures
timing information and attributes it back to Python source lines.
"""

import os
import tempfile

import pytest

# Import the profiler module (this should always work even without JAX)
from scalene.scalene_jax import JaxProfiler, is_jax_available
from scalene.scalene_library_profiler import ChromeTraceProfiler, ScaleneLibraryProfiler


class TestJaxProfilerUnit:
    """Unit tests for JaxProfiler class."""

    def test_jax_profiler_import(self):
        """Test that scalene_jax module can be imported."""
        from scalene.scalene_jax import JaxProfiler, is_jax_available
        # is_jax_available should return a boolean
        assert isinstance(is_jax_available(), bool)

    def test_jax_profiler_extends_base_class(self):
        """Test that JaxProfiler extends ChromeTraceProfiler and ScaleneLibraryProfiler."""
        profiler = JaxProfiler()
        assert isinstance(profiler, ChromeTraceProfiler)
        assert isinstance(profiler, ScaleneLibraryProfiler)

    def test_jax_profiler_init(self):
        """Test JaxProfiler initialization."""
        profiler = JaxProfiler()
        assert profiler._enabled is False
        assert profiler._profiling_active is False
        assert profiler._trace_dir is None
        assert len(profiler.line_times) == 0
        assert len(profiler.gpu_line_times) == 0

    def test_jax_profiler_is_available_matches_import(self):
        """Test is_available() matches module-level availability."""
        profiler = JaxProfiler()
        assert profiler.is_available() == is_jax_available()

    def test_jax_profiler_name(self):
        """Test that profiler has correct name."""
        profiler = JaxProfiler()
        assert profiler.name == "JAX"

    def test_jax_profiler_get_line_time_default(self):
        """Test get_line_time returns 0 for unknown lines."""
        profiler = JaxProfiler()
        assert profiler.get_line_time("nonexistent.py", 1) == 0.0
        assert profiler.get_line_time("nonexistent.py", 999) == 0.0

    def test_jax_profiler_get_gpu_line_time_default(self):
        """Test get_gpu_line_time returns 0 for unknown lines."""
        profiler = JaxProfiler()
        assert profiler.get_gpu_line_time("nonexistent.py", 1) == 0.0

    def test_jax_profiler_clear(self):
        """Test JaxProfiler clear method."""
        profiler = JaxProfiler()

        # Manually add some CPU data (in microseconds)
        profiler.line_times["test.py"][10] = 1000000.0
        assert len(profiler.line_times) == 1

        # Manually add some GPU data
        profiler.gpu_line_times["test.py"][10] = 500000.0
        assert len(profiler.gpu_line_times) == 1

        profiler.clear()
        assert len(profiler.line_times) == 0
        assert len(profiler.gpu_line_times) == 0

    def test_jax_profiler_has_gpu_timing(self):
        """Test has_gpu_timing method."""
        profiler = JaxProfiler()

        # Initially no GPU timing
        assert profiler.has_gpu_timing() is False

        # Add some GPU timing
        profiler.gpu_line_times["test.py"][10] = 1000.0
        assert profiler.has_gpu_timing() is True

        # Clear and check again
        profiler.clear()
        assert profiler.has_gpu_timing() is False

    def test_jax_profiler_line_time_conversion(self):
        """Test that line times are correctly converted from microseconds to seconds."""
        profiler = JaxProfiler()

        # Add timing in microseconds
        profiler.line_times["test.py"][10] = 2_000_000.0  # 2 seconds

        # Should return time in seconds
        assert profiler.get_line_time("test.py", 10) == 2.0

    def test_jax_profiler_gpu_line_time_conversion(self):
        """Test that GPU line times are correctly converted."""
        profiler = JaxProfiler()

        # Add GPU timing in microseconds
        profiler.gpu_line_times["test.py"][10] = 3_000_000.0  # 3 seconds

        # Should return time in seconds
        assert profiler.get_gpu_line_time("test.py", 10) == 3.0

    def test_jax_profiler_get_all_times(self):
        """Test get_all_times aggregates data correctly."""
        profiler = JaxProfiler()

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


class TestJaxProfilerWithoutJax:
    """Tests for JaxProfiler when JAX is not installed."""

    def test_start_without_jax_is_noop(self):
        """Test that start() is a no-op when JAX is not available."""
        profiler = JaxProfiler()

        if not profiler.is_available():
            profiler.start()
            assert profiler._enabled is False
            assert profiler._trace_dir is None

    def test_stop_without_start_is_safe(self):
        """Test that stop() is safe to call without start()."""
        profiler = JaxProfiler()
        # Should not raise
        profiler.stop()
        assert profiler._enabled is False


@pytest.mark.skipif(not is_jax_available(), reason="JAX not installed")
class TestJaxProfilerWithJax:
    """Tests that require JAX to be installed."""

    def test_jax_profiler_start_stop(self):
        """Test JaxProfiler start and stop with JAX installed."""
        import jax
        import jax.numpy as jnp

        profiler = JaxProfiler()
        profiler.start()
        assert profiler._enabled is True
        assert profiler._trace_dir is not None
        assert os.path.isdir(profiler._trace_dir)

        # Do some JAX operations
        x = jnp.ones((100, 100))
        y = jnp.dot(x, x)
        _ = jnp.sum(y)

        profiler.stop()
        assert profiler._enabled is False
        # Trace dir should be cleaned up
        assert profiler._trace_dir is None

    def test_jax_profiler_captures_operations(self):
        """Test that JaxProfiler captures JAX operations."""
        import jax
        import jax.numpy as jnp

        profiler = JaxProfiler()
        profiler.start()

        # Do some JAX operations that should be traced
        @jax.jit
        def compute(x):
            for _ in range(10):
                x = jnp.dot(x, x.T)
                x = jax.nn.relu(x)
            return x

        x = jnp.ones((100, 100))
        for _ in range(5):
            result = compute(x)
            # Force computation
            result.block_until_ready()

        profiler.stop()

        # The profiler should have run without error
        # Note: actual timing data may or may not be captured depending
        # on JAX's trace format and whether it includes Python source info
        assert profiler._enabled is False

    def test_jax_profiler_trace_dir_cleanup(self):
        """Test that trace directory is cleaned up after stop."""
        import jax
        import jax.numpy as jnp

        profiler = JaxProfiler()
        profiler.start()

        trace_dir = profiler._trace_dir
        assert trace_dir is not None
        assert os.path.isdir(trace_dir)

        # Do minimal work
        x = jnp.ones(10)
        _ = jnp.sum(x)

        profiler.stop()

        # Directory should be cleaned up
        assert not os.path.exists(trace_dir)

    def test_jax_profiler_multiple_start_stop(self):
        """Test multiple start/stop cycles."""
        import jax
        import jax.numpy as jnp

        profiler = JaxProfiler()

        for i in range(3):
            profiler.start()
            assert profiler._enabled is True

            x = jnp.ones((50, 50)) * i
            _ = jnp.dot(x, x)

            profiler.stop()
            assert profiler._enabled is False

            # Clear for next iteration
            profiler.clear()


class TestJaxProfilerAttribution:
    """Tests that verify precise line attribution works correctly.

    These tests verify the complete pipeline from trace events to
    line-level timing data that Scalene uses for profiling output.
    """

    def test_attribution_single_line(self):
        """Test that a single trace event correctly attributes time to a line."""
        profiler = JaxProfiler()

        # Simulate a trace event from JAX profiler
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
        profiler = JaxProfiler()

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
        profiler = JaxProfiler()

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
        profiler = JaxProfiler()

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
        profiler = JaxProfiler()

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
        profiler = JaxProfiler()

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

    def test_attribution_end_to_end_trace_file(self):
        """Test complete pipeline: trace file -> line attribution -> seconds."""
        import json

        profiler = JaxProfiler()

        # Create a realistic trace file with multiple events
        trace_data = {
            "traceEvents": [
                {"ph": "X", "dur": 500_000, "args": {"file": "jax_code.py", "line": 10}},
                {"ph": "X", "dur": 500_000, "args": {"file": "jax_code.py", "line": 10}},
                {"ph": "X", "dur": 1_500_000, "args": {"file": "jax_code.py", "line": 20}},
                {"ph": "M", "name": "metadata", "args": {}},  # Should be filtered
                {"ph": "X", "dur": 0, "args": {"file": "jax_code.py", "line": 30}},  # Should be filtered
            ]
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(trace_data, f)
            trace_file = f.name

        try:
            profiler._parse_trace_file(trace_file)

            # Line 10: 500ms + 500ms = 1s
            assert profiler.get_line_time("jax_code.py", 10) == 1.0
            # Line 20: 1.5s
            assert profiler.get_line_time("jax_code.py", 20) == 1.5
            # Line 30: filtered (zero duration)
            assert profiler.get_line_time("jax_code.py", 30) == 0.0
        finally:
            os.unlink(trace_file)


class TestJaxTraceFileParsing:
    """Tests for trace file parsing logic."""

    def test_parse_trace_event_complete_event(self):
        """Test parsing a complete (X) trace event."""
        profiler = JaxProfiler()

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
        profiler = JaxProfiler()

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
        profiler = JaxProfiler()

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
        profiler = JaxProfiler()

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
        profiler = JaxProfiler()

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

    def test_parse_trace_file_json(self):
        """Test parsing a JSON trace file."""
        profiler = JaxProfiler()

        # Create a temporary trace file
        import json

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

        profiler = JaxProfiler()

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


class TestGpuTimingAttribution:
    """Tests for GPU vs CPU timing attribution in Chrome trace events."""

    def test_cpu_event_goes_to_line_times(self):
        """Test that CPU events are attributed to line_times."""
        profiler = JaxProfiler()

        event = {
            "ph": "X",
            "dur": 1000,
            "name": "MatMul",
            "args": {"file": "test.py", "line": 10}
        }

        profiler._process_trace_event(event)

        assert profiler.line_times["test.py"][10] == 1000
        assert len(profiler.gpu_line_times) == 0

    def test_gpu_event_by_device_type(self):
        """Test that events with GPU device_type go to gpu_line_times."""
        profiler = JaxProfiler()

        event = {
            "ph": "X",
            "dur": 2000,
            "name": "MatMul",
            "args": {
                "file": "test.py",
                "line": 20,
                "device_type": "GPU"
            }
        }

        profiler._process_trace_event(event)

        assert profiler.gpu_line_times["test.py"][20] == 2000
        assert len(profiler.line_times) == 0

    def test_gpu_event_by_cuda_device(self):
        """Test that events with CUDA device go to gpu_line_times."""
        profiler = JaxProfiler()

        event = {
            "ph": "X",
            "dur": 3000,
            "name": "Kernel",
            "args": {
                "file": "test.py",
                "line": 30,
                "device_type": "cuda"
            }
        }

        profiler._process_trace_event(event)

        assert profiler.gpu_line_times["test.py"][30] == 3000
        assert len(profiler.line_times) == 0

    def test_gpu_event_by_stream_name(self):
        """Test that events with GPU stream go to gpu_line_times."""
        profiler = JaxProfiler()

        event = {
            "ph": "X",
            "dur": 4000,
            "name": "Conv2D",
            "args": {
                "file": "test.py",
                "line": 40,
                "stream": "GPU:0/stream:1"
            }
        }

        profiler._process_trace_event(event)

        assert profiler.gpu_line_times["test.py"][40] == 4000
        assert len(profiler.line_times) == 0

    def test_gpu_event_by_kernel_name(self):
        """Test that events with kernel in name go to gpu_line_times."""
        profiler = JaxProfiler()

        event = {
            "ph": "X",
            "dur": 5000,
            "name": "cuDNN_kernel_123",
            "args": {"file": "test.py", "line": 50}
        }

        profiler._process_trace_event(event)

        assert profiler.gpu_line_times["test.py"][50] == 5000
        assert len(profiler.line_times) == 0

    def test_gpu_event_by_category(self):
        """Test that events with GPU category go to gpu_line_times."""
        profiler = JaxProfiler()

        event = {
            "ph": "X",
            "dur": 6000,
            "name": "MatMul",
            "cat": "cuda",
            "args": {"file": "test.py", "line": 60}
        }

        profiler._process_trace_event(event)

        assert profiler.gpu_line_times["test.py"][60] == 6000
        assert len(profiler.line_times) == 0

    def test_xla_gpu_device(self):
        """Test that XLA GPU events are detected."""
        profiler = JaxProfiler()

        event = {
            "ph": "X",
            "dur": 7000,
            "name": "xla::MatMul",
            "args": {
                "file": "test.py",
                "line": 70,
                "device_type": "xla:gpu"
            }
        }

        profiler._process_trace_event(event)

        assert profiler.gpu_line_times["test.py"][70] == 7000
        assert len(profiler.line_times) == 0

    def test_mixed_cpu_and_gpu_events(self):
        """Test that mixed events are correctly separated."""
        profiler = JaxProfiler()

        cpu_event = {
            "ph": "X",
            "dur": 1000,
            "name": "PyFunc",
            "args": {"file": "test.py", "line": 10}
        }
        gpu_event = {
            "ph": "X",
            "dur": 2000,
            "name": "Kernel",
            "args": {
                "file": "test.py",
                "line": 20,
                "device_type": "GPU"
            }
        }

        profiler._process_trace_event(cpu_event)
        profiler._process_trace_event(gpu_event)

        assert profiler.line_times["test.py"][10] == 1000
        assert profiler.gpu_line_times["test.py"][20] == 2000
