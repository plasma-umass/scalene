from pathlib import Path

import pytest

from scalene.scalene_utility import Filename, generate_html


SENSITIVE_ENVIRONMENT_VARIABLES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_DEFAULT_REGION",
    "AWS_REGION",
)


@pytest.mark.parametrize("standalone", [False, True])
def test_generate_html_does_not_embed_environment_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, standalone: bool
) -> None:
    marker = "SCALENE_TEST_CREDENTIAL_MUST_NOT_APPEAR"
    for variable in SENSITIVE_ENVIRONMENT_VARIABLES:
        monkeypatch.setenv(variable, marker)

    profile = tmp_path / "profile.json"
    output = tmp_path / "profile.html"
    profile.write_text("{}", encoding="utf-8")

    generate_html(Filename(str(profile)), Filename(str(output)), standalone=standalone)

    rendered = output.read_text(encoding="utf-8")
    assert marker not in rendered
