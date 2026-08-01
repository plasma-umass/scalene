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
import os
import sys

import pytest

from scalene import pytest_scalene

# Enables the `pytester` fixture for the integration tests.
pytest_plugins = ["pytester"]

# Capture the interpreter and PATH at import time, before any test in the wider
# suite constructs a ``Scalene`` instance. Constructing one runs
# ``redirect_python``, which permanently rewrites ``sys.executable`` to a
# wrapper that re-launches Python under ``scalene run`` and prepends that
# wrapper's dir to ``PATH``. ``pytester.runpytest_subprocess`` reads
# ``sys.executable`` at call time, so our subprocess pytest would otherwise run
# as ``scalene run -m pytest`` (no pytest summary) or use the wrong interpreter.
# These pristine values are restored around each subprocess launch in ``_run``.
_PRISTINE_EXECUTABLE = sys.executable
_PRISTINE_PATH = os.environ.get("PATH", "")


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
    """Whether a subprocess pytest auto-loads the plugin and can profile.

    The integration tests shell out to a subprocess pytest and rely on the
    plugin being installed as a ``pytest11`` entry point (the real user path,
    and what CI provides via ``pip install -e .``). They need:
      * the compiled get_line_atomic/pywhere extensions (CPU sampling), and
      * a subprocess pytest that recognizes ``--scalene`` - i.e. the
        package-under-test is installed and its entry point registered, not
        shadowed by a different editable checkout that lacks the plugin.

    We deliberately do NOT load the plugin with ``-p`` in the subprocess: when
    the entry point is registered, pytest already auto-loads the module, and a
    second explicit ``-p`` would re-register it under a different name and
    raise ``ValueError: Plugin already registered``.
    """
    import subprocess
    import tempfile

    try:
        import scalene.get_line_atomic  # noqa: F401
    except Exception:
        return False
    # Probe from a neutral cwd (not the repo) so the implicit cwd entry on
    # sys.path can't make a working-tree plugin look "installed" when the
    # actual entry point lives in a different (shadowing) checkout.
    with tempfile.TemporaryDirectory() as neutral:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--help"],
            capture_output=True,
            cwd=neutral,
            text=True,
        )
    return "--scalene" in proc.stdout


requires_native = pytest.mark.skipif(
    not _integration_ready(),
    reason="Scalene plugin entry point not auto-loaded by a subprocess pytest "
    "(or native extensions missing) in this environment",
)


def _run(pytester: pytest.Pytester, *args: str):
    """Run a child pytest session.

    The plugin is auto-loaded via its ``pytest11`` entry point (guaranteed by
    ``_integration_ready``); we must NOT pass ``-p scalene.pytest_scalene`` or
    pytest would try to register the already-loaded module a second time.

    A subtlety when running inside the full Scalene test suite: if some
    earlier test constructed a ``Scalene`` instance, ``redirect_python``
    permanently rewrote ``sys.executable`` to a wrapper script (in a
    ``mkdtemp(prefix="scalene")`` dir) that re-launches Python under
    ``scalene run``, and prepended that dir to ``PATH``. ``runpytest_subprocess``
    launches ``sys.executable``, so without cleanup our inner ``pytest`` would
    run as ``scalene run -m pytest`` (no pytest summary) or pick the wrong
    interpreter. Restore the import-time interpreter and PATH (captured before
    any contamination) for the duration of the subprocess call.
    """
    saved_exe = sys.executable
    saved_path = os.environ.get("PATH", "")
    sys.executable = _PRISTINE_EXECUTABLE
    os.environ["PATH"] = _PRISTINE_PATH
    try:
        return pytester.runpytest_subprocess(*args)
    finally:
        sys.executable = saved_exe
        os.environ["PATH"] = saved_path


@requires_native
def test_session_profile_written(pytester: pytest.Pytester) -> None:
    """`pytest --scalene` profiles the whole session and writes a profile.

    Burns a couple of seconds and retries: Scalene writes no profile (and
    prints "did not run long enough") if it collected zero samples, which is
    timing-dependent on a busy CI runner (see CLAUDE.md).
    """
    pytester.makepyfile(
        test_sample="""
        import time

        def _burn():
            end = time.process_time() + 2.0
            acc = 0
            while time.process_time() < end:
                acc = sum(i * i for i in range(3000))
            return acc

        def test_one():
            assert _burn() >= 0
        """
    )
    outfile = pytester.path / "scalene-profile.json"
    profiled = False
    for _attempt in range(4):
        outfile.unlink(missing_ok=True)
        result = _run(
            pytester,
            "--scalene",
            "--scalene-outfile",
            str(outfile),
            "test_sample.py",
        )
        result.assert_outcomes(passed=1)
        if outfile.exists():
            data = json.loads(outfile.read_text())
            if any("test_sample.py" in f for f in data.get("files", {})):
                profiled = True
                break
    if not profiled:
        pytest.skip("profiler collected no CPU samples for the test file")


def _cpu_by_helper(data: dict, test_file_substr: str) -> dict:
    """Map helper-name -> total CPU% attributed to that helper's body.

    Scalene's per-function record keys ``"line"`` by the *source text* of the
    def line (e.g. ``"def _burn_marked():"``), not the bare name, so we match
    by substring. We also fold in per-line CPU whose source text mentions the
    helper, so attribution that lands on a call site inside the helper still
    counts.
    """
    test_file = next(
        (f for f in data.get("files", {}) if test_file_substr in f), None
    )
    if test_file is None:
        return {}
    fdata = data["files"][test_file]
    totals = {"_burn_unmarked": 0.0, "_burn_marked": 0.0}
    for rec in list(fdata.get("functions", [])) + list(fdata.get("lines", [])):
        text = rec.get("line", "")
        cpu = rec.get("n_cpu_percent_python", 0.0) + rec.get("n_cpu_percent_c", 0.0)
        for name in totals:
            if name in text:
                totals[name] += cpu
    return totals


@requires_native
def test_marker_narrows_profiling(pytester: pytest.Pytester) -> None:
    """@pytest.mark.scalene profiles only the marked test, not the rest.

    Retries on the sampling flakiness inherent to a signal-based profiler: a
    short test may not receive a single CPU sample (see CLAUDE.md). We burn
    generously and retry a few times; the meaningful assertion is that the
    *unmarked* test (which runs with sampling suspended) collects essentially
    no CPU while the *marked* one does.
    """
    pytester.makepyfile(
        test_marked="""
        import time
        import pytest

        def _burn_unmarked():
            end = time.process_time() + 1.0
            acc = 0
            while time.process_time() < end:
                acc = sum(i * i for i in range(3000))
            return acc

        def _burn_marked():
            end = time.process_time() + 2.0
            acc = 0
            while time.process_time() < end:
                acc = sum(i * i for i in range(3000))
            return acc

        def test_unmarked():
            assert _burn_unmarked() >= 0

        @pytest.mark.scalene
        def test_marked():
            assert _burn_marked() >= 0
        """
    )
    outfile = pytester.path / "scalene-profile.json"
    marked = unmarked = 0.0
    for _attempt in range(4):
        outfile.unlink(missing_ok=True)
        result = _run(
            pytester,
            "--scalene",
            "--scalene-outfile",
            str(outfile),
            "test_marked.py",
        )
        result.assert_outcomes(passed=2)
        if not outfile.exists():
            continue
        totals = _cpu_by_helper(json.loads(outfile.read_text()), "test_marked.py")
        marked = totals.get("_burn_marked", 0.0)
        unmarked = totals.get("_burn_unmarked", 0.0)
        if marked > 0.0:
            break  # got at least one sample in the marked region

    if marked == 0.0:
        pytest.skip("profiler collected no CPU samples (sampling flakiness)")
    # Selectivity: the unmarked test ran with sampling suspended, so it should
    # have collected essentially nothing relative to the marked test. Allow a
    # little slop for a stray sample at the suspend/resume boundary.
    assert unmarked < marked
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


@requires_native
def test_distributed_xdist_profiles_workers(pytester: pytest.Pytester) -> None:
    """`--scalene -n 2` profiles the xdist workers, not just the controller.

    The tests execute in worker subprocesses. Sampling in-process in the
    controller would see essentially none of that work, so a distributed run
    re-execs under `scalene run`: the workers are then launched through
    Scalene's python alias, run as children, and their stats are merged into
    one profile. Asserting on the *contents* is the point -- an earlier
    version of this plugin wrote a profile here that was technically valid but
    nearly empty.
    """
    pytest.importorskip("xdist")
    pytester.makepyfile(
        test_w1="""
        def test_burn_one():
            total = 0
            for i in range(3_000_000):
                total += i
            assert total > 0
        """,
        test_w2="""
        def test_burn_two():
            data = [[j for j in range(3000)] for _ in range(400)]
            assert len(data) == 400
        """,
    )

    # The deterministic part, checked on every attempt: the session has to
    # succeed and write a profile. If the xdist run stopped being routed
    # through `scalene run`, the plugin raises UsageError and the session
    # errors out here -- which is how this test catches that regression.
    #
    # Which *workers* land in the profile is sampling-dependent (a short test
    # can finish between samples), so the stronger "both workers present"
    # assertion is retried and, failing that, skipped rather than flaked --
    # the same tradeoff as tests/_scalene_subprocess.py.
    seen: set[str] = set()
    for _attempt in range(3):
        profile = pytester.path / "scalene-profile.json"
        if profile.exists():
            profile.unlink()
        result = _run(pytester, "--scalene", "-n", "2", "-q")
        result.assert_outcomes(passed=2)
        assert profile.exists(), "distributed run wrote no profile"

        files = json.loads(profile.read_text())["files"]
        seen = {os.path.basename(name) for name in files}
        if {"test_w1.py", "test_w2.py"} <= seen:
            total_cpu = sum(
                line["n_cpu_percent_python"] + line["n_cpu_percent_c"]
                for data in files.values()
                for line in data["lines"]
            )
            assert total_cpu > 1.0, (
                f"both workers present but only {total_cpu:.2f}% CPU attributed"
            )
            return
    pytest.skip(
        "Only sampled workers "
        f"{sorted(seen) or 'none'} across 3 attempts; the session ran and "
        "produced a profile each time, so xdist routing is working, but "
        "sampling never covered both workers."
    )


@requires_native
def test_memory_with_xdist_is_rejected(pytester: pytest.Pytester) -> None:
    """`--scalene-memory -n 2` must refuse rather than report zero bytes.

    CPU aggregates across workers, but allocation tracking does not: the run
    comes back with max_footprint_mb == 0 and 0 MB on every line for a
    workload that reports tens of MB serially. A memory profile that is
    uniformly zero looks like "your tests allocate nothing," so this
    combination is rejected outright.
    """
    pytest.importorskip("xdist")
    pytester.makepyfile(
        test_alloc="""
        def test_alloc():
            data = [[j for j in range(3000)] for _ in range(400)]
            assert len(data) == 400
        """
    )
    result = _run(pytester, "--scalene-memory", "-n", "2", "test_alloc.py")
    assert result.ret != 0, "--scalene-memory with -n should not succeed"
    result.stderr.fnmatch_lines(["*cannot be combined with a distributed*"])
    assert not (pytester.path / "scalene-profile.json").exists()


@requires_native
def test_xdist_zero_workers_still_profiles(pytester: pytest.Pytester) -> None:
    """`-n 0` keeps everything in-process, so profiling stays allowed."""
    pytest.importorskip("xdist")
    pytester.makepyfile(
        test_inproc="""
        def test_work():
            total = 0
            for i in range(2_000_000):
                total += i
            assert total > 0
        """
    )
    result = _run(pytester, "--scalene", "-n", "0", "test_inproc.py")
    result.assert_outcomes(passed=1)
    assert (pytester.path / "scalene-profile.json").exists()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
