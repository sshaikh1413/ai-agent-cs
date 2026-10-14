"""Pure tests label messages from the golden set instead of calling Claude."""

from __future__ import annotations

import pytest

from bookly_support.agent import machine
from golden_understanding import GoldenUnderstander


@pytest.fixture(autouse=True)
def _golden_understanding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine, "DEFAULT_UNDERSTANDER", GoldenUnderstander())
