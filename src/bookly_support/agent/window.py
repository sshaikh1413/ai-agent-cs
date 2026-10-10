"""Resolve "about a week ago" from placedAt. This is a date window, not an embedding."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

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


def short_date(value: datetime, today: date) -> str:
    """An order date as Mara says it: the year only when it is not this year."""

    moment = as_utc(value)
    if moment.year == today.year:
        return f"{_MONTHS[moment.month]} {moment.day}"
    return spoken_date(moment)


def days_past_window(delivered_at: datetime, today: date, return_window_days: int) -> int:
    """Days since the window closed. 0 or less means it is still open."""

    return (today - as_utc(delivered_at).date()).days - return_window_days


_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_MONTH_INDEX = {name.casefold(): index for index, name in enumerate(_MONTHS) if name}
_MONTH_INDEX.update({name[:3].casefold(): index for index, name in enumerate(_MONTHS) if name})
_MONTH_INDEX["sept"] = 9
_MONTH_WORD = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_AGO = re.compile(r"\b(\d+|an?|one|two|three|four|five|six)\s+(day|week|month)s?\s+ago\b")
_MONTH_DAY = re.compile(_MONTH_WORD + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b")
_IN_MONTH = re.compile(r"\b(?:in|during|back in|early|late|mid)\s+(?:-\s*)?" + _MONTH_WORD + r"\b")


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return start, nxt - timedelta(days=1)


def _latest_year(month: int, day: int, today: date) -> int:
    """The most recent year in which that month and day is not in the future."""

    return today.year if (month, day) <= (today.month, today.day) else today.year - 1


def ordered_window(text: str, today: date) -> tuple[date, date] | None:
    """When they say they ordered it, as a (first day, last day) window, or None.

    Closed phrases only: "yesterday", "3 days ago", "two weeks ago", "last week",
    "this month", "last month", "in September", "September 20th". Claude labels
    anything else in ``understand``. "About a week ago" keeps its own rule.
    """

    lowered = text.casefold()
    if re.search(r"\byesterday\b", lowered):
        day = today - timedelta(days=1)
        return day, day
    if re.search(r"\b(?:earlier )?today\b", lowered) and "order" in lowered:
        return today, today
    ago = _AGO.search(lowered)
    if ago:
        count = int(ago.group(1)) if ago.group(1).isdigit() else _NUMBERS[ago.group(1)]
        unit = ago.group(2)
        if unit == "day":
            center, slack = today - timedelta(days=count), 1
        elif unit == "week":
            center, slack = today - timedelta(days=7 * count), 3
        else:
            center, slack = today - timedelta(days=30 * count), 10
        return center - timedelta(days=slack), center + timedelta(days=slack)
    if re.search(r"\blast week\b", lowered):
        monday = today - timedelta(days=today.weekday())
        return monday - timedelta(days=7), monday - timedelta(days=1)
    if re.search(r"\bthis week\b", lowered):
        return today - timedelta(days=today.weekday()), today
    if re.search(r"\blast month\b", lowered):
        first = today.replace(day=1)
        previous = first - timedelta(days=1)
        return _month_bounds(previous.year, previous.month)
    if re.search(r"\bthis month\b", lowered):
        return today.replace(day=1), today
    dated = _MONTH_DAY.search(lowered)
    if dated:
        month = _MONTH_INDEX[dated.group(1).rstrip(".")]
        day = int(dated.group(2))
        try:
            when = date(_latest_year(month, day, today), month, day)
        except ValueError:
            return None
        return when - timedelta(days=2), when + timedelta(days=2)
    named = _IN_MONTH.search(lowered)
    if named:
        month = _MONTH_INDEX[named.group(1)]
        return _month_bounds(_latest_year(month, 1, today), month)
    return None
