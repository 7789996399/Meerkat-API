"""
Claim verification via local bidirectional DeBERTa-base-MNLI entailment
and keyword-based groundedness checking.

Two detection paths:
  1. Claim matches a source sentence but contradicts it
     → "contradicted" (DeBERTa catches this)
  2. Claim matches NO source sentence at all
     → "ungrounded" (keyword/entity matching catches this)

For matched claims, runs BIDIRECTIONAL entailment:
  - Forward:  premise=source_sentence, hypothesis=claim
  - Backward: premise=claim, hypothesis=source_sentence
  - BOTH ENTAILMENT   → VERIFIED  (true semantic equivalence)
  - EITHER CONTRADICTION → CONTRADICTED
  - Otherwise          → UNVERIFIED

Source text is split into individual lines/sentences so that each
"- Medication: dose" line becomes its own matchable unit. Claims are
matched to the best source line(s) by keyword overlap before running
DeBERTa, and claims with no meaningful overlap are flagged as ungrounded.
"""

import logging
import re

from transformers import pipeline

logger = logging.getLogger(__name__)

_nli_pipeline = None

# Minimum keyword overlap score to consider a claim "grounded" in a source line
_OVERLAP_THRESHOLD = 0.15

# Max source lines to run through DeBERTa per claim (top N by overlap)
_MAX_NLI_SENTENCES = 3

# Stop words excluded from keyword overlap scoring
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "was", "were", "are", "been",
    "be", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might",
    "shall", "can", "and", "or", "but", "in", "on", "at",
    "to", "for", "of", "with", "by", "from", "as", "into",
    "that", "which", "who", "whom", "this", "these", "those",
    "it", "its", "not", "no", "nor", "so", "if", "then",
    "than", "too", "very", "just", "about", "also", "only",
    "patient", "pt", "he", "she", "his", "her", "they", "their",
})


def load_model():
    """Pre-load the NLI model. Call at startup to avoid cold-start latency."""
    global _nli_pipeline
    if _nli_pipeline is None:
        logger.info("Loading microsoft/deberta-base-mnli for claim verification ...")
        _nli_pipeline = pipeline(
            "text-classification",
            model="microsoft/deberta-base-mnli",
            device=-1,  # CPU
        )
        logger.info("DeBERTa-base-MNLI loaded")
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


# ── Source splitting ─────────────────────────────────────────────


def _split_source_sentences(text: str) -> list[str]:
    """Split prose text into sentences, protecting common abbreviations."""
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


def _split_source_lines(text: str) -> list[str]:
    """
    Split source into individual lines/sentences for fine-grained matching.

    Handles structured clinical notes (newline/bullet-separated) and prose.
    Each "- Medication: dose" line becomes its own matchable unit.
    """
    lines = []
    for raw_line in text.split("\n"):
        stripped = raw_line.strip().lstrip("-•*>").strip()
        if len(stripped) < 5:
            continue
        # Long prose lines: further split into sentences
        if len(stripped.split()) > 40:
            lines.extend(_split_source_sentences(stripped))
        else:
            lines.append(stripped)

    # Fall back to sentence splitting if no newline structure
    if not lines:
        lines = _split_source_sentences(text)

    return lines


# ── Keyword overlap scoring ──────────────────────────────────────


def _tokenize(text: str) -> set[str]:
    """Extract content tokens from text, excluding stop words."""
    tokens = set(re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower()))
    return tokens - _STOP_WORDS


def _overlap_score(claim_tokens: set[str], sentence_tokens: set[str]) -> float:
    """Fraction of claim tokens found in the source sentence."""
    if not claim_tokens:
        return 0.0
    return len(claim_tokens & sentence_tokens) / len(claim_tokens)


def _find_best_matches(
    claim_text: str,
    claim_entities: list[str],
    source_lines: list[str],
) -> list[tuple[str, float]]:
    """
    Rank source lines by keyword overlap with the claim.

    Returns list of (sentence, score) sorted by descending score.
    """
    claim_tokens = _tokenize(claim_text)
    for ent in claim_entities:
        claim_tokens.update(re.findall(r"[a-z]+|\d+(?:\.\d+)?", ent.lower()))

    scored = []
    for line in source_lines:
        line_tokens = _tokenize(line)
        score = _overlap_score(claim_tokens, line_tokens)
        scored.append((line, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _claim_entities_in_source(claim_entities: list[str], full_source: str) -> bool:
    """Check whether ANY claim entity appears somewhere in the full source text."""
    source_lower = full_source.lower()
    for ent in claim_entities:
        if ent.lower() in source_lower:
            return True
    return False


# ── Main verification ────────────────────────────────────────────


def verify_claims(
    claims: list[dict],
    source_context: str,
) -> list[dict]:
    """
    Verify each claim against source context.

    Two detection paths:
      1. Best-matching source sentence contradicts claim → "contradicted"
      2. No source sentence has meaningful overlap → "ungrounded"

    Mutates each claim dict in-place, adding:
      - status: "verified" | "contradicted" | "unverified" | "ungrounded"
      - entailment_score: float (1.0 verified, 0.0 contradicted/ungrounded, 0.5 unverified)

    Returns the same list.
    """
    if not source_context.strip():
        for claim in claims:
            claim["status"] = "unverified"
            claim["entailment_score"] = 0.0
        return claims

    # Pre-load model (no-op if already loaded)
    load_model()

    source_lines = _split_source_lines(source_context)
    if not source_lines:
        for claim in claims:
            claim["status"] = "unverified"
            claim["entailment_score"] = 0.0
        return claims

    for claim in claims:
        _verify_single(claim, source_lines, source_context)

    return claims


def _verify_single(
    claim: dict,
    source_lines: list[str],
    full_source: str,
) -> None:
    """Verify a single claim: groundedness check then DeBERTa entailment."""
    claim_text = claim["text"]
    claim_entities = claim.get("entities", [])

    # Step 1: Find best matching source lines by keyword overlap
    ranked = _find_best_matches(claim_text, claim_entities, source_lines)

    best_score = ranked[0][1] if ranked else 0.0

    # Step 2: Ungrounded check
    if best_score < _OVERLAP_THRESHOLD:
        # Low keyword overlap. Check if key entities exist anywhere in source.
        if claim_entities and not _claim_entities_in_source(claim_entities, full_source):
            claim["status"] = "ungrounded"
            claim["entailment_score"] = 0.0
            return

        # No entities to check and no overlap at all — ungrounded
        if best_score == 0.0:
            claim["status"] = "ungrounded"
            claim["entailment_score"] = 0.0
            return

    # Step 3: Run DeBERTa on top matching sentences only
    top_sentences = [s for s, score in ranked[:_MAX_NLI_SENTENCES] if score > 0]
    if not top_sentences:
        # Fallback: use all source lines
        top_sentences = source_lines

    best_status = "unverified"
    best_entailment_score = 0.5

    for sent in top_sentences:
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
            best_entailment_score = 0.0

        # Track forward-only entailment as partial support
        if forward == "ENTAILMENT" and best_status != "contradicted":
            best_status = "verified"
            best_entailment_score = 0.8

    claim["status"] = best_status
    claim["entailment_score"] = best_entailment_score
