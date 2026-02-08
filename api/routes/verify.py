"""
POST /v1/verify — Real-time AI output verification.

This is the core endpoint. A client sends an AI model's input and output,
and Meerkat runs governance checks and returns a trust score.

DEMO MODE: All four checks use simulated scoring (keyword matching,
heuristics, random variance). The API contract is identical to production --
swap in real models later without changing any client code.
"""

import random
import re
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter

from api.models.schemas import (
    CheckResult,
    ClaimCheckResult,
    GovernanceCheck,
    VerifyRequest,
    VerifyResponse,
)
from api.store import audit_records

router = APIRouter()


# ---------------------------------------------------------------------------
# Simulated governance checks (demo mode)
#
# Each function below returns a CheckResult. In production, these would
# call real ML models (DeBERTa, sentence-transformers, etc.). For now,
# they produce realistic-looking scores using simple heuristics.
# ---------------------------------------------------------------------------

def _sim_entailment(output: str, context: str | None) -> CheckResult:
    """Simulated DeBERTa entailment check.

    Real version: tokenize (source, claim) pairs, run through DeBERTa NLI,
    get entailment/contradiction/neutral probabilities.

    Demo version: measures keyword overlap between output and context.
    More shared words = higher entailment score."""

    if not context:
        # No source document provided -- can't check entailment properly
        return CheckResult(
            score=0.5,
            flags=["no_context_provided"],
            detail="No source document provided. Entailment check requires context for accurate scoring.",
        )

    # Simple keyword overlap: what fraction of output words appear in context?
    output_words = set(re.findall(r"\w+", output.lower()))
    context_words = set(re.findall(r"\w+", context.lower()))

    if not output_words:
        overlap = 0.0
    else:
        overlap = len(output_words & context_words) / len(output_words)

    # Add some realistic variance so it doesn't look too mechanical
    score = min(1.0, max(0.0, overlap + random.uniform(-0.1, 0.1)))

    flags = []
    if score < 0.4:
        flags.append("entailment_contradiction")
    elif score < 0.6:
        flags.append("weak_entailment")

    if score >= 0.7:
        detail = "Claims are well-grounded in the source document."
    elif score >= 0.4:
        detail = "Some claims have weak support in the source document."
    else:
        detail = "Output contains claims that contradict or are unsupported by the source."

    return CheckResult(score=round(score, 3), flags=flags, detail=detail)


def _sim_entropy(output: str) -> CheckResult:
    """Simulated semantic entropy check.

    Real version: sample N completions from the model, embed them,
    cluster by semantic similarity, compute entropy over cluster distribution.

    Demo version: uses hedge words and response length as a proxy for
    model uncertainty. More hedging = higher entropy = less confident."""

    # Hedge words that suggest the model is uncertain
    hedge_words = ["may", "might", "could", "possibly", "perhaps", "uncertain",
                   "likely", "unlikely", "appears", "seems", "arguably"]

    words = output.lower().split()
    word_count = len(words)
    hedge_count = sum(1 for w in words if w in hedge_words)

    # More hedging and longer responses correlate with higher uncertainty
    hedge_ratio = hedge_count / max(word_count, 1)
    length_factor = min(word_count / 200, 1.0)  # longer = slightly more uncertain

    # Entropy score: 0 = very confident, 1 = very uncertain
    # We invert for the final score: high score = good (confident)
    raw_entropy = min(1.0, hedge_ratio * 5 + length_factor * 0.2)
    score = round(1.0 - raw_entropy + random.uniform(-0.05, 0.05), 3)
    score = min(1.0, max(0.0, score))

    flags = []
    if score < 0.4:
        flags.append("high_uncertainty")
    elif score < 0.7:
        flags.append("moderate_uncertainty")

    if score >= 0.7:
        detail = "Model output shows high confidence with consistent language."
    elif score >= 0.4:
        detail = "Model output contains hedging language suggesting moderate uncertainty."
    else:
        detail = "Model output shows significant uncertainty. Multiple hedge words detected."

    return CheckResult(score=score, flags=flags, detail=detail)


def _sim_preference(output: str) -> CheckResult:
    """Simulated implicit preference (bias) check.

    Real version: generate a mirror prompt (opposite framing), get both
    responses, compare with cosine similarity. High divergence = bias.

    Demo version: checks for strongly directional language that might
    indicate the model is steering the user."""

    # Words that suggest the model is pushing a specific direction
    bias_indicators = ["must", "should", "always", "never", "best", "worst",
                       "strongly recommend", "clearly", "obviously", "undoubtedly"]

    text_lower = output.lower()
    bias_hits = sum(1 for phrase in bias_indicators if phrase in text_lower)

    # More directional language = lower score (more biased)
    score = max(0.0, min(1.0, 1.0 - (bias_hits * 0.12) + random.uniform(-0.05, 0.05)))
    score = round(score, 3)

    flags = []
    if score < 0.6:
        flags.append("strong_bias")
    elif score < 0.85:
        flags.append("mild_preference")

    if score >= 0.85:
        detail = "No significant directional bias detected in the output."
    elif score >= 0.6:
        detail = "Output contains mildly directional language. Review for implicit preference."
    else:
        detail = "Output contains strongly directional language suggesting implicit bias."

    return CheckResult(score=score, flags=flags, detail=detail)


def _sim_claims(output: str, context: str | None) -> ClaimCheckResult:
    """Simulated claim extraction and verification.

    Real version: fine-tuned T5-small extracts claims, each claim is
    verified against context using DeBERTa entailment.

    Demo version: regex-based extraction of numbers, dates, percentages,
    and named entities. Verification uses keyword matching against context."""

    # Extract things that look like factual claims:
    # numbers, percentages, dollar amounts, dates, durations
    claim_patterns = [
        r"\$[\d,]+(?:\.\d{2})?",                    # dollar amounts
        r"\d+(?:\.\d+)?%",                           # percentages
        r"\d+[\s-](?:day|month|year|week)s?",        # durations
        r"(?:Section|Clause|Article)\s+[\d.]+",      # legal references
        r"\d{4}",                                     # years
    ]

    claims_found = []
    for pattern in claim_patterns:
        claims_found.extend(re.findall(pattern, output))

    total_claims = max(len(claims_found), 1)  # at least 1 for scoring

    if context:
        # Check how many extracted claims appear in the context
        context_lower = context.lower()
        verified = sum(1 for c in claims_found if c.lower() in context_lower)
    else:
        verified = 0

    unverified = total_claims - verified

    # Score: fraction of claims that are verified
    score = round(verified / total_claims + random.uniform(-0.05, 0.05), 3)
    score = min(1.0, max(0.0, score))

    flags = []
    if any(c.lower() not in (context or "").lower() for c in claims_found):
        if unverified > 2:
            flags.append("multiple_unverified_claims")
        elif unverified > 0:
            flags.append("unverified_claim")

    detail = f"Extracted {total_claims} factual claim(s). {verified} verified, {unverified} unverified."

    return ClaimCheckResult(
        score=score,
        flags=flags,
        detail=detail,
        claims=total_claims,
        verified=verified,
        unverified=unverified,
    )


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------

@router.post(
    "/v1/verify",
    response_model=VerifyResponse,
    summary="Verify an AI response",
    description=(
        "The core Meerkat endpoint. Send an AI model's input/output pair "
        "and get back a trust score with detailed governance analysis. "
        "Optionally provide source context for entailment checking."
    ),
    tags=["Governance"],
)
async def verify(request: VerifyRequest) -> VerifyResponse:
    start = time.time()

    # Run each requested governance check
    check_results: dict[str, CheckResult | ClaimCheckResult] = {}

    if GovernanceCheck.entailment in request.checks:
        check_results["entailment"] = _sim_entailment(request.output, request.context)

    if GovernanceCheck.semantic_entropy in request.checks:
        check_results["semantic_entropy"] = _sim_entropy(request.output)

    if GovernanceCheck.implicit_preference in request.checks:
        check_results["implicit_preference"] = _sim_preference(request.output)

    if GovernanceCheck.claim_extraction in request.checks:
        check_results["claim_extraction"] = _sim_claims(request.output, request.context)

    # Compute composite trust score (weighted average of all check scores)
    if check_results:
        avg_score = sum(r.score for r in check_results.values()) / len(check_results)
    else:
        avg_score = 0.5

    trust_score = int(round(avg_score * 100))

    # Determine governance decision based on thresholds
    # (In production, these thresholds come from the org's config)
    if trust_score >= 85:
        status = "PASS"
    elif trust_score >= 40:
        status = "FLAG"
    else:
        status = "BLOCK"

    # Collect all flags and generate recommendations
    all_flags = []
    recommendations = []
    for check_name, result in check_results.items():
        all_flags.extend(result.flags)
        if result.flags:
            recommendations.append(
                f"{check_name}: {result.detail}"
            )

    # Generate audit trail record
    audit_id = f"aud_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
    latency_ms = int((time.time() - start) * 1000)

    # Store in the in-memory audit log
    audit_records[audit_id] = {
        "audit_id": audit_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user": None,
        "domain": request.domain.value,
        "model_used": None,
        "plugin": None,
        "trust_score": trust_score,
        "status": status,
        "checks_run": [c.value for c in request.checks],
        "flags_raised": len(all_flags),
        "human_review_required": status == "FLAG",
        "request_summary": request.input[:200],
        "response_summary": request.output[:200],
    }

    return VerifyResponse(
        trust_score=trust_score,
        status=status,
        checks=check_results,
        audit_id=audit_id,
        recommendations=recommendations,
        latency_ms=latency_ms,
    )
