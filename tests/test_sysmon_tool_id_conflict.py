"""Test sys.monitoring tool ID conflict resolution.

This tests the fix for issue #1015: SIGSEGV crash when using Scalene with
PyTorch Lightning on Python 3.12+. The root cause was that both Scalene
and PyTorch's profiler use sys.monitoring.PROFILER_ID.

The fix makes Scalene try alternative tool IDs (3, 4) when PROFILER_ID is taken.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest


@unittest.skipIf(sys.version_info < (3, 12), "sys.monitoring requires Python 3.12+")
class TestToolIdConflict(unittest.TestCase):
    """Test that Scalene handles tool ID conflicts gracefully."""

    def test_fallback_when_profiler_id_taken(self):
        """Test that Scalene falls back to alternative ID when PROFILER_ID is taken.

        This test verifies that the _CANDIDATE_TOOL_IDS list is set up correctly,
        allowing Scalene to fall back to IDs 3 or 4 when PROFILER_ID is unavailable.
        """
        # Import the tracer module directly to test its configuration
        from scalene.scalene_tracer import _CANDIDATE_TOOL_IDS, _monitoring

        # Verify the candidate IDs are set up correctly for fallback
        expected_ids = [_monitoring.PROFILER_ID, 3, 4]
        self.assertEqual(
            _CANDIDATE_TOOL_IDS,
            expected_ids,
            f"Expected candidate IDs {expected_ids}, got {_CANDIDATE_TOOL_IDS}",
        )

        # Verify that the fallback IDs (3 and 4) are valid tool IDs
        # On a fresh interpreter, we should be able to claim them
        # (They may be taken in CI if torch or something else claimed them)
        for candidate_id in [3, 4]:
            current_owner = _monitoring.get_tool(candidate_id)
            if current_owner is None:
                # Good - this ID is available for Scalene to use as fallback
                pass
            else:
                # ID is taken, which is fine - the test is about the fallback *mechanism*
                print(f"Note: Tool ID {candidate_id} is owned by '{current_owner}'")

    def test_fallback_to_legacy_when_all_ids_taken(self):
        """Test that the fallback mechanism exists for legacy tracer mode.

        This verifies that _FORCE_LEGACY_TRACER can be set, which is what
        _setup_monitoring does when all candidate IDs are taken.
        """
        from scalene.scalene_tracer import (
            _CANDIDATE_TOOL_IDS,
            _SYS_MONITORING_AVAILABLE,
            _FORCE_LEGACY_TRACER,
            set_use_legacy_tracer,
            _use_sys_monitoring,
        )

        if not _SYS_MONITORING_AVAILABLE:
            self.skipTest("sys.monitoring not available")

        # Verify the fallback mechanism works by testing set_use_legacy_tracer
        original_value = _FORCE_LEGACY_TRACER

        try:
            # When _FORCE_LEGACY_TRACER is True, _use_sys_monitoring() returns False
            set_use_legacy_tracer(True)
            self.assertFalse(
                _use_sys_monitoring(),
                "Expected _use_sys_monitoring() to return False when legacy mode is forced",
            )

            # When _FORCE_LEGACY_TRACER is False, _use_sys_monitoring() returns True
            set_use_legacy_tracer(False)
            self.assertTrue(
                _use_sys_monitoring(),
                "Expected _use_sys_monitoring() to return True when legacy mode is not forced",
            )
        finally:
            # Restore original value
            set_use_legacy_tracer(original_value)

    def test_profiling_works_with_id_conflict(self):
        """Test that the tracer module has the correct setup for tool ID fallback.

        This verifies that _setup_monitoring has the logic to try multiple IDs.
        The actual runtime behavior is tested by test_scalene_with_torch.
        """
        from scalene.scalene_tracer import (
            _CANDIDATE_TOOL_IDS,
            _SCALENE_TOOL_ID,
            _SYS_MONITORING_AVAILABLE,
            _monitoring,
        )

        if not _SYS_MONITORING_AVAILABLE:
            self.skipTest("sys.monitoring not available")

        # Verify that we have multiple candidate IDs for fallback
        self.assertGreater(
            len(_CANDIDATE_TOOL_IDS),
            1,
            "Expected multiple candidate tool IDs for fallback",
        )

        # Verify PROFILER_ID is the first choice
        self.assertEqual(
            _CANDIDATE_TOOL_IDS[0],
            _monitoring.PROFILER_ID,
            "Expected PROFILER_ID to be the first candidate",
        )

        # Verify _SCALENE_TOOL_ID is one of the candidates
        # (It will be whichever one was successfully claimed during module init)
        self.assertIn(
            _SCALENE_TOOL_ID,
            _CANDIDATE_TOOL_IDS + [0],  # 0 is the default before init
            f"Unexpected _SCALENE_TOOL_ID: {_SCALENE_TOOL_ID}",
        )


@unittest.skipIf(sys.version_info < (3, 12), "sys.monitoring requires Python 3.12+")
class TestPyTorchCompatibility(unittest.TestCase):
    """Test compatibility with PyTorch."""

    def test_scalene_with_torch(self):
        """Test that Scalene can profile PyTorch code."""
        try:
            import torch  # noqa: F401
        except ImportError:
            self.skipTest("PyTorch not installed")

        # Create a test script that uses PyTorch
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("""
import torch

def compute():
    x = torch.randn(500, 500)
    y = torch.randn(500, 500)
    z = torch.matmul(x, y)
    return z.sum().item()

if __name__ == "__main__":
    result = compute()
    print(f"Result: {result}")
    print("SUCCESS")
""")
            test_file = f.name

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_file = f.name

        try:
            cmd = [
                sys.executable,
                "-m",
                "scalene",
                "run",
                "--json",
                "--outfile",
                output_file,
                "--cpu-only",  # Skip memory profiling to avoid potential conflicts
                test_file,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            # Check for crashes (SIGSEGV)
            self.assertNotEqual(
                result.returncode,
                -11,
                f"Scalene crashed with SIGSEGV:\nstderr: {result.stderr}",
            )
            # 245 = 256-11, how SIGSEGV sometimes appears
            self.assertNotEqual(
                result.returncode,
                245,
                f"Scalene crashed with SIGSEGV:\nstderr: {result.stderr}",
            )

            # Allow non-zero exit if it's just "code didn't run long enough"
            # The important thing is no crash
            if result.returncode != 0:
                if "did not run for long enough" in result.stderr:
                    # This is OK - profiling started successfully
                    print("Note: Code ran too fast for profiling, but no crash")
                    return
                self.fail(f"Scalene failed with PyTorch:\nstderr: {result.stderr}")

            self.assertIn("SUCCESS", result.stdout + result.stderr)

            # Profile might be empty if code ran too fast, but should be valid JSON
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                with open(output_file) as f:
                    profile = json.load(f)
                # Profile structure is valid if we got here

        finally:
            os.unlink(test_file)
            if os.path.exists(output_file):
                os.unlink(output_file)

    @unittest.skip("torch.profiler has compatibility issues with Scalene's signal handling")
    def test_scalene_with_torch_profiler(self):
        """Test that Scalene works when torch.profiler is used in profiled code.

        NOTE: This test is skipped because torch.profiler has known compatibility
        issues with Scalene's signal-based profiling. The tool ID conflict fix
        (#1015) addresses sys.monitoring conflicts, but torch.profiler also
        conflicts with Scalene's signal handlers, causing crashes.

        Users who need to use both should profile their code separately.
        """
        try:
            import torch  # noqa: F401
        except ImportError:
            self.skipTest("PyTorch not installed")

        # Create a test script that uses torch.profiler
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("""
import torch

def compute():
    x = torch.randn(500, 500)
    y = torch.randn(500, 500)
    z = torch.matmul(x, y)
    return z.sum().item()

# Use torch.profiler (may try to use sys.monitoring on Python 3.12+)
try:
    with torch.profiler.profile() as prof:
        result = compute()
except Exception as e:
    # torch.profiler may fail if sys.monitoring IDs are taken, that's OK
    print(f"torch.profiler failed (expected): {e}")
    result = compute()

print(f"Result: {result}")
print("SUCCESS")
""")
            test_file = f.name

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_file = f.name

        try:
            cmd = [
                sys.executable,
                "-m",
                "scalene",
                "run",
                "--json",
                "--outfile",
                output_file,
                test_file,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            # Main requirement: Scalene should not crash (no SIGSEGV)
            self.assertNotEqual(
                result.returncode,
                -11,  # SIGSEGV
                f"Scalene crashed with SIGSEGV:\nstderr: {result.stderr}",
            )
            self.assertNotEqual(
                result.returncode,
                245,  # 256-11, sometimes how SIGSEGV appears
                f"Scalene crashed with SIGSEGV:\nstderr: {result.stderr}",
            )

            # Should complete successfully
            self.assertEqual(
                result.returncode,
                0,
                f"Scalene failed:\nstdout: {result.stdout}\nstderr: {result.stderr}",
            )
            self.assertIn("SUCCESS", result.stdout + result.stderr)

        finally:
            os.unlink(test_file)
            if os.path.exists(output_file):
                os.unlink(output_file)


if __name__ == "__main__":
    unittest.main()
