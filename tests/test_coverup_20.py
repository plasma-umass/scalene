# file scalene/launchbrowser.py:101-145
# lines [101, 104, 106, 107, 108, 109, 110, 114, 116, 117, 118, 119, 120, 121, 125, 126, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 141, 142, 143, 144, 145]
# branches []

import os
import pytest
import tempfile
from scalene.launchbrowser import generate_html
from unittest.mock import patch

@pytest.fixture
def mock_environment():
    with patch("scalene.launchbrowser.Environment") as mock_env:
        mock_env.return_value.get_template.return_value.render.return_value = "rendered content"
        yield mock_env

@pytest.fixture
def mock_read_file_content():
    with patch("scalene.launchbrowser.read_file_content") as mock_read:
        mock_read.return_value = "file content"
        yield mock_read

def test_generate_html_file_not_found(mock_environment, mock_read_file_content):
    with tempfile.TemporaryDirectory() as tmpdirname:
        profile_fname = os.path.join(tmpdirname, "nonexistent_profile.prof")
        output_fname = os.path.join(tmpdirname, "output.html")
        with pytest.raises(AssertionError):
            generate_html(profile_fname, output_fname)
        assert not os.path.exists(output_fname)

def test_generate_html_success(mock_environment, mock_read_file_content):
    with tempfile.TemporaryDirectory() as tmpdirname:
        profile_fname = os.path.join(tmpdirname, "profile.prof")
        output_fname = os.path.join(tmpdirname, "output.html")
        # Create a dummy profile file
        with open(profile_fname, "w") as f:
            f.write("{}")
        generate_html(profile_fname, output_fname)
        assert os.path.exists(output_fname)
        with open(output_fname, "r") as f:
            content = f.read()
        assert content == "rendered content"

def test_generate_html_os_error(mock_environment, mock_read_file_content):
    with tempfile.TemporaryDirectory() as tmpdirname:
        profile_fname = os.path.join(tmpdirname, "profile.prof")
        output_fname = os.path.join(tmpdirname, "output.html")
        # Create a dummy profile file
        with open(profile_fname, "w") as f:
            f.write("{}")
        with patch("builtins.open", side_effect=OSError):
            generate_html(profile_fname, output_fname)
        assert not os.path.exists(output_fname)
