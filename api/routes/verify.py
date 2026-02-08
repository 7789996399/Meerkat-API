"""
POST /v1/verify -- Real-time AI output verification.

This is the core endpoint. A client sends an AI model's input and output,
and Meerkat runs governance checks and returns a trust score.

The governance checks live in api/governance/ -- one module per check.
This file handles the routing, scoring, and audit trail.
"""

import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter

from api.governance.claims import check_claims
from api.governance.entailment import check_entailment
from api.governance.entropy import check_entropy
from api.governance.preference import check_preference
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
# Scoring weights
#
# Entailment is weighted highest because hallucination detection is the
# most critical governance function in regulated industries. If the AI
# contradicts the source document, that's the #1 risk.
# ---------------------------------------------------------------------------

WEIGHTS = {
    "entailment": 0.40,           # Does the output match the source? (most important)
    "semantic_entropy": 0.25,     # How confident is the model?
    "implicit_preference": 0.20,  # Is the model showing bias?
    "claim_extraction": 0.15,     # Are factual claims verifiable?
}

# Status thresholds
PASS_THRESHOLD = 75   # trust_score >= 75 -> PASS
FLAG_THRESHOLD = 45   # trust_score >= 45 -> FLAG, below -> BLOCK


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
        check_results["entailment"] = check_entailment(request.output, request.context)

    if GovernanceCheck.semantic_entropy in request.checks:
        check_results["semantic_entropy"] = check_entropy(request.output)

    if GovernanceCheck.implicit_preference in request.checks:
        check_results["implicit_preference"] = check_preference(request.output)

    if GovernanceCheck.claim_extraction in request.checks:
        check_results["claim_extraction"] = check_claims(request.output, request.context)

    # Compute weighted trust score
    if check_results:
        weighted_sum = 0.0
        total_weight = 0.0
        for check_name, result in check_results.items():
            weight = WEIGHTS.get(check_name, 0.25)
            weighted_sum += result.score * weight
            total_weight += weight
        trust_score = int(round((weighted_sum / total_weight) * 100))
    else:
        trust_score = 50

    # Determine governance decision
    if trust_score >= PASS_THRESHOLD:
        status = "PASS"
    elif trust_score >= FLAG_THRESHOLD:
        status = "FLAG"
    else:
        status = "BLOCK"

    # Collect all flags and generate recommendations
    all_flags: list[str] = []
    recommendations: list[str] = []
    for check_name, result in check_results.items():
        all_flags.extend(result.flags)
        if result.flags:
            recommendations.append(f"{check_name}: {result.detail}")

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
