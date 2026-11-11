"""Unrecognized `scalene run` options must not leak into the program's argv.

`run` uses parse_known_args(), and the leftover arguments become the profiled
program's sys.argv. `--no-browser` (removed from the CLI in #963, but still
passed by older scripts and integrations) and typos such as `--cpu-onyl`
used to land there, so the program saw e.g. ['--no-browser', 'prog.py', ...].
"""

import sys
from unittest.mock import patch

import pytest

from scalene.scalene_parseargs import ScaleneParseArgs


def _parse(*argv: str):
    with patch.object(sys, "argv", ["scalene", "run", *argv]):
        return ScaleneParseArgs.parse_args()


@pytest.mark.parametrize("option", ["--no-browser", "--json", "--cpu"])
def test_legacy_noop_option_is_accepted_and_not_passed_through(option) -> None:
    _, left = _parse(option, "prog.py", "x")
    assert left == ["prog.py", "x"]


def test_legacy_cpu_means_cpu_only() -> None:
    args, _ = _parse("--cpu", "prog.py")
    assert args.cpu is True
    assert args.memory is False
    assert args.gpu is False


@pytest.mark.parametrize(
    "option", ["--cli", "--html", "--web", "--viewer", "--column-width=100"]
)
def test_legacy_view_option_points_to_view(option, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _parse(option, "prog.py")
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "no longer a `scalene run` option" in err
    assert "scalene view" in err


@pytest.mark.parametrize(
    "argv",
    [
        ("--cpu-onyl", "prog.py"),
        ("--cpu-onyl=1", "prog.py"),
        ("--typo", "-m", "json.tool"),
    ],
)
def test_unknown_option_before_program_is_an_error(argv, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _parse(*argv)
    assert exc.value.code == 2
    assert f"unrecognized arguments: {argv[0]}" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv, expected",
    [
        # Options after the program belong to the program.
        (("prog.py", "--verbose", "x"), ["prog.py", "--verbose", "x"]),
        (("-m", "mod", "--verbose"), ["-m", "mod", "--verbose"]),
        # Arguments after --- are passed through untouched.
        (("--cpu-only", "prog.py", "---", "--flag"), ["prog.py", "--flag"]),
        # Single-dash interpreter flags are left for run_profiler to strip.
        (("-u", "prog.py"), ["-u", "prog.py"]),
    ],
)
def test_program_arguments_still_pass_through(argv, expected) -> None:
    _, left = _parse(*argv)
    assert left == expected
