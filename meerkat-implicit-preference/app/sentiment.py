"""
Sentiment polarity analysis using distilbert-base-uncased-finetuned-sst-2-english.
Detects whether the AI output has a strong positive or negative sentiment lean.
"""

from transformers import pipeline

_classifier = None


def _get_classifier():
    global _classifier
    if _classifier is None:
        _classifier = pipeline(
            "sentiment-analysis",
            model="distilbert-base-uncased-finetuned-sst-2-english",
            top_k=None,
        )
    return _classifier


def analyze_sentiment(text: str) -> dict:
    """
    Returns sentiment scores for the text.

    For long texts, splits into sentences and averages the scores,
    since the model has a 512-token limit.
    """
    classifier = _get_classifier()

    # Split into sentences for long texts
    sentences = _split_sentences(text)
    if not sentences:
        return {"label": "NEUTRAL", "positive_score": 0.5, "negative_score": 0.5}

    # Batch classify (truncate individual sentences to avoid token overflow)
    truncated = [s[:500] for s in sentences]
    results = classifier(truncated)

    # Average scores across sentences
    pos_total = 0.0
    neg_total = 0.0
    for result in results:
        scores = {r["label"]: r["score"] for r in result}
        pos_total += scores.get("POSITIVE", 0.0)
        neg_total += scores.get("NEGATIVE", 0.0)

    n = len(results)
    pos_avg = pos_total / n
    neg_avg = neg_total / n

    label = "POSITIVE" if pos_avg > neg_avg else "NEGATIVE"
    if abs(pos_avg - neg_avg) < 0.15:
        label = "NEUTRAL"

    return {
        "label": label,
        "positive_score": round(pos_avg, 4),
        "negative_score": round(neg_avg, 4),
    }


def _split_sentences(text: str) -> list[str]:
    """Simple sentence splitter."""
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s for s in sentences if len(s.strip()) > 5]
