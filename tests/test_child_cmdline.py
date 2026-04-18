"""Regression tests for child-process cmdline propagation (issue #1022).

Scalene wraps `sys.executable` with a shell/batch alias so that any Python
subprocess spawned by the profiled program (pytest-xdist workers,
multiprocessing pools, `subprocess.run([sys.executable, ...])`, etc.) is
itself run under Scalene. The alias embeds the parent's scope-affecting
flags (`--profile-all`, `--profile-only`, `--profile-exclude`,
`--profile-system-libraries`, `--stacks`, `--no-async`) so that children
collect samples under the same rules as the parent.

Before this fix, only `--gpu`/`--memory`/`--cpu-only`/`--program-path` were
forwarded; a child launched with `--profile-all` from the parent would
default to `profile_all=False`, filter out every user-code sample, and
either drop everything silently or print "did not run long enough".
"""

import argparse
import pathlib
import subprocess
import sys
import tempfile
import textwrap

import pytest

from scalene.scalene_profiler import Scalene


def _ns(**kwargs):
    ns = argparse.Namespace(
        cpu=True,
        gpu=False,
        memory=False,
        use_virtual_time=False,
        profile_all=False,
        profile_system_libraries=False,
        stacks=False,
        async_profile=True,
        profile_only="",
        profile_exclude="",
    )
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


# ---------------------------------------------------------------------------
# Unit tests for the cmdline builder
# ---------------------------------------------------------------------------


def test_profile_all_propagated():
    cmdline = Scalene._build_child_cmdline(_ns(profile_all=True), "/tmp", 42)
    assert "--profile-all" in cmdline


def test_profile_all_not_propagated_when_unset():
    cmdline = Scalene._build_child_cmdline(_ns(), "/tmp", 42)
    assert "--profile-all" not in cmdline


def test_profile_scope_filters_propagated():
    cmdline = Scalene._build_child_cmdline(
        _ns(
            profile_only="mypkg,utils",
            profile_exclude="tests",
            profile_system_libraries=True,
            stacks=True,
        ),
        "/tmp",
        42,
    )
    quote = '"' if sys.platform == "win32" else "'"
    assert f"--profile-only={quote}mypkg,utils{quote}" in cmdline
    assert f"--profile-exclude={quote}tests{quote}" in cmdline
    assert "--profile-system-libraries" in cmdline
    assert "--stacks" in cmdline


def test_async_propagation_only_when_disabled():
    # async_profile defaults to True and the run subcommand has no --async
    # default-preserving form to re-enable it, so we only emit --no-async.
    enabled = Scalene._build_child_cmdline(_ns(async_profile=True), "/tmp", 42)
    disabled = Scalene._build_child_cmdline(_ns(async_profile=False), "/tmp", 42)
    assert "--no-async" not in enabled
    assert "--no-async" in disabled


def test_pid_and_separator_always_present():
    cmdline = Scalene._build_child_cmdline(_ns(), "", 12345)
    assert cmdline.rstrip().endswith("--pid=12345 ---")


def test_program_path_quoted():
    cmdline = Scalene._build_child_cmdline(_ns(), "/my/project", 1)
    quote = '"' if sys.platform == "win32" else "'"
    assert f"--program-path={quote}/my/project{quote}" in cmdline


def test_cpu_only_when_cpu_and_no_mem_or_gpu():
    cmdline = Scalene._build_child_cmdline(
        _ns(cpu=True, memory=False, gpu=False), "", 1
    )
    assert "--cpu-only" in cmdline


def test_cpu_only_suppressed_when_memory_or_gpu_on():
    cmdline_mem = Scalene._build_child_cmdline(_ns(cpu=True, memory=True), "", 1)
    cmdline_gpu = Scalene._build_child_cmdline(_ns(cpu=True, gpu=True), "", 1)
    assert "--cpu-only" not in cmdline_mem
    assert "--cpu-only" not in cmdline_gpu


# ---------------------------------------------------------------------------
# Integration test: verify the alias script actually embeds --profile-all.
# This catches regressions in the path from _build_child_cmdline through
# redirect_python into the on-disk alias file.
# ---------------------------------------------------------------------------


_DUMP_ALIAS = textwrap.dedent("""\
    import sys
    print("__ALIAS_START__")
    with open(sys.executable, "r", encoding="utf-8", errors="replace") as f:
        print(f.read())
    print("__ALIAS_END__", flush=True)
""")


def _run_scalene_and_capture_alias(*extra_flags):
    """Run `scalene run ... script.py` where script.py prints its sys.executable
    (the alias) contents, and return the alias body."""
    with tempfile.TemporaryDirectory(prefix="scalene_1022_") as tmp:
        tmp = pathlib.Path(tmp)
        script = tmp / "dump_alias.py"
        script.write_text(_DUMP_ALIAS)
        outfile = tmp / "profile.json"

        cmd = [
            sys.executable,
            "-m",
            "scalene",
            "run",
            "--cpu-only",
            "-o",
            str(outfile),
            *extra_flags,
            str(script),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        out = proc.stdout
        if "__ALIAS_START__" not in out or "__ALIAS_END__" not in out:
            pytest.skip(
                "Scalene bootstrap failed in this environment; "
                f"rc={proc.returncode} stderr={proc.stderr[-400:]}"
            )
        start = out.index("__ALIAS_START__") + len("__ALIAS_START__")
        end = out.index("__ALIAS_END__")
        return out[start:end]


def test_alias_forwards_profile_all():
    """Regression for #1022: the alias must carry --profile-all when the
    parent was invoked with it, so xdist/multiprocessing children keep the
    same profiling scope."""
    alias = _run_scalene_and_capture_alias("--profile-all")
    assert "--profile-all" in alias, f"alias body was: {alias!r}"


def test_alias_omits_profile_all_when_parent_omits_it():
    alias = _run_scalene_and_capture_alias()
    assert "--profile-all" not in alias, f"alias body was: {alias!r}"
