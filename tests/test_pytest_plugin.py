"""Tests for the Scalene pytest plugin (scalene/pytest_scalene.py).

Covers https://github.com/plasma-umass/scalene/issues/70.

Two layers:
  * Unit tests for the pure argv/command-building helpers (no subprocess).
  * Integration tests that run a throwaway pytest session in-process via the
    ``pytester`` fixture, asserting that a profile gets written and that the
    @pytest.mark.scalene marker narrows what is profiled.

The integration tests need Scalene's native extensions (CPU sampling), so
they skip cleanly if those aren't importable.
"""

from __future__ import annotations

import json
import sys

import pytest

from scalene import pytest_scalene

# Enables the `pytester` fixture for the integration tests.
pytest_plugins = ["pytester"]


# ---------------------------------------------------------------------------
# Unit tests: argv stripping and command construction (no subprocess)
# ---------------------------------------------------------------------------


def test_strip_scalene_args_removes_flags():
    argv = ["-v", "--scalene", "--scalene-memory", "test_foo.py"]
    assert pytest_scalene._strip_scalene_args(argv) == ["-v", "test_foo.py"]


def test_strip_scalene_args_removes_value_option_and_value():
    argv = ["--scalene", "--scalene-outfile", "out.json", "-k", "fast"]
    assert pytest_scalene._strip_scalene_args(argv) == ["-k", "fast"]


def test_strip_scalene_args_removes_equals_form():
    argv = ["--scalene-outfile=out.json", "--scalene-args=--profile-all", "x.py"]
    assert pytest_scalene._strip_scalene_args(argv) == ["x.py"]


def test_strip_scalene_args_preserves_plugin_loader_flag():
    # `-p scalene.pytest_scalene` must survive so the re-exec'd child can load
    # the plugin even when it isn't installed as an entry point.
    argv = ["-p", "scalene.pytest_scalene", "--scalene", "test_foo.py"]
    assert pytest_scalene._strip_scalene_args(argv) == [
        "-p",
        "scalene.pytest_scalene",
        "test_foo.py",
    ]


# ---------------------------------------------------------------------------
# Integration tests via the pytester fixture
# ---------------------------------------------------------------------------


def _integration_ready() -> bool:
    """Whether a child interpreter can both profile and load the plugin.

    The integration tests shell out to a subprocess pytest, so they need:
      * the compiled get_line_atomic/pywhere extensions (CPU sampling), and
      * the SAME scalene that the subprocess will import to expose
        ``scalene.pytest_scalene`` (i.e. the package-under-test is installed,
        not shadowed by a different editable checkout).
    """
    import subprocess
    import tempfile

    try:
        import scalene.get_line_atomic  # noqa: F401
    except Exception:
        return False
    # Probe from a neutral cwd (not the repo): a `python -c` run from inside
    # the repo would find the working-tree plugin via the implicit cwd entry
    # on sys.path, but the pytester subprocess runs in a temp dir and only
    # sees installed packages. Match that condition to avoid a false positive
    # on dev machines whose editable install points at a different checkout.
    with tempfile.TemporaryDirectory() as neutral:
        proc = subprocess.run(
            [sys.executable, "-c", "import scalene.pytest_scalene"],
            capture_output=True,
            cwd=neutral,
        )
    return proc.returncode == 0


requires_native = pytest.mark.skipif(
    not _integration_ready(),
    reason="Scalene native extensions or plugin not importable from a "
    "subprocess in this environment",
)


def _run(pytester: pytest.Pytester, *args: str):
    """Run a child pytest session with the Scalene plugin explicitly loaded."""
    return pytester.runpytest_subprocess("-p", "scalene.pytest_scalene", *args)


@requires_native
def test_session_profile_written(pytester: pytest.Pytester) -> None:
    """`pytest --scalene` profiles the whole session and writes a profile."""
    pytester.makepyfile(
        test_sample="""
        import time

        def _burn():
            end = time.process_time() + 0.5
            acc = 0
            while time.process_time() < end:
                acc = sum(i * i for i in range(2000))
            return acc

        def test_one():
            assert _burn() >= 0
        """
    )
    outfile = pytester.path / "scalene-profile.json"
    result = _run(
        pytester,
        "--scalene",
        "--scalene-outfile",
        str(outfile),
        "test_sample.py",
    )
    result.assert_outcomes(passed=1)
    assert outfile.exists(), "Scalene should have written a profile"
    data = json.loads(outfile.read_text())
    # The test file should appear among the profiled files.
    assert any("test_sample.py" in f for f in data.get("files", {}))


@requires_native
def test_marker_narrows_profiling(pytester: pytest.Pytester) -> None:
    """@pytest.mark.scalene profiles only the marked test, not the rest."""
    pytester.makepyfile(
        test_marked="""
        import time
        import pytest

        def _burn_unmarked():
            end = time.process_time() + 0.4
            acc = 0
            while time.process_time() < end:
                acc = sum(i * i for i in range(2000))
            return acc

        def _burn_marked():
            end = time.process_time() + 0.6
            acc = 0
            while time.process_time() < end:
                acc = sum(i * i for i in range(2000))
            return acc

        def test_unmarked():
            assert _burn_unmarked() >= 0

        @pytest.mark.scalene
        def test_marked():
            assert _burn_marked() >= 0
        """
    )
    outfile = pytester.path / "scalene-profile.json"
    result = _run(
        pytester,
        "--scalene",
        "--scalene-outfile",
        str(outfile),
        "test_marked.py",
    )
    result.assert_outcomes(passed=2)
    assert outfile.exists()
    data = json.loads(outfile.read_text())
    test_file = next(
        (f for f in data.get("files", {}) if "test_marked.py" in f), None
    )
    assert test_file is not None
    funcs = {
        fn["line"]: fn["n_cpu_percent_python"] + fn["n_cpu_percent_c"]
        for fn in data["files"][test_file].get("functions", [])
    }
    # The marked function should dominate; the unmarked one should not be
    # meaningfully sampled (allow a small slop for stray samples at the
    # suspend/resume boundary).
    marked = funcs.get("_burn_marked", 0.0)
    unmarked = funcs.get("_burn_unmarked", 0.0)
    assert marked > unmarked
    assert unmarked < 10.0, f"unmarked test was profiled too much: {unmarked}%"


@requires_native
def test_plugin_noop_without_flag(pytester: pytest.Pytester) -> None:
    """Without --scalene, the plugin must not write a profile or interfere."""
    pytester.makepyfile(
        test_plain="""
        def test_trivial():
            assert 1 + 1 == 2
        """
    )
    result = _run(pytester, "test_plain.py")
    result.assert_outcomes(passed=1)
    assert not (pytester.path / "scalene-profile.json").exists()


@requires_native
def test_marker_registered(pytester: pytest.Pytester) -> None:
    """The `scalene` marker is registered (no PytestUnknownMarkWarning)."""
    result = _run(pytester, "--markers")
    result.stdout.fnmatch_lines(["*@pytest.mark.scalene*"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
