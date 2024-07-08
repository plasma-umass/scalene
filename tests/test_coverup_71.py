# file scalene/__main__.py:13-21
# lines [13, 14, 15, 17, 18, 19, 20, 21]
# branches []

import pytest
from unittest.mock import patch
import sys
import io
from scalene import scalene_profiler

# Test function to improve coverage for the main function in scalene.__main__
def test_main_exception_handling():
    # Mock the Scalene main function to raise an exception
    with patch('scalene.scalene_profiler.Scalene.main', side_effect=Exception("Test Exception")):
        # Redirect stderr to capture the output
        with patch('sys.stderr', new=io.StringIO()) as fake_stderr:
            # Mock sys.exit to prevent the test from exiting
            with patch('sys.exit', side_effect=SystemExit) as mock_exit:
                # Call the main function which should now raise an exception
                with pytest.raises(SystemExit):
                    from scalene.__main__ import main
                    main()
                # Check that the exception message was printed to stderr
                assert "ERROR: Calling Scalene main function failed: Test Exception" in fake_stderr.getvalue()
                # Check that sys.exit was called with the correct exit code
                mock_exit.assert_called_once_with(1)
