"""
Implicit Preference Check

Calls the real implicit-preference microservice (meerkat-preference on port 8003)
which uses DistilBERT sentiment analysis, domain-specific direction detection,
and counterfactual consistency analysis.

Falls back to a local keyword heuristic if the microservice is unavailable.
"""

import logging
import os
import re

import httpx

from api.models.schemas import CheckResult

logger = logging.getLogger(__name__)

PREFERENCE_SERVICE_URL = os.getenv("PREFERENCE_SERVICE_URL", "http://localhost:8003")


async def check_preference(
    output: str,
    domain: str = "general",
    context: str | None = None,
) -> CheckResult:
    """Run implicit preference check via the real ML microservice.

    Falls back to the local heuristic if the service is unreachable.
    """
    url = f"{PREFERENCE_SERVICE_URL}/analyze"
    payload = {
        "output": output,
        "domain": domain,
        "source": context or "",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()

        data = resp.json()
        return _map_service_response(data)

    except Exception as e:
        logger.warning(
            "Preference microservice unavailable (%s), falling back to heuristic",
            e,
        )
        return _check_preference_heuristic(output)


def _map_service_response(data: dict) -> CheckResult:
    """Map the microservice JSON response to a CheckResult."""
    score = round(data["score"], 3)
    flags = data.get("flags", [])
    bias_detected = data["bias_detected"]
    direction = data["direction"]
    party_a = data.get("party_a", "")
    party_b = data.get("party_b", "")
    details = data.get("details", {})

    # Build detail message
    sentiment = details.get("sentiment", {})
    sentiment_label = sentiment.get("label", "unknown")

    if bias_detected:
        detail = (
            f"Bias detected (score {score:.3f}). "
            f"Direction: {direction} (favoring {party_a} over {party_b}). "
            f"Sentiment: {sentiment_label}."
        )
    else:
        detail = (
            f"Output is balanced (score {score:.3f}). "
            f"Direction: {direction}. Sentiment: {sentiment_label}."
        )

    return CheckResult(score=score, flags=flags, detail=detail)


# ── Heuristic fallback (keyword-based, no ML) ─────────────────────

STRONG_BIAS_PHRASES = [
    "extremely aggressive", "extremely unfavorable", "clearly unfair",
    "obviously risky", "obviously unfavorable", "must reject",
    "should never accept", "should never agree", "outrageous",
    "alarming", "devastating", "unacceptable terms",
    "strongly advise against", "no reasonable person would",
    "you must not", "under no circumstances",
]

MILD_BIAS_WORDS = [
    "must", "should", "always", "never", "clearly", "obviously",
    "undoubtedly", "certainly", "worst", "terrible", "dangerous",
    "unacceptable", "unreasonable", "excessive", "egregious",
]

BALANCED_INDICATORS = [
    "however", "on the other hand", "alternatively", "in contrast",
    "both parties", "either party", "balanced", "standard",
    "typical", "common in", "customary", "reasonable",
    "the clause states", "the provision provides", "the section specifies",
    "according to", "as stated in",
]


def _check_preference_heuristic(output: str) -> CheckResult:
    """Heuristic fallback: keyword counting for bias detection."""
    text_lower = output.lower()

    strong_hits = sum(1 for phrase in STRONG_BIAS_PHRASES if phrase in text_lower)
    mild_hits = sum(1 for word in MILD_BIAS_WORDS if word in text_lower)
    balanced_hits = sum(1 for phrase in BALANCED_INDICATORS if phrase in text_lower)
    aggressive_claims = len(re.findall(
        r'\b(?:aggressive|extreme|excessive|unreasonable|outrageous)\s+\w+',
        text_lower,
    ))

    score = 0.85
    score -= strong_hits * 0.20
    score -= mild_hits * 0.04
    score -= aggressive_claims * 0.10
    score += balanced_hits * 0.03
    score = round(max(0.0, min(1.0, score)), 3)

    flags: list[str] = []

    if score < 0.5:
        flags.append("strong_bias")
        detail = (
            f"Output contains strongly biased language ({strong_hits} loaded phrase(s), "
            f"{mild_hits} directional word(s)). The response appears to steer the user "
            f"rather than present balanced analysis."
        )
    elif score < 0.75:
        flags.append("mild_preference")
        detail = (
            f"Output contains some directional language ({mild_hits} indicator(s)). "
            f"Consider reviewing for implicit preference."
        )
    else:
        detail = "Output uses neutral, balanced language without significant directional bias."
        if balanced_hits > 0:
            detail += f" Found {balanced_hits} balanced/objective indicator(s)."

    detail += " (heuristic -- preference service unavailable)"
    return CheckResult(score=score, flags=flags, detail=detail)
