"""Resolve "about a week ago" from placedAt. This is a date window, not an embedding."""

from __future__ import annotations

from datetime import date, datetime, timezone

WEEK_MIN_DAYS = 5
WEEK_MAX_DAYS = 9


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def days_before(placed_at: datetime, today: date) -> int:
    return (today - as_utc(placed_at).date()).days


def about_a_week(placed_at: datetime, today: date) -> bool:
    elapsed = days_before(placed_at, today)
    return WEEK_MIN_DAYS <= elapsed <= WEEK_MAX_DAYS


_MONTHS = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def spoken_date(value: datetime) -> str:
    """A delivery date as Mara says it, from the stored instant."""

    moment = as_utc(value)
    return f"{_MONTHS[moment.month]} {moment.day}, {moment.year}"


def iso_day(value: datetime) -> str:
    return as_utc(value).date().isoformat()


def week_matches(orders: list[dict], today: date) -> list[dict]:
    """Orders whose placedAt falls 5 to 9 days before today, inclusive."""

    found: list[dict] = []
    for order in orders:
        placed_at = order.get("placedAt")
        if isinstance(placed_at, datetime) and about_a_week(placed_at, today):
            found.append(order)
    return found
