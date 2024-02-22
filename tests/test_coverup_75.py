# file scalene/syntaxline.py:7-14
# lines [7, 8, 9, 11, 12, 13, 14]
# branches []

import pytest
from scalene.syntaxline import SyntaxLine
from rich.console import Console
from rich.segment import Segment

@pytest.fixture
def console():
    return Console()

@pytest.fixture
def segments():
    return [Segment("test"), Segment(" line")]

def test_rich_console(console, segments):
    syntax_line = SyntaxLine(segments)
    result = list(syntax_line.__rich_console__(console, None))
    assert result == segments

def test_cleanup(console, segments, tmp_path):
    # Create a temporary file to ensure the test environment is clean
    temp_file = tmp_path / "temp.txt"
    temp_file.write_text("temporary file content")
    assert temp_file.exists()

    # Run the test
    test_rich_console(console, segments)

    # Clean up by removing the temporary file
    temp_file.unlink()
    assert not temp_file.exists()
