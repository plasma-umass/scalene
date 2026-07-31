"""Pytest plugin for Scalene.

Lets you profile a test run with Scalene straight from pytest::

    pytest --scalene                  # profile the whole session (CPU)
    pytest --scalene -k test_hot      # profile just the selected tests
    pytest --scalene --scalene-memory # full CPU+memory profile (re-execs)

This resolves https://github.com/plasma-umass/scalene/issues/70, which asked
for a way to run a test suite under Scalene without writing a throwaway
driver script. Two execution modes are supported:

In-process (default)
    The plugin sets up Scalene's signal-based CPU profiler inside the running
    pytest process. No re-exec, so it composes with IDE test runners and with
    ``-k``/marker selection. Memory profiling is *not* available this way
    because tracking allocations requires libscalene to be preloaded
    (``LD_PRELOAD``/``DYLD_INSERT_LIBRARIES``) before the interpreter starts.

Re-exec (``--scalene-memory`` / ``--scalene-gpu``)
    When full profiling is requested and we are *not* already running under
    ``scalene run``, the plugin re-launches the same pytest invocation as
    ``python -m scalene run --memory -m pytest ...`` so libscalene is
    preloaded. When pytest *is* already running under ``scalene run`` (i.e.
    ``scalene run -m pytest``), the plugin detects that and simply drives the
    profiler that is already initialized - no second re-exec.

Granularity
    By default the entire session (collection + every test) is profiled and a
    single ``scalene-profile.json`` is written at the end. Marking tests with
    ``@pytest.mark.scalene`` narrows profiling to only those tests; the rest of
    the session runs with sampling suspended.
"""

from __future__ import annotations

import contextlib
import os
import sys
from typing import TYPE_CHECKING, Any, Generator

if TYPE_CHECKING:
    import pytest


# Environment marker set on the re-exec'd child so it doesn't try to re-exec
# again (which would loop forever).
_REEXEC_GUARD = "SCALENE_PYTEST_REEXEC"

_DEFAULT_OUTFILE = "scalene-profile.json"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the plugin's command-line options."""
    group = parser.getgroup("scalene", "Scalene profiler")
    group.addoption(
        "--scalene",
        action="store_true",
        default=False,
        help="Profile the test run with Scalene (CPU). "
        "Writes scalene-profile.json on completion.",
    )
    group.addoption(
        "--scalene-memory",
        action="store_true",
        default=False,
        help="Profile CPU and memory with Scalene. Implies --scalene. "
        "Re-execs pytest under `scalene run` because memory profiling "
        "requires libscalene to be preloaded.",
    )
    group.addoption(
        "--scalene-gpu",
        action="store_true",
        default=False,
        help="Also profile GPU time and memory (implies --scalene). "
        "Requires the re-exec path, like --scalene-memory.",
    )
    group.addoption(
        "--scalene-outfile",
        action="store",
        default=None,
        metavar="PATH",
        help="Where to write the Scalene profile "
        "(default: scalene-profile.json in the current directory).",
    )
    group.addoption(
        "--scalene-args",
        action="store",
        default="",
        metavar="ARGS",
        help="Extra arguments to forward to `scalene run` when re-execing "
        "for memory/GPU profiling, e.g. --scalene-args='--profile-all'.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``scalene`` marker and, if asked, install the plugin."""
    config.addinivalue_line(
        "markers",
        "scalene: profile only this test with Scalene (when running "
        "`pytest --scalene`). When any test is marked, unmarked tests still "
        "run but with profiling suspended.",
    )

    if not _scalene_requested(config):
        return

    _reject_distributed(config)

    # Memory/GPU profiling needs libscalene preloaded, which can only happen
    # by launching the interpreter under `scalene run`. If the user asked for
    # it and we're not already there, re-exec (unless we already tried once).
    if (
        _needs_preload(config)
        and not _already_under_scalene()
        and not os.environ.get(_REEXEC_GUARD)
    ):
        _reexec_under_scalene(config)
        # _reexec_under_scalene does not return.

    config.pluginmanager.register(ScalenePlugin(config), "scalene-plugin")


def _reject_distributed(config: pytest.Config) -> None:
    """Refuse to profile a pytest-xdist run distributed across workers.

    Under ``-n 2`` (or any ``--dist`` mode) the tests execute in worker
    subprocesses. The sampler installed here lives in the controller, which
    does almost nothing, so the run *succeeds* and writes a profile that is
    essentially empty -- observed as ~1% on a single line for a workload that
    attributes ~95% correctly when run serially. A silently near-empty profile
    is worse than no profile, so fail fast with something actionable.

    ``-n 0`` is fine and stays allowed: xdist runs everything in this process
    and leaves ``dist`` at ``"no"``.
    """
    import pytest

    dist = getattr(config.option, "dist", "no")
    if dist == "no":
        return
    raise pytest.UsageError(
        f"--scalene cannot profile a distributed pytest-xdist run (--dist={dist}): "
        "the tests execute in worker subprocesses that the profiler does not "
        "observe, so the profile would come out nearly empty. Re-run without "
        "-n/--dist (or with -n 0, which keeps tests in this process)."
    )


def _scalene_requested(config: pytest.Config) -> bool:
    return bool(
        config.getoption("--scalene")
        or config.getoption("--scalene-memory")
        or config.getoption("--scalene-gpu")
    )


def _needs_preload(config: pytest.Config) -> bool:
    """Memory and GPU profiling both require the re-exec/preload path."""
    return bool(
        config.getoption("--scalene-memory") or config.getoption("--scalene-gpu")
    )


def _already_under_scalene() -> bool:
    """Return True if this process is already running under `scalene run`."""
    try:
        from scalene.scalene_profiler import Scalene
    except Exception:
        return False
    return Scalene.get_initialized()


def _reexec_under_scalene(config: pytest.Config) -> None:
    """Re-launch pytest under `scalene run -m pytest` and exit.

    Rebuilds the original pytest command line from ``sys.argv`` (dropping the
    Scalene-only flags, which `scalene run` wouldn't understand) and runs it as
    a child so libscalene is preloaded for memory/GPU tracking.
    """
    outfile = config.getoption("--scalene-outfile") or _DEFAULT_OUTFILE

    # Only `scalene run` options go here. Output/view options like
    # --no-browser/--cli/--json are NOT valid for `run`; the profile is
    # written to JSON via -o and viewed later with `scalene view`.
    scalene_run_args: list[str] = ["-o", str(outfile)]
    if config.getoption("--scalene-memory"):
        scalene_run_args.append("--memory")
    if config.getoption("--scalene-gpu"):
        scalene_run_args.append("--gpu")
    extra = config.getoption("--scalene-args")
    if extra:
        import shlex

        scalene_run_args.extend(shlex.split(str(extra)))

    # Strip the plugin's own flags, then re-add a bare `--scalene` so the
    # child's plugin engages in external mode (detects it's under `scalene
    # run`, repoints the program path to the test rootdir, and lets scalene
    # run write the profile). The re-exec guard env var stops the child from
    # re-execing again. `-p scalene.pytest_scalene`, if the user passed it, is
    # preserved by _strip_scalene_args so the plugin loads even when it isn't
    # installed as an entry point.
    pytest_args = ["--scalene", *_strip_scalene_args(sys.argv[1:])]

    # The target module goes *after* `---`: `scalene run <opts> --- -m pytest <args>`.
    cmd = [
        sys.executable,
        "-m",
        "scalene",
        "run",
        *scalene_run_args,
        "---",
        "-m",
        "pytest",
        *pytest_args,
    ]

    env = dict(os.environ)
    env[_REEXEC_GUARD] = "1"

    sys.stderr.write(
        "Scalene: re-running pytest under `scalene run` for "
        "memory/GPU profiling...\n"
    )
    sys.stderr.flush()

    # execve replaces this process, so the child IS the test run and its exit
    # status is what the shell/IDE sees. Fall back to a subprocess if execve
    # isn't usable.
    try:
        os.execve(sys.executable, cmd, env)
    except OSError:
        import subprocess

        result = subprocess.run(cmd, env=env)
        sys.exit(result.returncode)


def _strip_scalene_args(argv: list[str]) -> list[str]:
    """Remove the plugin's own options from a pytest argv before re-exec.

    `scalene run -m pytest` would choke on `--scalene*` flags because they are
    pytest options that only exist once this plugin is loaded, not scalene
    options. We forward everything else verbatim.
    """
    value_opts = {"--scalene-outfile", "--scalene-args"}
    flag_opts = {"--scalene", "--scalene-memory", "--scalene-gpu"}
    all_opts = value_opts | flag_opts

    cleaned: list[str] = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg in value_opts:
            skip_next = True  # also drop the following value token
            continue
        if arg in flag_opts:
            continue
        # Handle "--opt=value" forms.
        if any(arg.startswith(opt + "=") for opt in all_opts):
            continue
        cleaned.append(arg)
    return cleaned


class ScalenePlugin:
    """Drives Scalene's profiler over a pytest session.

    Holds no profiling data of its own - it starts and stops the global
    :class:`scalene.scalene_profiler.Scalene` profiler at session and (when
    tests are marked) per-test boundaries.
    """

    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self._scalene: Any = None
        # Whether sampling is currently on.
        self._enabled = False
        # True if the session contains at least one @pytest.mark.scalene test,
        # in which case we profile only marked tests.
        self._selective = False
        # True when Scalene was already initialized before we touched it, i.e.
        # we are running under `scalene run -m pytest` and it owns output.
        self._external = False

    # -- setup -------------------------------------------------------------

    def _ensure_initialized(self) -> bool:
        """Set up Scalene for in-process profiling if it isn't already.

        Returns False if Scalene can't be loaded, so the plugin degrades to a
        no-op rather than breaking the test run.
        """
        if self._scalene is not None:
            return True
        try:
            from scalene import scalene_profiler
            from scalene.scalene_arguments import ScaleneArguments
        except Exception as exc:  # pragma: no cover - defensive
            sys.stderr.write(f"Scalene: could not load profiler: {exc}\n")
            return False

        scalene = scalene_profiler.Scalene

        if scalene.get_initialized():
            # Already running under `scalene run -m pytest`: the profiler is
            # configured and already sampling. We only steer start/stop around
            # marked tests; we must not reconfigure it or write the profile
            # (scalene run does that on exit).
            #
            # One correction we *do* make: scalene run sets its program path to
            # the entrypoint's directory, which here is pytest's location in
            # site-packages - so none of the user's tests would be traced and
            # the profile comes back empty (exactly what the issue reporters
            # worked around with --profile-all). Repoint it at the pytest
            # rootdir so the test files are profiled out of the box. Any
            # --profile-all / --profile-only / --profile-exclude filters the
            # user passed to `scalene run` still apply on top of this.
            self._external = True
            self._scalene = scalene
            self._enabled = True
            with contextlib.suppress(Exception):
                scalene.set_program_path(str(self.config.rootpath))
            return True

        # In-process setup: CPU-only (memory needs preload, handled by re-exec).
        outfile = self.config.getoption("--scalene-outfile") or _DEFAULT_OUTFILE
        args = ScaleneArguments(
            cpu=True,
            gpu=False,
            memory=False,
            json=True,
            cli=False,
            web=False,
            no_browser=True,
            outfile=os.path.abspath(os.path.expanduser(str(outfile))),
        )
        try:
            scalene.set_initialized()
            scalene(args)
            scalene.set_program_path(str(self.config.rootpath))
        except Exception as exc:  # pragma: no cover - defensive
            sys.stderr.write(f"Scalene: failed to initialize profiler: {exc}\n")
            return False
        self._scalene = scalene
        return True

    @staticmethod
    def _is_marked(item: pytest.Item) -> bool:
        return item.get_closest_marker("scalene") is not None

    # -- pytest hooks ------------------------------------------------------

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        # Start profiling here so whole-session mode also covers collection.
        # If collection turns out to be selective (some test is marked),
        # pytest_collection_modifyitems suspends sampling again before any
        # test body runs.
        if not self._ensure_initialized():
            return
        self._resume()

    def pytest_collection_modifyitems(
        self, items: list[pytest.Item]
    ) -> None:
        """Switch to per-test profiling when any test carries @pytest.mark.scalene."""
        if self._scalene is None:
            return
        self._selective = any(self._is_marked(item) for item in items)
        if self._selective:
            # Only marked tests should be profiled: stop sampling now and let
            # pytest_runtest_call resume around each marked test.
            self._suspend()

    def pytest_runtest_call(self, item: pytest.Item) -> Generator[None, None, None]:
        """Gate per-test profiling for the selective (marked) case."""
        # Wrapped as a hookwrapper below, so this yields once around the call.
        if self._selective and self._scalene is not None and self._is_marked(item):
            self._resume()
            try:
                yield
            finally:
                self._suspend()
        else:
            yield

    def pytest_sessionfinish(
        self, session: pytest.Session, exitstatus: int
    ) -> None:
        if self._scalene is None:
            return
        self._suspend()
        # When `scalene run` owns the profiler, it writes the profile on exit.
        if self._external:
            return
        try:
            self._scalene.output_profile(sys.argv)
        except Exception as exc:  # pragma: no cover - defensive
            sys.stderr.write(f"Scalene: failed to write profile: {exc}\n")

    # -- start/stop helpers ------------------------------------------------

    def _resume(self) -> None:
        if self._scalene is None or self._enabled:
            return
        try:
            self._scalene.start()
            self._enabled = True
        except SystemExit:
            # start() exits if not initialized; we guard against that, but be
            # safe and disable ourselves rather than tearing down the session.
            self._scalene = None
        except Exception as exc:  # pragma: no cover - defensive
            sys.stderr.write(f"Scalene: failed to start profiling: {exc}\n")
            self._scalene = None

    def _suspend(self) -> None:
        if self._scalene is None or not self._enabled:
            return
        with contextlib.suppress(Exception):  # pragma: no cover - defensive
            self._scalene.stop()
        self._enabled = False


# Apply hookwrapper semantics to pytest_runtest_call at import time, so the
# generator above is treated as a wrapper (yielding once around the test call).
with contextlib.suppress(Exception):  # only when pytest is installed
    import pytest as _pytest

    ScalenePlugin.pytest_runtest_call = _pytest.hookimpl(  # type: ignore[method-assign]
        hookwrapper=True
    )(ScalenePlugin.pytest_runtest_call)
