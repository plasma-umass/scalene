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
    """The TS source must have been rebuilt before this PR is merged."""
    assert BUNDLE_PATH.exists(), f"missing bundle at {BUNDLE_PATH}"
    src = BUNDLE_PATH.read_text(encoding="utf-8")
    assert "renderCombinedStacks" in src, (
        "renderCombinedStacks() missing from bundle — re-run "
        "`npx esbuild scalene-gui.ts --bundle ...` and commit the bundle"
    )
    assert "toggleCombinedStacks" in src, (
        "toggleCombinedStacks() missing from bundle — re-run esbuild"
    )


def test_section_present_when_combined_stacks_populated(tmp_path: pathlib.Path) -> None:
    profile = _build_profile(with_combined_stacks=True)
    html = _render(tmp_path, profile)

    # CSS rules from the template
    assert ".combined-stacks-section" in html
    assert ".flame-segment" in html
    # Bundle JS embedded inline (standalone mode)
    assert "renderCombinedStacks" in html
    assert "toggleCombinedStacks" in html
    # Flame-chart helpers from the bundle
    assert "buildFlameTree" in html
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
