# file scalene/scalene_parseargs.py:15-24
# lines [17, 19, 20, 23, 24]
# branches ['23->exit', '23->24']

import argparse
from unittest.mock import patch
import pytest

# Assuming the RichArgParser class is in a file named scalene_parseargs.py
from scalene.scalene_parseargs import RichArgParser

def test_rich_arg_parser_print_message(capsys):
    with patch('rich.console.Console') as mock_console:
        parser = RichArgParser()
        parser._print_message("Test message")
        mock_console.return_value.print.assert_called_once_with("Test message")

        # Now test with message being None
        parser._print_message(None)
        mock_console.return_value.print.assert_called_once_with("Test message")

        # Capture the output to ensure it's not printed to the actual console
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

def test_rich_arg_parser_init():
    with patch('rich.console.Console') as mock_console:
        parser = RichArgParser()
        mock_console.assert_called_once()
        assert isinstance(parser, argparse.ArgumentParser)
