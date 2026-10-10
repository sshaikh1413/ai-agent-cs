from datetime import date, datetime, timezone

from bookly_support.agent.resolve import resolve_order
from bookly_support.agent.window import WEEK_MAX_DAYS, WEEK_MIN_DAYS, about_a_week, week_matches

TODAY = date(2026, 10, 1)


def _placed(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)


def _order(order_id: str, placed: date) -> dict:
    return {
        "orderId": order_id,
        "title": order_id,
        "placedAt": _placed(placed),
    }


def test_about_a_week_is_five_through_nine_days() -> None:
    assert WEEK_MIN_DAYS == 5
    assert WEEK_MAX_DAYS == 9
    assert about_a_week(_placed(date(2026, 9, 26)), TODAY)
    assert about_a_week(_placed(date(2026, 9, 24)), TODAY)
    assert about_a_week(_placed(date(2026, 9, 22)), TODAY)
    assert not about_a_week(_placed(date(2026, 9, 27)), TODAY)
    assert not about_a_week(_placed(date(2026, 9, 21)), TODAY)


def test_one_week_match_is_selected_and_two_are_not() -> None:
    midnight = _order("BLY-22018", date(2026, 9, 24))
    circe = _order("BLY-22002", date(2026, 9, 11))
    assert week_matches([midnight, circe], TODAY) == [midnight]
    kind, matches = resolve_order("the one from about a week ago", [midnight, circe], TODAY)
    assert kind == "selected"
    assert matches == [midnight]

    other = _order("BLY-22019", date(2026, 9, 26))
    kind, matches = resolve_order("about a week ago", [midnight, other], TODAY)
    assert kind == "ambiguous"
    assert {order["orderId"] for order in matches} == {"BLY-22018", "BLY-22019"}

    kind, matches = resolve_order("about a week ago", [circe], TODAY)
    assert kind == "week_none"
    assert matches == [circe]
