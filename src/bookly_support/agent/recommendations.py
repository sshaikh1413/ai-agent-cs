"""Pick one catalog title the customer does not already own."""

from __future__ import annotations


def choose_recommendation(owned_titles: list[str], catalog: list[dict]) -> dict | None:
    """One non-horror title, alphabetical, skipping books already on the account.

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
    chosen = sorted(choices, key=lambda book: str(book.get("title") or "").casefold())[0]
    author = chosen.get("author")
    return {
        "title": str(chosen["title"]).strip(),
        "genre": str(chosen.get("genre") or "").strip(),
        "author": author.strip() if isinstance(author, str) and author.strip() else None,
    }
