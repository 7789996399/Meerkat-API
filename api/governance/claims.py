"""
Claim Extraction and Verification

Calls the real claim-extractor microservice (meerkat-claims on port 8002)
which uses spaCy en_core_web_trf for NER-based claim extraction and
entity cross-referencing for hallucination detection.

Falls back to a local regex heuristic if the microservice is unavailable.
"""

import logging
import os
import re

import httpx

from api.models.schemas import ClaimCheckResult

logger = logging.getLogger(__name__)

CLAIMS_SERVICE_URL = os.getenv("CLAIMS_SERVICE_URL", "http://localhost:8002")


async def check_claims(output: str, context: str | None) -> ClaimCheckResult:
    """Run claim extraction via the real ML microservice.

    Falls back to the local heuristic if the service is unreachable.
    """
    if not context:
        return ClaimCheckResult(
            score=0.5,
            flags=["no_context_provided"],
            detail="No source document provided. Claims cannot be verified.",
            claims=0,
            verified=0,
            unverified=0,
        )

    url = f"{CLAIMS_SERVICE_URL}/extract"
    payload = {
        "ai_output": output,
        "source": context,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()

        data = resp.json()
        return _map_service_response(data)

    except Exception as e:
        logger.warning(
            "Claims microservice unavailable (%s), falling back to heuristic",
            e,
        )
        return _check_claims_heuristic(output, context)


def _map_service_response(data: dict) -> ClaimCheckResult:
    """Map the microservice JSON response to a ClaimCheckResult."""
    total = data["total_claims"]
    verified = data["verified"]
    contradicted = data["contradicted"]
    unverified = data["unverified"]
    flags = data.get("flags", [])
    hallucinated = data.get("hallucinated_entities", [])

    # Score = verified / total (0 if no claims)
    score = round(verified / total, 3) if total > 0 else 0.0

    # Build detail message
    parts = [f"Extracted {total} factual claim(s) (spaCy NER)."]
    parts.append(f"{verified} verified, {unverified} unverified, {contradicted} contradicted.")
    if contradicted > 0:
        parts.append("Source document contradicts one or more claims.")
    if hallucinated:
        parts.append(f"Hallucinated entities detected: {', '.join(hallucinated[:5])}.")

    return ClaimCheckResult(
        score=score,
        flags=flags,
        detail=" ".join(parts),
        claims=total,
        verified=verified,
        unverified=unverified,
    )


# ── Heuristic fallback (regex-based, no ML) ───────────────────────

def _extract_claims_heuristic(output: str) -> list[dict]:
    """Extract structured claims via regex patterns."""
    claims: list[dict] = []

    for match in re.finditer(r'(\d+)[\s-]*(day|week|month|year|mile)s?', output, re.IGNORECASE):
        claims.append({"text": match.group(0), "type": "duration", "value": match.group(1), "unit": match.group(2).lower()})

    for match in re.finditer(r'\$[\d,]+(?:\.\d+)?', output):
        claims.append({"text": match.group(0), "type": "monetary", "value": match.group(0), "unit": "dollars"})

    for match in re.finditer(r'(\d+(?:\.\d+)?)\s*%', output):
        claims.append({"text": match.group(0), "type": "percentage", "value": match.group(1), "unit": "percent"})

    for match in re.finditer(r'(?:Section|Clause|Article)\s+(\d+(?:\.\d+)*)', output, re.IGNORECASE):
        claims.append({"text": match.group(0), "type": "section_ref", "value": match.group(1), "unit": "section"})

    geo_patterns = [
        (r'(?:all\s+of\s+)?North\s+America', "North America"),
        (r'British\s+Columbia', "British Columbia"),
        (r'Vancouver(?:,\s*BC)?', "Vancouver"),
        (r'(?:United\s+States|Canada)', None),
    ]
    for pattern, label in geo_patterns:
        m = re.search(pattern, output, re.IGNORECASE)
        if m:
            text = label or m.group(0)
            claims.append({"text": text, "type": "geographic", "value": text, "unit": "location"})

    return claims


def _verify_claim_heuristic(claim: dict, context: str) -> str:
    """Verify a single claim against context via text matching."""
    context_lower = context.lower()
    claim_value = claim["value"]
    claim_unit = claim["unit"]

    if claim["type"] == "duration":
        unit = claim_unit
        unit_matches = list(re.finditer(
            rf'(\w+)\s*\((\d+)\)\s*{unit}s?|(\d+)[\s-]*{unit}s?',
            context_lower,
        ))
        if not unit_matches:
            return "unverified"
        for m in unit_matches:
            context_value = m.group(2) or m.group(3)
            if context_value == claim_value:
                return "verified"
        return "contradicted"

    elif claim["type"] == "monetary":
        if claim_value.lower() in context_lower:
            return "verified"
        if re.search(r'\$[\d,]+', context):
            return "contradicted"
        return "unverified"

    elif claim["type"] == "section_ref":
        ref = claim["value"]
        if ref in context or f"section {ref}".lower() in context_lower:
            return "verified"
        return "unverified"

    elif claim["type"] == "geographic":
        if claim["value"].lower() in context_lower:
            return "verified"
        geo_terms = ["north america", "british columbia", "vancouver", "canada", "united states"]
        context_geos = [g for g in geo_terms if g in context_lower]
        if context_geos and claim["value"].lower() not in context_geos:
            return "contradicted"
        return "unverified"

    else:
        if claim_value.lower() in context_lower:
            return "verified"
        return "unverified"


def _check_claims_heuristic(output: str, context: str) -> ClaimCheckResult:
    """Heuristic fallback: regex extraction + text matching."""
    claims = _extract_claims_heuristic(output)

    if not claims:
        return ClaimCheckResult(
            score=0.7,
            flags=[],
            detail="No specific factual claims detected in the output. (heuristic -- claims service unavailable)",
            claims=0,
            verified=0,
            unverified=0,
        )

    verified_count = 0
    contradicted_count = 0
    unverified_count = 0
    flags: list[str] = []

    for claim in claims:
        status = _verify_claim_heuristic(claim, context)
        if status == "verified":
            verified_count += 1
        elif status == "contradicted":
            contradicted_count += 1
            flags.append(f"claim: '{claim['text']}' contradicts source")
        else:
            unverified_count += 1
            flags.append(f"claim: '{claim['text']}' not found in source")

    total = len(claims)
    if total > 0:
        verified_ratio = verified_count / total
        contradiction_penalty = contradicted_count * 0.25
        unverified_penalty = unverified_count * 0.05
        score = max(0.0, min(1.0, verified_ratio - contradiction_penalty - unverified_penalty))
    else:
        score = 0.7

    score = round(score, 3)

    parts = [f"Extracted {total} factual claim(s)."]
    parts.append(f"{verified_count} verified, {unverified_count} unverified, {contradicted_count} contradicted.")
    if contradicted_count > 0:
        parts.append("Source document contradicts one or more claims.")
    detail = " ".join(parts) + " (heuristic -- claims service unavailable)"

    return ClaimCheckResult(
        score=score,
        flags=flags,
        detail=detail,
        claims=total,
        verified=verified_count,
        unverified=unverified_count,
    )
