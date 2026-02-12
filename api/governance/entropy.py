"""
Semantic Entropy Check

Calls the real semantic entropy microservice (meerkat-entropy on port 8001)
which implements the full Farquhar et al. (Nature, 2024) pipeline:
  1. Generate N completions via Ollama at temperature=1.0
  2. Cluster by bidirectional entailment (DeBERTa-large-MNLI)
  3. Compute Shannon entropy over clusters

Falls back to a local heuristic if the microservice is unavailable
(e.g. running the gateway standalone without Docker Compose).
"""

import logging
import os
import re

import httpx

from api.models.schemas import CheckResult

logger = logging.getLogger(__name__)

ENTROPY_SERVICE_URL = os.getenv("ENTROPY_SERVICE_URL", "http://localhost:8001")

# ── Flags that the microservice interpretation maps to ─────────────

_FLAGGED_INTERPRETATIONS = {
    "moderate_uncertainty",
    "high_uncertainty",
    "confabulation_likely",
}


async def check_entropy(
    output: str,
    question: str | None = None,
    context: str | None = None,
) -> CheckResult:
    """Run semantic entropy check via the real ML microservice.

    Falls back to the local heuristic if the service is unreachable.
    """
    if question is None:
        # Can't call the microservice without a question -- use heuristic
        return _check_entropy_heuristic(output)

    url = f"{ENTROPY_SERVICE_URL}/analyze"
    payload = {
        "question": question,
        "ai_output": output,
        "num_completions": 10,
    }
    if context:
        payload["source_context"] = context

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()

        data = resp.json()
        return _map_service_response(data)

    except Exception as e:
        logger.warning(
            "Entropy microservice unavailable (%s), falling back to heuristic",
            e,
        )
        return _check_entropy_heuristic(output)


def _map_service_response(data: dict) -> CheckResult:
    """Map the microservice JSON response to a CheckResult."""
    semantic_entropy = data["semantic_entropy"]
    interpretation = data["interpretation"]
    num_clusters = data["num_clusters"]
    num_completions = data["num_completions"]
    ai_in_majority = data["ai_output_in_majority"]

    # Invert: microservice entropy 0=certain, 1=uncertain
    # CheckResult score 0=worst, 1=best
    score = round(1.0 - semantic_entropy, 3)

    flags: list[str] = []
    if interpretation in _FLAGGED_INTERPRETATIONS:
        flags.append(interpretation)
    if not ai_in_majority and num_clusters > 1:
        flags.append("ai_output_outside_majority_cluster")

    # Build detail message
    if interpretation == "certain":
        detail = (
            f"High confidence: all {num_completions} sampled completions "
            f"converged into {num_clusters} cluster(s). "
            f"Semantic entropy: {semantic_entropy:.3f}."
        )
    elif interpretation == "confabulation_likely":
        detail = (
            f"Confabulation likely: {num_completions} completions diverged into "
            f"{num_clusters} clusters. Semantic entropy: {semantic_entropy:.3f}."
        )
    else:
        level = interpretation.replace("_", " ")
        detail = (
            f"{level.capitalize()}: {num_completions} completions formed "
            f"{num_clusters} cluster(s). Semantic entropy: {semantic_entropy:.3f}."
        )

    if not ai_in_majority and num_clusters > 1:
        detail += " The original AI output is NOT in the majority cluster."

    return CheckResult(score=score, flags=flags, detail=detail)


# ── Heuristic fallback (text-based, no ML) ────────────────────────

HEDGE_WORDS = {
    "may", "might", "could", "possibly", "perhaps", "uncertain",
    "likely", "unlikely", "appears", "seems", "arguably", "potentially",
    "suggest", "suggests", "probable", "presumably", "conceivably",
}

HEDGE_PHRASES = [
    "it is unclear", "it seems", "it appears", "it is possible",
    "it is likely", "it is unlikely", "there may be", "there might be",
    "not entirely clear", "difficult to determine", "hard to say",
    "open to interpretation", "subject to debate",
]

CONFIDENCE_PATTERNS = [
    r'\b\d+[\s-](?:day|week|month|year|mile)s?\b',
    r'(?:Section|Clause|Article)\s+\d',
    r'\$[\d,]+',
    r'\d+(?:\.\d+)?%',
    r'\b(?:requires|contains|states|specifies|provides|mandates)\b',
]

CONTRADICTION_PAIRS = [
    (r'\bbut\s+(?:also|however)', "hedging_qualifier"),
    (r'\bhowever.*(?:nevertheless|nonetheless)', "contradictory_structure"),
    (r'\bon\s+(?:the\s+)?one\s+hand.*on\s+the\s+other', "on_the_other_hand"),
]


def _check_entropy_heuristic(output: str) -> CheckResult:
    """Heuristic fallback: analyse the text itself for confidence signals."""
    text_lower = output.lower()
    words = text_lower.split()
    word_count = max(len(words), 1)

    hedge_count = sum(1 for w in words if w in HEDGE_WORDS)
    hedge_ratio = hedge_count / word_count
    phrase_count = sum(1 for phrase in HEDGE_PHRASES if phrase in text_lower)
    confidence_count = sum(
        len(re.findall(pattern, output, re.IGNORECASE))
        for pattern in CONFIDENCE_PATTERNS
    )
    contradiction_count = sum(
        1 for pattern, _ in CONTRADICTION_PAIRS
        if re.search(pattern, text_lower)
    )

    score = 0.5
    score += min(confidence_count * 0.08, 0.4)
    score -= hedge_ratio * 3.0
    score -= phrase_count * 0.08
    score -= contradiction_count * 0.15
    if word_count < 20 and confidence_count == 0:
        score -= 0.1
    score = round(max(0.0, min(1.0, score)), 3)

    flags: list[str] = []
    details: list[str] = []

    if score < 0.35:
        flags.append("high_uncertainty")
        details.append("Output shows significant hedging and lacks specific details.")
    elif score < 0.65:
        flags.append("moderate_uncertainty")
        details.append("Output contains some hedging language.")

    if contradiction_count > 0:
        flags.append("self_contradicting")
        details.append("Output contains self-contradicting statements.")

    if hedge_count > 0 and not details:
        details.append(f"Detected {hedge_count} hedge word(s) but overall confidence is acceptable.")

    if not details:
        details.append("Output shows high confidence with specific facts and definitive language.")

    detail = " ".join(details) + " (heuristic -- entropy service unavailable)"
    return CheckResult(score=score, flags=flags, detail=detail)
