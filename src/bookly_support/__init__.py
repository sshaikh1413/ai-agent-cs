"""Bookly bookstore support agent."""


def main() -> None:
    import uvicorn

    uvicorn.run("bookly_support.main:app", host="0.0.0.0", port=8642)
