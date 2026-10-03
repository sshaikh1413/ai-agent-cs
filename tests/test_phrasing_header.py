from bookly_support.agent.phrasing import ClaudePhraser
from bookly_support.config import PYDANTIC_MODEL, Settings


def test_model_string_and_workspace_header() -> None:
    assert PYDANTIC_MODEL == "anthropic:claude-sonnet-5-5"
    phraser = ClaudePhraser(
        Settings(
            anthropic_api_key="test-key-not-real",
            anthropic_workspace_id="ws_test",
            mongodb_uri="mongodb://localhost",
        )
    )
    assert phraser.model_string == "anthropic:claude-sonnet-5-5"
    client = phraser._agent.model._provider.client  # type: ignore[attr-defined]
    headers = {key.lower(): value for key, value in client.default_headers.items()}
    assert headers["anthropic-workspace-id"] == "ws_test"
    settings = phraser._agent.model_settings
    assert settings is not None
    assert settings["extra_headers"]["anthropic-workspace-id"] == "ws_test"
