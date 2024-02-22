# file scalene/scalene_profiler.py:1843-1854
# lines [1843, 1844, 1846, 1848, 1850, 1851, 1852, 1853]
# branches []

import pytest
from unittest.mock import patch
from scalene.scalene_profiler import Scalene

@pytest.fixture
def scalene_cleanup():
    # Fixture to clean up any state after the test
    yield
    Scalene._Scalene__files_to_profile.clear()

def test_register_files_to_profile(scalene_cleanup):
    # Set up the necessary attributes in Scalene
    Scalene._Scalene__args = type('', (), {})()
    Scalene._Scalene__args.profile_only = 'test1.py,test2.py'
    Scalene._Scalene__args.profile_all = False
    Scalene._Scalene__files_to_profile = set(['test3.py'])
    Scalene._Scalene__program_path = '.'

    with patch('scalene.pywhere.register_files_to_profile') as mock_register_files_to_profile:
        # Call the method under test
        Scalene.register_files_to_profile()

        # Check that pywhere.register_files_to_profile was called with the correct arguments
        mock_register_files_to_profile.assert_called_once_with(
            ['test3.py', 'test1.py', 'test2.py'], '.', False
        )
