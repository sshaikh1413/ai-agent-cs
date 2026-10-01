"""Runtime settings. Values come from the process environment only."""

from __future__ import annotations

import os
from dataclasses import dataclass

CUSTOMER_ID = "cust_becky"
POLICY_ID = "return-window"
MODEL_NAME = "claude-sonnet-5-5"
PYDANTIC_MODEL = "anthropic:claude-sonnet-5-5"
WORKSPACE_HEADER = "anthropic-workspace-id"

_REQUIRED = ("ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "MONGODB_URI")


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    anthropic_workspace_id: str
    mongodb_uri: str
    model_name: str = MODEL_NAME

    @property
    def pydantic_model(self) -> str:
        return f"anthropic:{self.model_name}"


def load_settings() -> Settings:
    missing = [name for name in _REQUIRED if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError(
            "Missing environment variables: " + ", ".join(missing)
        )
    # The demo model is fixed. A different ANTHROPIC_MODEL value is ignored
    # so the phrasing client cannot drift off claude-sonnet-5-5.
    return Settings(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"].strip(),
        anthropic_workspace_id=os.environ["ANTHROPIC_WORKSPACE_ID"].strip(),
        mongodb_uri=os.environ["MONGODB_URI"].strip(),
        model_name=MODEL_NAME,
    )
