"""Tests for the GUI's AI model registry (scalene/scalene-gui/models.ts).

Providers retire model IDs regularly (#1123). The GUI keeps every model ID in
models.ts so there is one place to update, and recovers at request time from
models that have since been retired. These tests keep it that way.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest

GUI_DIR = Path(__file__).resolve().parent.parent / "scalene" / "scalene-gui"
REGISTRY = GUI_DIR / "models.ts"

# Strings that look like a model ID: claude-*/gemini-* containing a digit or
# "latest", and gpt-<digit>*. Element IDs like "gemini-api-key" don't match.
MODEL_ID_LITERAL = re.compile(
    r"""["'`>](?:[a-z]+\.)*(?:(?:claude|gemini)-[\w.:-]*(?:\d|latest)|gpt-\d)[\w.:-]*["'`<]"""
)


def _gui_sources() -> List[Path]:
    sources = [p for p in GUI_DIR.glob("*.ts") if not p.name.endswith(".d.ts")]
    sources.append(GUI_DIR / "index.html.template")
    return [p for p in sources if p != REGISTRY]


def test_model_ids_only_in_registry() -> None:
    offenders = []
    for path in _gui_sources():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in MODEL_ID_LITERAL.finditer(line):
                offenders.append(f"{path.name}:{lineno}: {match.group(0)}")
    assert not offenders, (
        "Model IDs belong in scalene-gui/models.ts so that retiring a model "
        "means editing one file:\n" + "\n".join(offenders)
    )


def test_pattern_catches_model_ids() -> None:
    # Guard against the check above passing because the pattern rotted.
    for literal in [
        '"claude-sonnet-4-5-20250929"',
        "'claude-sonnet-5-5'",
        '"us.anthropic.claude-opus-4-5-20251101-v1:0"',
        '"gemini-2.0-flash"',
        '"gemini-flash-latest"',
        '"gpt-4"',
        '<option value="x">gpt-5.2<',
    ]:
        assert MODEL_ID_LITERAL.search(literal), literal
    for literal in ['"gemini-api-key"', '"claude-fields"', 'includes("gpt")']:
        assert not MODEL_ID_LITERAL.search(literal), literal


# --- Behavior of models.ts, run under Node ------------------------------------

_NODE_SCRIPT = r"""
const m = await import(process.argv[1]);
const pick = (args) => m.pickReplacement(...args);
const out = {
  registry: m.MODEL_REGISTRY,
  retired: m.RETIRED_MODELS,
  families: Object.fromEntries(JSON.parse(process.argv[2]).map((id) => [id, m.modelFamily(id)])),
  picks: JSON.parse(process.argv[3]).map(pick),
  ranks: JSON.parse(process.argv[4]).map((args) => m.rankReplacements(...args)),
};
console.log(JSON.stringify(out));
"""

_FAMILY_CASES = {
    "claude-sonnet-4-5-20250929": "claude-sonnet",
    "claude-sonnet-5-5": "claude-sonnet",
    "claude-opus-4-5-20251124": "claude-opus",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": "claude-sonnet",
    "anthropic.claude-haiku-5-5": "claude-haiku",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": "claude-haiku",
    "global.anthropic.claude-opus-4-6-v1": "claude-opus",
    "gemini-2.0-flash": "gemini-flash",
    "gemini-flash-latest": "gemini-flash",
    "gemini-2.5-flash-lite": "gemini-flash-lite",
    "gpt-4": "gpt",
    "gpt-5.2-pro": "gpt-pro",
}

# (failed model, models the provider lists, registry default) -> replacement
_PICK_CASES = [
    # Retired Sonnet: newest Sonnet wins, regardless of list order.
    (
        [
            "claude-sonnet-4-5-20250929",
            [
                "claude-haiku-5-5",
                "claude-sonnet-4-6",
                "claude-sonnet-5-5",
                "claude-opus-5-5",
            ],
            "claude-sonnet-5-5",
        ],
        "claude-sonnet-5-5",
    ),
    # Gemini: a -latest alias beats numbered versions.
    (
        [
            "gemini-2.0-flash",
            ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-pro"],
            "gemini-pro-latest",
        ],
        "gemini-flash-latest",
    ),
    # No same-family model listed: fall back to the default if it is listed...
    (
        ["claude-instant-1", ["claude-sonnet-5-5"], "claude-sonnet-5-5"],
        "claude-sonnet-5-5",
    ),
    # ...but not if the provider says it doesn't exist.
    (["claude-instant-1", ["claude-opus-5-5"], "claude-sonnet-5-5"], None),
    # No list available (e.g. Bedrock): use the default.
    (
        [
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            [],
            "anthropic.claude-sonnet-5-5",
        ],
        "anthropic.claude-sonnet-5-5",
    ),
    # Never "replace" a model with itself.
    (["claude-sonnet-5-5", [], "claude-sonnet-5-5"], None),
    (["claude-sonnet-5-5", ["claude-sonnet-5-5"], "claude-sonnet-5-5"], None),
]


_BEDROCK = [
    "global.anthropic.claude-sonnet-5-5",
    "global.anthropic.claude-opus-5-5",
    "global.anthropic.claude-haiku-5-5",
    "global.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-opus-4-6-v1",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
]

# (failed model, available, default) -> replacements to try, best first
_RANK_CASES = [
    # An account without access to the 5.5 default falls back within the
    # family (seen on a real AWS account, which can call 4.6 but not 5.5).
    (
        [
            "global.anthropic.claude-sonnet-5-5",
            _BEDROCK,
            "global.anthropic.claude-sonnet-5-5",
        ],
        ["global.anthropic.claude-sonnet-4-6"],
    ),
    # A retired Sonnet tries the newest Sonnet first, then older ones.
    (
        [
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            _BEDROCK,
            "global.anthropic.claude-sonnet-5-5",
        ],
        ["global.anthropic.claude-sonnet-5-5", "global.anthropic.claude-sonnet-4-6"],
    ),
    # Different family: the default comes after same-family candidates.
    (
        [
            "global.anthropic.claude-opus-5-5",
            _BEDROCK,
            "global.anthropic.claude-sonnet-5-5",
        ],
        ["global.anthropic.claude-opus-4-6-v1", "global.anthropic.claude-sonnet-5-5"],
    ),
]


def _node_supports_type_stripping(node: str) -> bool:
    try:
        out = subprocess.run(
            [node, "--version"], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return False
    major, minor = (int(x) for x in out.strip().lstrip("v").split(".")[:2])
    return (major, minor) >= (22, 6)


@pytest.fixture(scope="module")
def registry_eval() -> Dict[str, Any]:
    node = shutil.which("node")
    if node is None or not _node_supports_type_stripping(node):
        pytest.skip("needs Node.js 22.6+ to run models.ts")
    result = subprocess.run(
        [
            node,
            "--experimental-strip-types",
            "--no-warnings",
            "--input-type=module",
            "-e",
            _NODE_SCRIPT,
            REGISTRY.as_uri(),
            json.dumps(list(_FAMILY_CASES)),
            json.dumps([args for args, _ in _PICK_CASES]),
            json.dumps([args for args, _ in _RANK_CASES]),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_model_family(registry_eval: Dict[str, Any]) -> None:
    assert registry_eval["families"] == _FAMILY_CASES


def test_pick_replacement(registry_eval: Dict[str, Any]) -> None:
    assert registry_eval["picks"] == [expected for _, expected in _PICK_CASES]


def test_rank_replacements(registry_eval: Dict[str, Any]) -> None:
    assert registry_eval["ranks"] == [expected for _, expected in _RANK_CASES]


def test_registry_is_consistent(registry_eval: Dict[str, Any]) -> None:
    assert_registry_consistent(registry_eval["registry"], registry_eval["retired"])


def assert_registry_consistent(
    registry: Dict[str, Any], retired: Dict[str, Dict[str, str]]
) -> None:
    assert set(retired) == set(registry)
    for name, provider in registry.items():
        ids = [m["id"] for m in provider["models"]]
        assert provider["defaultModel"] in ids, name
        assert len(ids) == len(set(ids)), name
        # A provider's retired IDs must not be offered by that provider, and
        # must map to something it offers.
        assert not set(ids) & set(retired[name]), name
        for old, new in retired[name].items():
            assert new in ids, f"{name}: {old} -> {new}"


_RESTORE_SCRIPT = r"""
// Minimal DOM: just what restoreModelSelection touches.
globalThis.document = { createElement: () => ({ value: "", textContent: "" }) };
const m = await import(process.argv[1]);
const select = (id, values) => {
  const options = values.map((value) => ({ value }));
  return { id, options, value: "", appendChild: (o) => options.push(o) };
};
const restore = (provider, saved) => {
  const { selectId, models } = m.MODEL_REGISTRY[provider];
  return m.restoreModelSelection(select(selectId, models.map((x) => x.id)), saved);
};
console.log(JSON.stringify([
  restore("openai", "o4-mini"),
  restore("azure", "o4-mini"),
  restore("anthropic", "claude-sonnet-4-5-20250929"),
  restore("anthropic", "my-custom-model"),
]));
"""


def test_retirements_are_per_provider() -> None:
    # Providers share model names, so a retirement on one must not rewrite
    # another's saved choice (an Azure deployment can still be named o4-mini).
    node = shutil.which("node")
    if node is None or not _node_supports_type_stripping(node):
        pytest.skip("needs Node.js 22.6+ to run models.ts")
    result = subprocess.run(
        [
            node,
            "--experimental-strip-types",
            "--no-warnings",
            "--input-type=module",
            "-e",
            _RESTORE_SCRIPT,
            REGISTRY.as_uri(),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        "gpt-5.2",
        "o4-mini",
        "claude-sonnet-5-5",
        "my-custom-model",
    ]
