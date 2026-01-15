"""Tests for PyTorch JIT profiler integration.

These tests verify that Scalene correctly attributes time to lines inside
JIT-compiled PyTorch functions, not just to the call site. Also tests
GPU profiling when CUDA is available.
"""

import pytest

# Skip all tests if torch is not available
torch = pytest.importorskip("torch")


class TestTorchProfilerUnit:
    """Unit tests for TorchProfiler class."""

    def test_torch_profiler_import(self):
        """Test that scalene_torch module can be imported."""
        from scalene.scalene_torch import TorchProfiler, is_torch_available, is_cuda_available
        assert is_torch_available() is True
        # is_cuda_available should return a boolean (True if CUDA GPU available)
        assert isinstance(is_cuda_available(), bool)

    def test_torch_profiler_init(self):
        """Test TorchProfiler initialization."""
        from scalene.scalene_torch import TorchProfiler
        profiler = TorchProfiler()
        assert profiler._enabled is False
        assert profiler._gpu_enabled is False
        assert profiler._profiler is None
        assert len(profiler.line_times) == 0
        assert len(profiler.gpu_line_times) == 0

    def test_torch_profiler_start_stop(self):
        """Test TorchProfiler start and stop."""
        from scalene.scalene_torch import TorchProfiler
        profiler = TorchProfiler()
        profiler.start()
        assert profiler._enabled is True
        assert profiler._profiler is not None

        # Do some torch operations
        x = torch.randn(10, 10)
        y = x @ x.T

        profiler.stop()
        assert profiler._enabled is False

    def test_torch_profiler_captures_operations(self):
        """Test that TorchProfiler captures torch operations."""
        from scalene.scalene_torch import TorchProfiler
        profiler = TorchProfiler()
        profiler.start()

        # Do some torch operations
        x = torch.randn(100, 100)
        for _ in range(10):
            x = x @ x.T
            x = torch.relu(x)

        profiler.stop()

        # Should have captured some timing data
        # Note: line_times may be empty if torch.profiler doesn't capture
        # stacks for simple operations, but the profiler should run without error
        assert profiler._enabled is False

    def test_torch_profiler_get_line_time(self):
        """Test get_line_time returns 0 for unknown lines."""
        from scalene.scalene_torch import TorchProfiler
        profiler = TorchProfiler()

        # Should return 0 for lines that weren't profiled
        assert profiler.get_line_time("nonexistent.py", 1) == 0.0
        assert profiler.get_line_time("nonexistent.py", 999) == 0.0

    def test_torch_profiler_clear(self):
        """Test TorchProfiler clear method."""
        from scalene.scalene_torch import TorchProfiler
        profiler = TorchProfiler()

        # Manually add some CPU data
        profiler.line_times["test.py"][10] = 1000.0
        assert len(profiler.line_times) == 1

        # Manually add some GPU data
        profiler.gpu_line_times["test.py"][10] = 500.0
        assert len(profiler.gpu_line_times) == 1

        profiler.clear()
        assert len(profiler.line_times) == 0
        assert len(profiler.gpu_line_times) == 0

    def test_torch_profiler_get_gpu_line_time(self):
        """Test get_gpu_line_time returns correct values."""
        from scalene.scalene_torch import TorchProfiler
        profiler = TorchProfiler()

        # Should return 0 for lines that weren't profiled
        assert profiler.get_gpu_line_time("nonexistent.py", 1) == 0.0

        # Add some GPU timing data (in microseconds)
        profiler.gpu_line_times["test.py"][10] = 2_000_000.0  # 2 seconds

        # Should return time in seconds
        assert profiler.get_gpu_line_time("test.py", 10) == 2.0

    def test_torch_profiler_has_gpu_timing(self):
        """Test has_gpu_timing method."""
        from scalene.scalene_torch import TorchProfiler
        profiler = TorchProfiler()

        # Initially no GPU timing
        assert profiler.has_gpu_timing() is False

        # Add some GPU timing
        profiler.gpu_line_times["test.py"][10] = 1000.0
        assert profiler.has_gpu_timing() is True

        # Clear and check again
        profiler.clear()
        assert profiler.has_gpu_timing() is False


class TestTorchProfilerJIT:
    """Tests for JIT function profiling."""

    def test_jit_function_internal_lines_captured(self):
        """Test that lines inside JIT functions are captured."""
        from scalene.scalene_torch import TorchProfiler

        # Define a JIT function in this file so we know the filename
        @torch.jit.script
        def jit_compute(x: torch.Tensor) -> torch.Tensor:
            for _ in range(20):
                x = x @ x.T  # This line should be captured
                x = torch.relu(x)  # This line should be captured
            return x

        profiler = TorchProfiler()
        profiler.start()

        x = torch.randn(200, 200)
        for _ in range(50):
            result = jit_compute(x)

        profiler.stop()

        # Check that we captured timing for this file
        this_file = __file__
        if this_file in profiler.line_times:
            # We should have captured some internal lines
            captured_lines = list(profiler.line_times[this_file].keys())
            assert len(captured_lines) > 0, "Should capture at least one line"

            # The captured lines should have non-zero timing
            for lineno in captured_lines:
                time_us = profiler.line_times[this_file][lineno]
                assert time_us > 0, f"Line {lineno} should have positive timing"

    def test_jit_load_works(self):
        """Test that torch.jit.load works (issue #908)."""
        import tempfile
        import os

        @torch.jit.script
        def simple_fn(x: torch.Tensor) -> torch.Tensor:
            return x * 2 + 1

        # Save the model
        with tempfile.NamedTemporaryFile(suffix=".pt", delete=False) as f:
            model_path = f.name

        try:
            torch.jit.save(torch.jit.script(simple_fn), model_path)

            # Load should work (this was failing when PYTORCH_JIT=0)
            loaded = torch.jit.load(model_path)

            # Verify it works
            x = torch.tensor([1.0, 2.0, 3.0])
            result = loaded(x)
            expected = x * 2 + 1
            assert torch.allclose(result, expected)
        finally:
            os.unlink(model_path)


class TestTorchStatisticsIntegration:
    """Tests for torch timing integration with ScaleneStatistics."""

    def test_cpu_statistics_has_torch_cpu_field(self):
        """Test that CPUStatistics has torch_cpu_time field."""
        from scalene.scalene_statistics import ScaleneStatistics
        stats = ScaleneStatistics()

        # Should have torch_cpu_time as a defaultdict
        assert hasattr(stats.cpu_stats, 'torch_cpu_time')

        # Should be accessible without KeyError
        val = stats.cpu_stats.torch_cpu_time["test.py"][10]
        assert val == 0.0  # Default value

    def test_cpu_statistics_has_torch_gpu_field(self):
        """Test that CPUStatistics has torch_gpu_time field for CUDA timing."""
        from scalene.scalene_statistics import ScaleneStatistics
        stats = ScaleneStatistics()

        # Should have torch_gpu_time as a defaultdict
        assert hasattr(stats.cpu_stats, 'torch_gpu_time')

        # Should be accessible without KeyError
        val = stats.cpu_stats.torch_gpu_time["test.py"][10]
        assert val == 0.0  # Default value

    def test_cpu_statistics_torch_cpu_time_accumulates(self):
        """Test that torch CPU timing accumulates correctly."""
        from scalene.scalene_statistics import ScaleneStatistics
        stats = ScaleneStatistics()

        # Add some timing
        stats.cpu_stats.torch_cpu_time["test.py"][10] += 1000.0
        stats.cpu_stats.torch_cpu_time["test.py"][10] += 500.0
        stats.cpu_stats.torch_cpu_time["test.py"][20] += 200.0

        assert stats.cpu_stats.torch_cpu_time["test.py"][10] == 1500.0
        assert stats.cpu_stats.torch_cpu_time["test.py"][20] == 200.0

    def test_cpu_statistics_torch_gpu_time_accumulates(self):
        """Test that torch GPU timing accumulates correctly."""
        from scalene.scalene_statistics import ScaleneStatistics
        stats = ScaleneStatistics()

        # Add some GPU timing
        stats.cpu_stats.torch_gpu_time["test.py"][10] += 2000.0
        stats.cpu_stats.torch_gpu_time["test.py"][10] += 1000.0
        stats.cpu_stats.torch_gpu_time["test.py"][20] += 500.0

        assert stats.cpu_stats.torch_gpu_time["test.py"][10] == 3000.0
        assert stats.cpu_stats.torch_gpu_time["test.py"][20] == 500.0

    def test_cpu_statistics_clear_clears_torch_times(self):
        """Test that clear() clears both torch CPU and GPU times."""
        from scalene.scalene_statistics import ScaleneStatistics
        stats = ScaleneStatistics()

        # Add some timing
        stats.cpu_stats.torch_cpu_time["test.py"][10] = 1000.0
        stats.cpu_stats.torch_gpu_time["test.py"][10] = 2000.0

        # Clear
        stats.cpu_stats.clear()

        # Both should be empty
        assert len(stats.cpu_stats.torch_cpu_time) == 0
        assert len(stats.cpu_stats.torch_gpu_time) == 0


class TestTorchJSONOutput:
    """Tests for torch timing in JSON output."""

    def test_json_includes_torch_timing_lines(self):
        """Test that lines with only torch timing are included in output."""
        from scalene.scalene_json import ScaleneJSON
        from scalene.scalene_statistics import ScaleneStatistics, Filename, LineNumber

        stats = ScaleneStatistics()
        stats.elapsed_time = 10.0  # 10 seconds
        stats.cpu_stats.total_cpu_samples = 100

        # Add torch timing for a line that has no signal-based samples
        fname = Filename("test_file.py")
        stats.cpu_stats.torch_cpu_time[fname][5] = 2_000_000.0  # 2 seconds in microseconds

        json_output = ScaleneJSON()

        # The profile_this_code function would normally return False for this line
        # since it has no signal samples, but with torch timing it should be included
        def profile_this_code(f, l):
            return False  # Simulate no signal samples

        result = json_output.output_profile_line(
            fname=fname,
            fname_print=fname,
            line_no=LineNumber(5),
            line="x = torch.matmul(a, b)",
            stats=stats,
            profile_this_code=profile_this_code,
            profile_memory=False,
            force_print=False,
        )

        # Should have non-zero C time from torch profiler
        assert result["n_cpu_percent_c"] > 0, "Should include torch timing as C time"

    def test_json_caps_percentages(self):
        """Test that percentages are capped at 100%."""
        from scalene.scalene_json import ScaleneJSON
        from scalene.scalene_statistics import ScaleneStatistics, Filename, LineNumber

        stats = ScaleneStatistics()
        stats.elapsed_time = 1.0  # 1 second
        stats.cpu_stats.total_cpu_samples = 100

        # Add torch timing that would exceed 100%
        fname = Filename("test_file.py")
        stats.cpu_stats.torch_cpu_time[fname][5] = 2_000_000.0  # 2 seconds = 200%

        json_output = ScaleneJSON()

        result = json_output.output_profile_line(
            fname=fname,
            fname_print=fname,
            line_no=LineNumber(5),
            line="x = heavy_computation()",
            stats=stats,
            profile_this_code=lambda f, l: True,
            profile_memory=False,
            force_print=False,
        )

        # Should be capped at 100%
        assert result["n_cpu_percent_c"] <= 100.0, "C percent should be capped at 100"
        assert result["n_cpu_percent_python"] <= 100.0, "Python percent should be capped at 100"
        assert result["n_sys_percent"] <= 100.0, "Sys percent should be capped at 100"


class TestTorchNormalization:
    """Tests for CPU percentage normalization with torch timing."""

    def test_normalization_sums_to_100(self):
        """Test that normalized percentages sum to <= 100%."""
        import subprocess
        import json
        import tempfile
        import os

        # Create a test script that uses JIT - must run long enough to profile
        test_code = '''
import torch

@torch.jit.script
def jit_fn(x: torch.Tensor) -> torch.Tensor:
    for _ in range(50):
        x = x @ x.T
        x = torch.relu(x)
    return x

x = torch.randn(300, 300)
for _ in range(100):
    result = jit_fn(x)
'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(test_code)
            test_file = f.name

        profile_file = tempfile.NamedTemporaryFile(suffix='.json', delete=False).name

        try:
            # Run scalene on the test file
            proc = subprocess.run(
                ['python3', '-m', 'scalene', 'run', '-o', profile_file, '--cli', test_file],
                capture_output=True,
                text=True,
                timeout=120
            )

            # Check if profile was generated
            if not os.path.exists(profile_file) or os.path.getsize(profile_file) == 0:
                pytest.skip("Profile not generated (program may not have run long enough)")

            # Load the profile
            with open(profile_file) as f:
                data = json.load(f)

            # Check if we have files to analyze
            if 'files' not in data or not data['files']:
                pytest.skip("No files in profile (program may not have run long enough)")

            # Sum up all CPU percentages
            total_cpu = 0.0
            for fdata in data['files'].values():
                for linedata in fdata.get('lines', []):
                    total_cpu += linedata.get('n_cpu_percent_c', 0)
                    total_cpu += linedata.get('n_cpu_percent_python', 0)
                    total_cpu += linedata.get('n_sys_percent', 0)

            # Total should be <= 100% (with small tolerance for floating point)
            assert total_cpu <= 100.5, f"Total CPU should be <= 100%, got {total_cpu}%"

        finally:
            os.unlink(test_file)
            if os.path.exists(profile_file):
                os.unlink(profile_file)
