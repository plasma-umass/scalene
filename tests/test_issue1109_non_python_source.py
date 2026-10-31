"""Regression tests for #1109: profiling code whose filename is not Python.

Jinja2 (and other template engines) compile generated Python with the
*template's* path as the filename, so render functions have
co_filename == "templates/page.html". Scalene sampled those frames, then
tried to ast.parse() the HTML when emitting JSON, and the SyntaxError
aborted the whole profile.
"""

from pathlib import Path

from scalene.scalene_arguments import ScaleneArguments
from scalene.scalene_json import ScaleneJSON
from scalene.scalene_statistics import Filename, LineNumber, ScaleneStatistics
from scalene.scalene_tracing import ScaleneTracing

TEMPLATE = """<html><head><style>
  .x {
      width: 30rem;
  }
</style></head>
<body>{% for i in items %}<p>{{ i }}</p>{% endfor %}</body></html>
"""


def _stats_for(*fnames: str) -> ScaleneStatistics:
    stats = ScaleneStatistics()
    for f in fnames:
        stats.cpu_stats.cpu_samples_python[Filename(f)][LineNumber(1)] = 1.0
        stats.cpu_stats.cpu_samples[Filename(f)] = 1.0
        stats.cpu_stats.total_cpu_samples += 1.0
    stats.elapsed_time = 1.0
    return stats


def test_output_profiles_skips_non_python_file(tmp_path: Path) -> None:
    html = tmp_path / "page.html"
    html.write_text(TEMPLATE)
    prog = tmp_path / "prog.py"
    prog.write_text("x = 1\n")
    stats = _stats_for(str(html), str(prog))
    result = ScaleneJSON().output_profiles(
        Filename(str(prog)),
        stats,
        0,
        lambda f, l: True,
        tmp_path / "no-children",
        Filename(str(prog)),
        Filename(str(prog)),
        [],
        profile_memory=False,
        reduced_profile=False,
    )
    files = result["files"]
    assert not any(f.endswith("page.html") for f in files)
    assert any(f.endswith("prog.py") for f in files)


def _tracing(tmp_path: Path) -> ScaleneTracing:
    return ScaleneTracing(
        ScaleneArguments(), "/nonexistent-profiler-base", Filename(str(tmp_path))
    )


def test_should_trace_rejects_template(tmp_path: Path) -> None:
    html = tmp_path / "page.html"
    html.write_text(TEMPLATE)
    assert not _tracing(tmp_path).should_trace(Filename(str(html)), "root")


def test_should_trace_accepts_python_with_odd_suffix(tmp_path: Path) -> None:
    script = tmp_path / "tool.cgi"
    script.write_text("def main():\n    return 1\n")
    assert _tracing(tmp_path).should_trace(Filename(str(script)), "main")


def test_should_trace_accepts_py_and_extensionless(tmp_path: Path) -> None:
    for name in ("prog.py", "script"):
        p = tmp_path / name
        p.write_text("x = 1\n")
        assert _tracing(tmp_path).should_trace(Filename(str(p)), "<module>")
