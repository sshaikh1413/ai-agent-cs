from datetime import date, datetime, timedelta, timezone

from bookly_support.agent.eligibility import is_eligible

TODAY = date(2026, 10, 1)


def _delivered(on: date) -> datetime:
    return datetime(on.year, on.month, on.day, 8, tzinfo=timezone.utc)


def test_window_boundary_uses_the_policy_length() -> None:
    assert is_eligible(_delivered(TODAY - timedelta(days=30)), TODAY, 30)
    assert not is_eligible(_delivered(TODAY - timedelta(days=31)), TODAY, 30)
    assert is_eligible(_delivered(TODAY - timedelta(days=10)), TODAY, 10)
    assert not is_eligible(_delivered(TODAY - timedelta(days=11)), TODAY, 10)


def test_missing_delivery_is_not_eligible() -> None:
    assert not is_eligible(None, TODAY, 30)
