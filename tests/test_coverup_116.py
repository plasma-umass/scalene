# file scalene/scalene_utility.py:128-172
# lines [131, 133, 134, 135, 136, 137, 141, 143, 144, 145, 146, 147, 148, 152, 153, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164, 168, 169, 170, 171, 172]
# branches []

import os
import pytest
from scalene.scalene_utility import generate_html

@pytest.fixture
def cleanup_files():
    created_files = []
    yield created_files
    for file in created_files:
        if os.path.exists(file):
            os.remove(file)

def test_generate_html(cleanup_files):
    # Create a temporary profile file with some content
    profile_fname = "temp_profile.prof"
    output_fname = "temp_output.html"
    cleanup_files.extend([profile_fname, output_fname])
    
    with open(profile_fname, "w") as f:
        f.write("profile content")

    # Call the function to generate HTML
    generate_html(profile_fname, output_fname)

    # Check if the output file was created and has content
    assert os.path.exists(output_fname)
    with open(output_fname, "r") as f:
        content = f.read()
        assert content  # The file should not be empty

    # Check if the output file contains the profile content
    assert "profile content" in content

    # Clean up the created files
    os.remove(profile_fname)
    os.remove(output_fname)
