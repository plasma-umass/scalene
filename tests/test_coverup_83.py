# file scalene/scalene_parseargs.py:15-24
# lines [17, 19, 20, 23, 24]
# branches ['23->exit', '23->24']

import argparse
import sys

import pytest

# Assuming the RichArgParser class is in a file named scalene_parseargs.py
from scalene.scalene_parseargs import RichArgParser, _colorize_help_for_rich


@pytest.mark.parametrize("use_rich", [True, False])
def test_rich_arg_parser_print_message(capsys, use_rich):
    # Both paths (Rich on Python < 3.14, native argparse colors on 3.14+)
    # write to the stream argparse asks for, defaulting to stderr like
    # argparse does: help goes to stdout, usage errors to stderr.
    parser = RichArgParser()
    parser._use_rich = use_rich

    parser._print_message("Test message", sys.stdout)
    captured = capsys.readouterr()
    assert "Test message" in captured.out
    assert captured.err == ""

    parser._print_message("Error message")
    captured = capsys.readouterr()
    assert "Error message" in captured.err
    assert captured.out == ""

    # Test with message being None (should not print)
    parser._print_message(None)
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_rich_arg_parser_uses_rich_before_3_14():
    parser = RichArgParser()
    assert parser._use_rich == (sys.version_info < (3, 14))
    assert isinstance(parser, argparse.ArgumentParser)


def test_rich_arg_parser_error_goes_to_stderr(capsys):
    parser = RichArgParser(prog="scalene run")
    with pytest.raises(SystemExit) as exc:
        parser.error("unrecognized arguments: --typo")
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "unrecognized arguments: --typo" in captured.err
    assert captured.out == ""


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
