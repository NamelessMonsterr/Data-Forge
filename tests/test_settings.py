"""Settings and local environment loading tests."""

import os

from backend.core.settings import load_env_file


def test_load_env_file_sets_missing_values_without_overriding(tmp_path, monkeypatch):
    """Local .env files should work for development without overriding process env."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DATAFORGE_DISCOVERY_LIVE=true",
                "EXISTING_VALUE=from-file",
                "QUOTED_VALUE='quoted'",
                "# ignored comment",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("DATAFORGE_DISCOVERY_LIVE", raising=False)
    monkeypatch.delenv("DATAFORGE_SKIP_DOTENV", raising=False)
    monkeypatch.setenv("EXISTING_VALUE", "from-env")

    load_env_file(env_file)

    assert os.environ["DATAFORGE_DISCOVERY_LIVE"] == "true"
    assert os.environ["EXISTING_VALUE"] == "from-env"
    assert os.environ["QUOTED_VALUE"] == "quoted"
