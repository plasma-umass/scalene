"""GUI integration tests for the combined_stacks viewer (PR follow-up to #1035).

These are pipeline / asset-bundling smoke tests, not browser tests. They
verify that:

  - The TypeScript bundle on disk contains the new render code.
  - generate_html() with --standalone embeds that bundle inline so the
    section is reachable from a self-contained HTML file.
  - The inline CSS rules from the Jinja2 template are present.
  - Profile JSON containing combined_stacks reaches the rendered HTML.
  - Profile JSON without combined_stacks (older profiles) still renders
    cleanly (no crash, no leftover marker text).

We deliberately do NOT spin up Selenium or a headless browser here:
adding chromedriver to CI is out of scope for this PR. The end-to-end
"does the section actually expand on click" check is manual.
"""

import json
import pathlib
from typing import Any, Dict

import pytest

from scalene.scalene_statistics import Filename
from scalene.scalene_utility import generate_html

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BUNDLE_PATH = REPO_ROOT / "scalene" / "scalene-gui" / "scalene-gui-bundle.js"
TS_SOURCE_PATH = REPO_ROOT / "scalene" / "scalene-gui" / "scalene-gui.ts"


def _build_profile(*, with_combined_stacks: bool) -> Dict[str, Any]:
    """Build a minimal but schema-shaped profile dict for HTML rendering."""
    base: Dict[str, Any] = {
        "alloc_samples": 0,
        "args": [],
        "async_profile": False,
        "elapsed_time_sec": 1.0,
        "start_time_absolute": 0.0,
        "start_time_perf": 0.0,
        "entrypoint_dir": "/tmp",
        "filename": "demo.py",
        "files": {
            "demo.py": {
                "functions": [],
                "imports": [],
                "leaks": {},
                "lines": [],
                "percent_cpu_time": 100.0,
            }
        },
        "gpu": False,
        "gpu_device": "",
        "growth_rate": 0.0,
        "max_footprint_fname": None,
        "max_footprint_lineno": None,
        "max_footprint_mb": 0.0,
        "max_footprint_python_fraction": 0.0,
        "memory": False,
        "program": "demo.py",
        "samples": [],
        "stacks": [],
        "native_stacks": [],
    }
    if with_combined_stacks:
        base["combined_stacks"] = [
            [
                [
                    {
                        "kind": "py",
                        "display_name": "user_outer_function",
                        "filename_or_module": "/app/work.py",
                        "line": 10,
                        "ip": None,
                        "offset": None,
                    },
                    {
                        "kind": "py",
                        "display_name": "user_inner_function",
                        "filename_or_module": "/app/work.py",
                        "line": 42,
                        "ip": None,
                        "offset": None,
                    },
                    {
                        "kind": "native",
                        "display_name": "marker_native_symbol",
                        "filename_or_module": "/lib/libmarker.dylib",
                        "line": None,
                        "ip": 140735000000,
                        "offset": 32,
                    },
                ],
                7,
            ]
        ]
    return base


def _render(tmp_path: pathlib.Path, profile: Dict[str, Any]) -> str:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile))
    html_path = tmp_path / "out.html"
    generate_html(Filename(str(profile_path)), Filename(str(html_path)), standalone=True)
    assert html_path.exists(), "generate_html did not write output"
    return html_path.read_text(encoding="utf-8")


def test_bundle_contains_new_render_helpers() -> None:
    """The TS source must have been rebuilt before this PR is merged.

    Only checks string literals that survive minification: function names
    used in onClick handlers (which become string literals) and CSS class
    names. Internal function names like renderCombinedStacks are mangled
    by esbuild --minify and are asserted via the TypeScript source tests.
    """
    assert BUNDLE_PATH.exists(), f"missing bundle at {BUNDLE_PATH}"
    src = BUNDLE_PATH.read_text(encoding="utf-8")
    for sym in (
        # Function names used in onClick handlers survive as string literals
        "toggleCombinedStacks",
        "toggleCombinedStacksTimeline",
        "toggleMemoryStacks",
        # DOM class-name string literals (preserved — they're data, not code)
        "timeline-axis",
        "timeline-gridlines",
        "memory-axis",
        "memory-gridlines",
    ):
        assert sym in src, (
            f"expected {sym!r} in bundle — re-run "
            f"`npm --prefix scalene/scalene-gui run build` and commit"
        )


def test_ts_source_contains_timeline_axis_helpers() -> None:
    """The timeline view ships a time-axis ruler with gridlines. The axis
    helpers (pickNiceTickInterval / renderTimelineAxis /
    renderTimelineGridlines) are internal to the bundle; we assert their
    existence at the TS source level so the check isn't sensitive to
    whether the bundle was built with minification."""
    assert TS_SOURCE_PATH.exists(), f"missing TS source at {TS_SOURCE_PATH}"
    src = TS_SOURCE_PATH.read_text(encoding="utf-8")
    for sym in (
        "pickNiceTickInterval",
        "formatTimelineTickLabel",
        "renderTimelineAxis",
        "renderTimelineGridlines",
    ):
        assert sym in src, f"expected {sym!r} in TS source"


def test_ts_source_contains_memory_axis_helpers() -> None:
    """Same, for the memory flame chart's MB-axis helpers."""
    assert TS_SOURCE_PATH.exists(), f"missing TS source at {TS_SOURCE_PATH}"
    src = TS_SOURCE_PATH.read_text(encoding="utf-8")
    for sym in (
        "pickNiceTickInterval",  # shared with the timeline axis
        "formatMemoryTickLabel",
        "renderMemoryAxis",
        "renderMemoryGridlines",
    ):
        assert sym in src, f"expected {sym!r} in TS source"


def test_timeline_tooltips_use_source_lookup() -> None:
    """Timeline tooltips (on individual frame rectangles in the stitched
    stacks timeline) must pull their source-line text from
    ``profile.files`` via the same ``makeFileSourceLookup`` helper the
    flame-chart tooltips use. This guards against a regression where
    ``renderCombinedStacksTimeline`` silently stops passing the lookup
    to ``renderTimelineFrames`` and tooltips lose their source-line
    tail.

    Scans the TypeScript source rather than the compiled bundle because
    minification renames local identifiers and rewrites the function
    declaration form (``function foo(...) {...}`` → an aliased arrow
    assignment with ``__name(..., "foo")`` runtime tagging). The code-
    flow wiring we want to assert lives at the source level; the bundle
    merely reflects it.
    """
    assert TS_SOURCE_PATH.exists(), f"missing TS source at {TS_SOURCE_PATH}"
    src = TS_SOURCE_PATH.read_text(encoding="utf-8")
    # The helper has to exist; the renderer has to call it; and the
    # timeline renderer has to receive it.
    assert "makeFileSourceLookup" in src
    assert "renderTimelineFrames" in src
    marker = "renderCombinedStacksTimeline"
    start = src.find(f"function {marker}")
    assert start != -1, f"{marker!r} definition not found in TS source"
    # Cap the span at the next top-level function definition after
    # this one so we don't accidentally match an unrelated later call.
    end = src.find("\nfunction ", start + len(marker) + 10)
    if end == -1:
        end = src.find("\nexport function ", start + len(marker) + 10)
    body = src[start:end] if end > start else src[start:]
    assert "makeFileSourceLookup" in body, (
        "renderCombinedStacksTimeline no longer constructs the file "
        "source lookup — timeline tooltips will stop showing source "
        "lines. Re-thread makeFileSourceLookup into renderTimelineFrames."
    )
    assert "renderTimelineFrames" in body, (
        "renderCombinedStacksTimeline no longer calls renderTimelineFrames"
    )


def test_timeline_tooltip_source_line_reaches_embedded_profile(
    tmp_path: pathlib.Path,
) -> None:
    """End-to-end-ish: a profile that references a source line via
    combined_stacks_timeline must carry the corresponding source text
    through to the rendered standalone HTML so the timeline tooltip
    can read it at runtime. We don't evaluate the JS tooltip code
    here; we just verify the data the runtime needs is reachable.

    This complements test_bundle_timeline_tooltips_use_source_lookup
    (which asserts the code path) by asserting the data path."""
    marker = "leaf_user_code_line_abc123"
    profile = _build_profile(with_combined_stacks=True)
    # Override the files section to include a known source line at
    # lineno 10, matching the first frame's line in _build_profile.
    profile["files"]["demo.py"]["lines"] = [
        # pad to reach lineno 10 so lines[9] == our marker line
        *(
            {
                "lineno": i,
                "line": f"# filler {i}",
                "n_cpu_percent_python": 0,
                "n_cpu_percent_c": 0,
                "n_sys_percent": 0,
                "n_core_utilization": 0,
                "n_peak_mb": 0,
                "n_avg_mb": 0,
                "n_python_fraction": 0,
                "n_copy_mb_s": 0,
                "n_malloc_mb": 0,
                "n_mallocs": 0,
                "n_growth_mb": 0,
                "n_usage_fraction": 0,
                "n_gpu_percent": 0,
                "n_gpu_avg_memory_mb": 0,
                "n_gpu_peak_memory_mb": 0,
                "memory_samples": [],
            }
            for i in range(1, 10)
        ),
        {
            "lineno": 10,
            "line": marker,
            "n_cpu_percent_python": 0,
            "n_cpu_percent_c": 0,
            "n_sys_percent": 0,
            "n_core_utilization": 0,
            "n_peak_mb": 0,
            "n_avg_mb": 0,
            "n_python_fraction": 0,
            "n_copy_mb_s": 0,
            "n_malloc_mb": 0,
            "n_mallocs": 0,
            "n_growth_mb": 0,
            "n_usage_fraction": 0,
            "n_gpu_percent": 0,
            "n_gpu_avg_memory_mb": 0,
            "n_gpu_peak_memory_mb": 0,
            "memory_samples": [],
        },
    ]
    # Point the combined_stacks frame at demo.py:10 so makeFileSourceLookup
    # will return the marker line at render time.
    profile["combined_stacks"][0][0][0]["filename_or_module"] = "demo.py"
    profile["combined_stacks"][0][0][0]["line"] = 10
    profile["combined_stacks_timeline"] = [
        {"t_sec": 0.0, "stack_index": 0, "count": 1}
    ]
    profile["elapsed_time_sec"] = 1.0

    html = _render(tmp_path, profile)
    assert marker in html, (
        "the source text at demo.py:10 must be embedded somewhere in the "
        "standalone HTML (via the files.lines section) so the runtime "
        "timeline tooltip can look it up via makeFileSourceLookup"
    )


def test_static_html_has_no_experimental_badge(tmp_path: pathlib.Path) -> None:
    """The timeline view is no longer labeled as "experimental".
    Regression guard — future styling changes must not re-introduce a
    warning-colored badge around it."""
    profile = _build_profile(with_combined_stacks=True)
    profile["combined_stacks_timeline"] = [
        {"t_sec": 0.0, "stack_index": 0, "count": 1},
    ]
    profile["elapsed_time_sec"] = 1.0
    html = _render(tmp_path, profile)
    # Case-insensitive substring match on both the text and the Bootstrap
    # badge class that previously wrapped it.
    lowered = html.lower()
    assert "experimental" not in lowered, (
        "'experimental' text leaked into rendered timeline HTML"
    )
    assert "bg-warning text-dark" not in html, (
        "the experimental warning-colored badge must not be rendered"
    )


def test_section_present_when_combined_stacks_populated(tmp_path: pathlib.Path) -> None:
    profile = _build_profile(with_combined_stacks=True)
    html = _render(tmp_path, profile)

    # CSS rules from the template
    assert ".combined-stacks-section" in html
    assert ".flame-segment" in html
    # Function names used in onClick handlers survive minification as strings
    assert "toggleCombinedStacks" in html
    # The profile JSON literal includes our combined_stacks data
    assert "marker_native_symbol" in html
    assert "user_outer_function" in html
    assert "user_inner_function" in html


def test_section_absent_marker_text_when_combined_stacks_missing(
    tmp_path: pathlib.Path,
) -> None:
    """Old profiles without combined_stacks must not surface marker text.

    The static HTML still embeds the bundle's render code (it's compiled
    in), but the runtime guard `if (stacks.length === 0) return ""`
    prevents any frame display_names from leaking into the JSON literal —
    so the marker symbol from the populated test cannot appear here.
    """
    profile = _build_profile(with_combined_stacks=False)
    html = _render(tmp_path, profile)

    assert "marker_native_symbol" not in html
    assert "user_inner_function" not in html


def test_standalone_renders_without_crash_on_minimal_profile(
    tmp_path: pathlib.Path,
) -> None:
    """generate_html on a minimal profile (no stacks fields at all) must
    succeed; the new code should never reference combined_stacks
    unconditionally."""
    profile = _build_profile(with_combined_stacks=False)
    # Strip optional fields entirely
    profile.pop("stacks", None)
    profile.pop("native_stacks", None)
    html = _render(tmp_path, profile)
    assert "Scalene" in html
    # CSS still injected (it's static template content)
    assert ".combined-stacks-section" in html


@pytest.mark.parametrize("standalone", [True, False])
def test_css_rule_present_in_both_modes(
    tmp_path: pathlib.Path, standalone: bool
) -> None:
    """The .combined-stacks-section / .flame-segment rules must be in the
    inline <style> block regardless of standalone mode."""
    profile = _build_profile(with_combined_stacks=True)
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile))
    html_path = tmp_path / "out.html"
    generate_html(
        Filename(str(profile_path)), Filename(str(html_path)), standalone=standalone
    )
    html = html_path.read_text(encoding="utf-8")
    assert ".combined-stacks-section" in html
    assert ".flame-segment" in html
