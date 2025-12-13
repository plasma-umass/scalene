# file scalene/scalene_parseargs.py:15-24
# lines [17, 19, 20, 23, 24]
# branches ['23->exit', '23->24']

import argparse
import sys
from unittest.mock import patch, MagicMock
import pytest

# Assuming the RichArgParser class is in a file named scalene_parseargs.py
from scalene.scalene_parseargs import RichArgParser, _colorize_help_for_rich


def test_rich_arg_parser_print_message(capsys):
    if sys.version_info >= (3, 14):
        # Python 3.14+: Uses native print, not Rich
        parser = RichArgParser()
        parser._print_message("Test message")
        captured = capsys.readouterr()
        assert "Test message" in captured.out

        # Test with message being None (should not print)
        parser._print_message(None)
        captured = capsys.readouterr()
        assert captured.out == ""
    else:
        # Python < 3.14: Uses Rich console
        with patch("rich.console.Console") as mock_console_class:
            mock_console = MagicMock()
            mock_console_class.return_value = mock_console

            parser = RichArgParser()
            parser._print_message("Test message")

            # Should call print with colorized message and highlight=False
            mock_console.print.assert_called_once()
            call_args = mock_console.print.call_args
            assert call_args[1].get("highlight") is False

            # Test with message being None (should not call print again)
            mock_console.reset_mock()
            parser._print_message(None)
            mock_console.print.assert_not_called()


def test_rich_arg_parser_init():
    if sys.version_info >= (3, 14):
        # Python 3.14+: No Rich console
        parser = RichArgParser()
        assert parser._console is None
        assert isinstance(parser, argparse.ArgumentParser)
    else:
        # Python < 3.14: Uses Rich console
        with patch("rich.console.Console") as mock_console:
            parser = RichArgParser()
            mock_console.assert_called_once()
            assert isinstance(parser, argparse.ArgumentParser)


def test_colorize_help_for_rich():
    """Test the colorization function for Python < 3.14."""
    text = """usage: scalene [-h] [--version]

Scalene: a profiler

options:
  -h, --help       show help
  --version        show version
  --column-width COLUMN_WIDTH
                   set width
"""
    result = _colorize_help_for_rich(text)

    # Check that Rich markup was added
    assert "[bold blue]usage:[/bold blue]" in result
    assert "[bold magenta]scalene[/bold magenta]" in result
    assert "[bold blue]options:[/bold blue]" in result
    assert "[bold green]-h[/bold green]" in result
    assert "[bold cyan]--help[/bold cyan]" in result
    assert "[bold cyan]--version[/bold cyan]" in result
    assert "[bold cyan]--column-width[/bold cyan]" in result
    assert "[bold yellow]COLUMN_WIDTH[/bold yellow]" in result
