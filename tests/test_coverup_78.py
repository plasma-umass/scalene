# file scalene/scalene_profiler.py:1843-1854
# lines [1843, 1844, 1846, 1848, 1850, 1851, 1852, 1853]
# branches []

import pytest
import sys
from unittest.mock import patch
from scalene.scalene_profiler import Scalene


@pytest.fixture
def scalene_cleanup():
    # Fixture to clean up any state after the test
    yield
    Scalene._Scalene__files_to_profile.clear()


@pytest.mark.skipif(
    sys.platform == "win32", reason="Test only applicable to win32 platform"
)
def test_register_files_to_profile(scalene_cleanup):
    # Set up the necessary attributes in Scalene
    Scalene._Scalene__args = type("", (), {})()
    Scalene._Scalene__args.profile_only = "test1.py,test2.py"
    Scalene._Scalene__args.profile_all = False
    Scalene._Scalene__files_to_profile = set(["test3.py"])
    Scalene._Scalene__program_path = "."

    with patch(
        "scalene.pywhere.register_files_to_profile"
    ) as mock_register_files_to_profile:
        # Call the method under test
        Scalene._register_files_to_profile()

        # The 4th positional arg is the canonical path of the installed
        # scalene package (used by TraceConfig to exclude Scalene-internal
        # frames via an absolute-path prefix check). Value depends on the
        # installation path, so assert it is a non-empty str rather than a
        # fixed string.
        assert mock_register_files_to_profile.call_count == 1
        args, kwargs = mock_register_files_to_profile.call_args
        assert args[0] == ["test3.py", "test1.py", "test2.py"]
        assert args[1] == "."
        assert args[2] is False
        assert isinstance(args[3], str) and args[3]  # non-empty package path
