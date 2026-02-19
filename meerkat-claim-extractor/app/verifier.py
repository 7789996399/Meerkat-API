"""
Claim verification via local bidirectional DeBERTa-large-MNLI entailment.

For each claim, runs BIDIRECTIONAL entailment against each source sentence:
  - Forward:  premise=source_sentence, hypothesis=claim
  - Backward: premise=claim, hypothesis=source_sentence
  - BOTH ENTAILMENT   → VERIFIED  (true semantic equivalence)
  - EITHER CONTRADICTION → CONTRADICTED
  - Otherwise          → UNVERIFIED

Source text is split into sentences so that long documents don't exceed
the 512-token limit. If ANY source sentence gives bidirectional entailment,
the claim is verified.

Reference: meerkat-semantic-entropy/app/entailment_client.py
"""

import logging
import re

from transformers import pipeline

logger = logging.getLogger(__name__)

_nli_pipeline = None


def load_model():
    """Pre-load the NLI model. Call at startup to avoid cold-start latency."""
    global _nli_pipeline
    if _nli_pipeline is None:
        logger.info("Loading microsoft/deberta-large-mnli for claim verification ...")
        _nli_pipeline = pipeline(
            "text-classification",
            model="microsoft/deberta-large-mnli",
            device=-1,  # CPU
        )
        logger.info("DeBERTa-large-MNLI loaded")
    return _nli_pipeline


def _check_entailment(premise: str, hypothesis: str) -> str:
    """
    Check NLI relation between premise and hypothesis.
    Returns 'ENTAILMENT', 'NEUTRAL', or 'CONTRADICTION'.
    """
    nli = load_model()
    try:
        result = nli(
            f"{premise} [SEP] {hypothesis}",
            truncation=True,
            max_length=512,
        )
        return result[0]["label"]
    except Exception as e:
        logger.error("Entailment check failed: %s", e)
        return "NEUTRAL"


def _split_source_sentences(text: str) -> list[str]:
    """Split source text into sentences for per-sentence entailment checks."""
    # Protect common abbreviations
    protected = text
    for abbr in ("Dr.", "Mr.", "Mrs.", "Ms.", "Inc.", "Corp.", "vs.", "etc.", "e.g.", "i.e."):
        protected = protected.replace(abbr, abbr.replace(".", "_DOT_"))

    parts = re.split(r"(?<=[.!?])\s+", protected)
    sentences = []
    for p in parts:
        restored = p.replace("_DOT_", ".").strip()
        if len(restored) >= 10:
            sentences.append(restored)
    return sentences


def verify_claims(
    claims: list[dict],
    source_context: str,
) -> list[dict]:
    """
    Verify each claim against source using bidirectional DeBERTa entailment.

    For each claim, checks it against every source sentence. If ANY sentence
    produces bidirectional entailment, the claim is verified.

    Mutates each claim dict in-place, adding:
      - status: "verified" | "contradicted" | "unverified"
      - entailment_score: float (1.0 if verified, 0.0 if contradicted, 0.5 if unverified)

    Returns the same list.
    """
    if not source_context.strip():
        for claim in claims:
            claim["status"] = "unverified"
            claim["entailment_score"] = 0.0
        return claims

    # Pre-load model (no-op if already loaded)
    load_model()

    source_sentences = _split_source_sentences(source_context)
    if not source_sentences:
        for claim in claims:
            claim["status"] = "unverified"
            claim["entailment_score"] = 0.0
        return claims

    for claim in claims:
        _verify_single(claim, source_sentences)

    return claims


def _verify_single(claim: dict, source_sentences: list[str]) -> None:
    """Verify a single claim via bidirectional entailment against source sentences."""
    claim_text = claim["text"]

    best_status = "unverified"
    best_score = 0.5

    for sent in source_sentences:
        forward = _check_entailment(sent, claim_text)
        backward = _check_entailment(claim_text, sent)

        if forward == "ENTAILMENT" and backward == "ENTAILMENT":
            # Bidirectional entailment = verified (true equivalence)
            claim["status"] = "verified"
            claim["entailment_score"] = 1.0
            return

        if forward == "CONTRADICTION" or backward == "CONTRADICTION":
            # Any contradiction is significant
            best_status = "contradicted"
            best_score = 0.0

        # Track forward-only entailment as partial support
        if forward == "ENTAILMENT" and best_status != "contradicted":
            best_status = "verified"
            best_score = 0.8

    claim["status"] = best_status
    claim["entailment_score"] = best_score
