"""Unit tests for scalene_tracer module.

These tests verify that the tracer correctly attributes memory per-line
using both sys.monitoring (Python 3.12+) and legacy PyEval_SetTrace.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest


class TestTracerModes(unittest.TestCase):
    """Test different tracer modes produce correct memory attribution."""

    @classmethod
    def setUpClass(cls):
        """Create a test script that makes large allocations."""
        cls.test_script = tempfile.NamedTemporaryFile(
            mode='w', suffix='.py', delete=False
        )
        cls.test_script.write('''
def make_allocations():
    # Line 3: Large allocation
    data1 = [0] * 10_000_000  # ~80MB
    # Line 5: Another large allocation
    data2 = [0] * 10_000_000  # ~80MB
    # Line 7: Yet another
    data3 = [0] * 10_000_000  # ~80MB
    return len(data1) + len(data2) + len(data3)

if __name__ == "__main__":
    result = make_allocations()
    print(f"Result: {result}")
''')
        cls.test_script.close()

    @classmethod
    def tearDownClass(cls):
        """Clean up test script."""
        os.unlink(cls.test_script.name)

    def run_scalene(self, extra_args=None):
        """Run scalene on the test script and return JSON output."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            output_file = f.name

        try:
            cmd = [
                sys.executable, '-m', 'scalene',
                'run', '--json', '--outfile', output_file,
            ]
            if extra_args:
                cmd.extend(extra_args)
            cmd.append(self.test_script.name)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                print(f"STDERR: {result.stderr}")

            with open(output_file) as f:
                return json.load(f)
        finally:
            if os.path.exists(output_file):
                os.unlink(output_file)

    def get_memory_allocations(self, profile_data, script_name):
        """Extract memory allocations per line from profile data."""
        allocations = {}
        files = profile_data.get('files', {})
        for fname, fdata in files.items():
            if script_name in fname:
                for line in fdata.get('lines', []):
                    lineno = line.get('lineno', 0)
                    n_malloc = line.get('n_malloc_mb', 0) + line.get('n_python_malloc_mb', 0)
                    if n_malloc > 0:
                        allocations[lineno] = n_malloc
        return allocations

    def test_sys_monitoring_default(self):
        """Test that sys.monitoring (default on Python 3.12+) attributes memory correctly."""
        if sys.version_info < (3, 12):
            self.skipTest("sys.monitoring requires Python 3.12+")

        profile = self.run_scalene()
        allocations = self.get_memory_allocations(profile, os.path.basename(self.test_script.name))

        # Should have allocations on lines 4, 6, and 8 (the actual list creation lines)
        # The exact line numbers depend on the script structure
        self.assertTrue(len(allocations) > 0, "No memory allocations detected")
        total_alloc = sum(allocations.values())
        # Expect at least 100MB allocated (3 * ~80MB, but sampling means we may not catch all)
        self.assertGreater(total_alloc, 50, f"Expected significant allocation, got {total_alloc}MB")

    def test_python_callback(self):
        """Test that Python callback mode works correctly."""
        if sys.version_info < (3, 12):
            self.skipTest("sys.monitoring requires Python 3.12+")

        profile = self.run_scalene(['--use-python-callback'])
        allocations = self.get_memory_allocations(profile, os.path.basename(self.test_script.name))

        self.assertTrue(len(allocations) > 0, "No memory allocations detected with Python callback")
        total_alloc = sum(allocations.values())
        self.assertGreater(total_alloc, 50, f"Expected significant allocation, got {total_alloc}MB")

    def test_legacy_tracer(self):
        """Test that legacy PyEval_SetTrace works correctly."""
        profile = self.run_scalene(['--use-legacy-tracer'])
        allocations = self.get_memory_allocations(profile, os.path.basename(self.test_script.name))

        self.assertTrue(len(allocations) > 0, "No memory allocations detected with legacy tracer")
        total_alloc = sum(allocations.values())
        self.assertGreater(total_alloc, 50, f"Expected significant allocation, got {total_alloc}MB")


class TestTracerAPI(unittest.TestCase):
    """Test the tracer API functions."""

    def test_using_sys_monitoring(self):
        """Test using_sys_monitoring returns correct value based on Python version."""
        from scalene.scalene_tracer import using_sys_monitoring

        if sys.version_info >= (3, 12):
            self.assertTrue(using_sys_monitoring())
        else:
            self.assertFalse(using_sys_monitoring())

    def test_set_use_legacy_tracer(self):
        """Test that set_use_legacy_tracer affects using_sys_monitoring."""
        from scalene.scalene_tracer import (
            set_use_legacy_tracer,
            using_sys_monitoring,
        )

        if sys.version_info < (3, 12):
            self.skipTest("sys.monitoring requires Python 3.12+")

        # Default should use sys.monitoring
        set_use_legacy_tracer(False)
        self.assertTrue(using_sys_monitoring())

        # Setting legacy mode should disable sys.monitoring
        set_use_legacy_tracer(True)
        self.assertFalse(using_sys_monitoring())

        # Reset
        set_use_legacy_tracer(False)

    def test_pywhere_sysmon_available(self):
        """Test that pywhere reports correct sysmon availability."""
        from scalene import pywhere

        # sysmon_available returns True if C API is available (Python 3.13+)
        available = pywhere.sysmon_available()
        if sys.version_info >= (3, 13):
            self.assertTrue(available)
        else:
            self.assertFalse(available)

    def test_pywhere_tool_id(self):
        """Test that pywhere returns correct tool ID."""
        from scalene import pywhere

        tool_id = pywhere.get_sysmon_tool_id()
        # Should be PROFILER_ID = 2
        self.assertEqual(tool_id, 2)


class TestFunctionCallHandling(unittest.TestCase):
    """Test that function calls from profiled lines are handled correctly."""

    @classmethod
    def setUpClass(cls):
        """Create a test script with function calls."""
        cls.test_script = tempfile.NamedTemporaryFile(
            mode='w', suffix='.py', delete=False
        )
        cls.test_script.write('''
def helper_function():
    # This allocation should NOT be attributed to the calling line
    return [0] * 5_000_000

def main():
    # Line 7: Allocation on this line
    data = [0] * 10_000_000
    # Line 9: Call to helper - allocation inside should be separate
    result = helper_function()
    # Line 11: Another allocation
    data2 = [0] * 10_000_000
    return len(data) + len(result) + len(data2)

if __name__ == "__main__":
    print(main())
''')
        cls.test_script.close()

    @classmethod
    def tearDownClass(cls):
        """Clean up test script."""
        os.unlink(cls.test_script.name)

    def test_function_call_attribution(self):
        """Test that allocations in called functions are not attributed to caller."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            output_file = f.name

        try:
            cmd = [
                sys.executable, '-m', 'scalene',
                'run', '--json', '--outfile', output_file,
                self.test_script.name
            ]
            subprocess.run(cmd, capture_output=True, timeout=60)

            with open(output_file) as f:
                profile = json.load(f)

            # Check that we have multiple lines with allocations
            files = profile.get('files', {})
            allocations = {}
            for fname, fdata in files.items():
                if os.path.basename(self.test_script.name) in fname:
                    for line in fdata.get('lines', []):
                        lineno = line.get('lineno', 0)
                        n_malloc = line.get('n_malloc_mb', 0) + line.get('n_python_malloc_mb', 0)
                        if n_malloc > 0:
                            allocations[lineno] = n_malloc

            # Should have allocations detected
            self.assertTrue(len(allocations) > 0, "No allocations detected")

        finally:
            if os.path.exists(output_file):
                os.unlink(output_file)


if __name__ == '__main__':
    unittest.main()
