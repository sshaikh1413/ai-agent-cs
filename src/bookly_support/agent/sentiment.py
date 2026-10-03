"""Score the reason the customer typed. This label does not choose the offer."""

from __future__ import annotations

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_ANALYZER = SentimentIntensityAnalyzer()

# Cutoffs published with VADER for the compound score.
_POSITIVE_AT = 0.05
_NEGATIVE_AT = -0.05


def label_sentiment(text: str) -> str:
    """Map the compound score of this text to negative, neutral, or positive."""

    compound = float(_ANALYZER.polarity_scores(text or "")["compound"])
    if compound >= _POSITIVE_AT:
        return "positive"
    if compound <= _NEGATIVE_AT:
        return "negative"
    return "neutral"
