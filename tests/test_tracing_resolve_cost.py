"""should_trace() must not resolve every sysconfig path on each new file.

On Windows, should_trace() runs on the CPU sampling thread, and each
Path.resolve() there has to win the GIL back from the busy main thread.
Resolving ~80 sysconfig directories for every newly seen file made the
first sample take longer than a short program's whole run, so Scalene
recorded no CPU time at all ("did not run for long enough to profile").
The directories are now resolved once, when ScaleneTracing is created.
"""

import os
import pathlib
from unittest import mock

from scalene.scalene_arguments import ScaleneArguments
from scalene.scalene_statistics import Filename
from scalene.scalene_tracing import ScaleneTracing


def test_should_trace_miss_resolves_only_a_few_paths(tmp_path):
    prog = tmp_path / "prog.py"
    prog.write_text("x = 1\n")
    other = tmp_path / "other.py"
    other.write_text("y = 2\n")

    tracing = ScaleneTracing(
        ScaleneArguments(), os.path.dirname(os.path.abspath(__file__)), Filename(str(prog))
    )
    tracing.set_program_path(Filename(str(tmp_path)))

    real_resolve = pathlib.Path.resolve
    calls = []

    def counting_resolve(self, *args, **kwargs):
        calls.append(str(self))
        return real_resolve(self, *args, **kwargs)

    with mock.patch.object(pathlib.Path, "resolve", counting_resolve):
        assert tracing.should_trace(Filename(str(other)), "<module>")

    # The file itself is resolved a handful of times; the library
    # directories and the program path must come from the cache.
    assert len(calls) <= 5, calls


def test_library_files_still_excluded():
    tracing = ScaleneTracing(ScaleneArguments(), "/nonexistent-scalene-base", Filename(""))
    tracing.set_program_path(Filename(os.path.dirname(os.__file__)))
    # os.py lives in the stdlib directory, which is a sysconfig path.
    assert not tracing.should_trace(Filename(os.__file__), "<module>")
