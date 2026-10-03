"""Pick one catalog title the customer does not already own."""

from __future__ import annotations

import hashlib


def choose_recommendation(
    owned_titles: list[str],
    catalog: list[dict],
    seed: str,
) -> dict | None:
    """One non-horror title, skipping books already on the account.

    Remaining titles are sorted by name. The seed — an order id, or the
    customer id when the session has no order — chooses the index. The same
    seed always returns the same book. A different seed can return another.
    Returns None when every catalog title is horror or already owned.
    """

    owned = {title.casefold() for title in owned_titles if title and title.strip()}
    choices: list[dict] = []
    for book in catalog:
        title = str(book.get("title") or "").strip()
        genre = str(book.get("genre") or "").strip().casefold()
        if not title or genre == "horror" or title.casefold() in owned:
            continue
        choices.append(book)
    if not choices:
        return None
    ordered = sorted(
        choices,
        key=lambda book: (
            str(book.get("title") or "").casefold(),
            str(book.get("_id") or ""),
        ),
    )
    chosen = ordered[_index_for_seed(seed, len(ordered))]
    author = chosen.get("author")
    return {
        "title": str(chosen["title"]).strip(),
        "genre": str(chosen.get("genre") or "").strip(),
        "author": author.strip() if isinstance(author, str) and author.strip() else None,
    }


def _index_for_seed(seed: str, count: int) -> int:
    digest = hashlib.sha256((seed or "").encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % count
