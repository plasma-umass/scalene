"""Tests for scripts/update_models.mjs, which the scheduled update-models
workflow runs to replace curated AI models that providers stop listing.

The provider lists here are made up; the script's network code isn't run.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import pytest
from test_model_registry import assert_registry_consistent

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "update_models.mjs"
REGISTRY = ROOT / "scalene" / "scalene-gui" / "models.ts"

_NODE_SCRIPT = r"""
import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
const [scriptUrl, registryUrl, casesJson, outPath] = process.argv.slice(1);
const script = await import(scriptUrl);
const models = await import(registryUrl);
const source = readFileSync(new URL(registryUrl), "utf8");
const results = [];
for (const c of JSON.parse(casesJson)) {
  const plan = script.planProvider(c.provider, models.MODEL_REGISTRY[c.provider], c.live, models);
  const rewritten = script.applyChanges(source, plan.changes, "2030-01-01");
  // Load the rewritten registry to check it still parses and is consistent.
  writeFileSync(outPath, rewritten);
  const after = await import(pathToFileURL(outPath).href + "?" + results.length);
  results.push({ plan, registry: after.MODEL_REGISTRY, retired: after.RETIRED_MODELS,
                 unchanged: rewritten === source });
}
console.log(JSON.stringify(results));
"""


def _ids(
    provider: str, drop: Sequence[str] = (), add: Sequence[Tuple[str, str]] = ()
) -> List[Dict[str, str]]:
    """The current curated list for a provider, as a provider would list it."""
    out = subprocess.run(
        [
            shutil.which("node") or "node",
            "--experimental-strip-types",
            "--no-warnings",
            "--input-type=module",
            "-e",
            "const m = await import(process.argv[1]);"
            "console.log(JSON.stringify(m.MODEL_REGISTRY[process.argv[2]].models.map(x => x.id)))",
            REGISTRY.as_uri(),
            provider,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    ids = [i for i in json.loads(out.stdout) if i not in drop]
    return [{"id": i} for i in ids] + [{"id": i, "name": n} for i, n in add]


def _node_ok() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    out = subprocess.run([node, "--version"], capture_output=True, text=True).stdout
    major, minor = (int(x) for x in out.strip().lstrip("v").split(".")[:2])
    return (major, minor) >= (22, 6)


@pytest.fixture(scope="module")
def run_cases(tmp_path_factory: pytest.TempPathFactory) -> Any:
    if not _node_ok():
        pytest.skip("needs Node.js 22.6+ to run models.ts")
    out_path = tmp_path_factory.mktemp("models") / "models.ts"

    def run(cases: list) -> list:
        result = subprocess.run(
            [
                shutil.which("node") or "node",
                "--experimental-strip-types",
                "--no-warnings",
                "--input-type=module",
                "-e",
                _NODE_SCRIPT,
                SCRIPT.as_uri(),
                REGISTRY.as_uri(),
                json.dumps(cases),
                str(out_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    return run


def _assert_consistent(result: Dict[str, Any]) -> None:
    assert_registry_consistent(result["registry"], result["retired"])


def test_nothing_missing_changes_nothing(run_cases: Any) -> None:
    [result] = run_cases([{"provider": "anthropic", "live": _ids("anthropic")}])
    assert result["plan"]["changes"] == []
    assert result["unchanged"]


def test_retired_default_moves_to_successor(run_cases: Any) -> None:
    live = _ids(
        "anthropic",
        drop=["claude-sonnet-5-5"],
        add=[("claude-sonnet-6", "Claude Sonnet 6"), ("claude-sonnet-6-20300101", "x")],
    )
    [result] = run_cases([{"provider": "anthropic", "live": live}])
    assert result["plan"]["changes"] == [
        {
            "provider": "anthropic",
            "from": "claude-sonnet-5-5",
            "to": "claude-sonnet-6",  # the alias, not the dated snapshot
            "label": "Claude Sonnet 6",
        }
    ]
    anthropic = result["registry"]["anthropic"]
    assert anthropic["defaultModel"] == "claude-sonnet-6"
    assert anthropic["models"][0] == {
        "id": "claude-sonnet-6",
        "label": "Claude Sonnet 6",
    }
    assert result["retired"]["anthropic"]["claude-sonnet-5-5"] == "claude-sonnet-6"
    # Older retirements that pointed at 5.5 now skip straight to 6.
    assert (
        result["retired"]["anthropic"]["claude-sonnet-4-5-20250929"]
        == "claude-sonnet-6"
    )
    _assert_consistent(result)


def test_retired_model_merges_into_curated_successor(run_cases: Any) -> None:
    # Bedrock drops Sonnet 5.5; Sonnet 4.6 is already curated, so the 5.5
    # entry is removed rather than duplicated.
    live = _ids("amazon", drop=["global.anthropic.claude-sonnet-5-5"])
    [result] = run_cases([{"provider": "amazon", "live": live}])
    amazon = result["registry"]["amazon"]
    assert amazon["defaultModel"] == "global.anthropic.claude-sonnet-4-6"
    assert "global.anthropic.claude-sonnet-5-5" not in [
        m["id"] for m in amazon["models"]
    ]
    _assert_consistent(result)


def test_newer_models_are_only_reported(run_cases: Any) -> None:
    live = _ids("anthropic", add=[("claude-opus-6", "Claude Opus 6")])
    [result] = run_cases([{"provider": "anthropic", "live": live}])
    assert result["plan"]["changes"] == []
    assert result["plan"]["newer"] == ["claude-opus-6"]
    assert result["unchanged"]


def test_mass_disappearance_is_not_trusted(run_cases: Any) -> None:
    live = [{"id": "gemini-pro-latest"}, {"id": "something-else"}]
    [result] = run_cases([{"provider": "gemini", "live": live}])
    assert result["plan"]["changes"] == []
    assert result["plan"]["skipped"]
    assert result["unchanged"]


def test_shared_name_retires_only_for_its_provider(run_cases: Any) -> None:
    # OpenAI drops gpt-4.1; Azure, which also offers a gpt-4.1, is untouched.
    live = _ids("openai", drop=["gpt-4.1"])
    [result] = run_cases([{"provider": "openai", "live": live}])
    assert "gpt-4.1" in result["retired"]["openai"]
    assert "gpt-4.1" not in result["retired"]["azure"]
    assert "gpt-4.1" in [m["id"] for m in result["registry"]["azure"]["models"]]
    _assert_consistent(result)
