"""Return-window check. The window length comes from the policy document."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from bookly_support.agent.window import as_utc


def is_eligible(
    delivered_at: datetime | None,
    today: date,
    return_window_days: int,
) -> bool:
    if delivered_at is None or return_window_days < 0:
        return False
    deadline = as_utc(delivered_at).date() + timedelta(days=return_window_days)
    return today <= deadline
