"""
Claim Extraction and Verification (demo mode)

Extracts specific factual claims from the AI's output and cross-references
each one against the source document.

HOW IT WORKS:
  1. Scan the output for claim-like patterns:
     - Dollar amounts ($500,000)
     - Durations (12-month, 30 days, 2 years)
     - Percentages (50%)
     - Section references (Section 3.1)
     - Geographic scopes (North America, British Columbia)
     - Named entities (Acme Corp, TechStart Inc)
  2. For each extracted claim, search the context for it
  3. Classify each claim as:
     - VERIFIED: the exact fact appears in the source
     - CONTRADICTED: a different fact for the same topic appears
     - UNVERIFIED: the claim can't be found in the source at all

PRODUCTION MODE:
  Would use a fine-tuned T5-small for structured claim parsing,
  then per-claim DeBERTa entailment verification.
"""

import re

from api.models.schemas import ClaimCheckResult


def _extract_claims(output: str) -> list[dict]:
    """Extract structured claims from the output text.
    Returns a list of dicts with 'text' (the claim) and 'type' (category)."""

    claims: list[dict] = []

    # Duration claims: "12-month", "30 days", "2 years", "5-year", etc.
    for match in re.finditer(r'(\d+)[\s-]*(day|week|month|year|mile)s?', output, re.IGNORECASE):
        full = match.group(0)
        claims.append({"text": full, "type": "duration", "value": match.group(1), "unit": match.group(2).lower()})

    # Dollar amounts
    for match in re.finditer(r'\$[\d,]+(?:\.\d+)?', output):
        claims.append({"text": match.group(0), "type": "monetary", "value": match.group(0), "unit": "dollars"})

    # Percentages
    for match in re.finditer(r'(\d+(?:\.\d+)?)\s*%', output):
        claims.append({"text": match.group(0), "type": "percentage", "value": match.group(1), "unit": "percent"})

    # Section references
    for match in re.finditer(r'(?:Section|Clause|Article)\s+(\d+(?:\.\d+)*)', output, re.IGNORECASE):
        claims.append({"text": match.group(0), "type": "section_ref", "value": match.group(1), "unit": "section"})

    # Geographic scope claims
    geo_patterns = [
        (r'(?:all\s+of\s+)?North\s+America', "North America"),
        (r'British\s+Columbia', "British Columbia"),
        (r'Vancouver(?:,\s*BC)?', "Vancouver"),
        (r'(?:United\s+States|Canada)', None),
    ]
    for pattern, label in geo_patterns:
        if re.search(pattern, output, re.IGNORECASE):
            text = label or re.search(pattern, output, re.IGNORECASE).group(0)
            claims.append({"text": text, "type": "geographic", "value": text, "unit": "location"})

    return claims


def _verify_claim(claim: dict, context: str) -> str:
    """Verify a single claim against the context.
    Returns 'verified', 'contradicted', or 'unverified'."""

    context_lower = context.lower()
    claim_value = claim["value"]
    claim_unit = claim["unit"]

    if claim["type"] == "duration":
        # Look for the same unit in context
        unit = claim_unit
        # Search for any number near this unit in the context
        unit_matches = list(re.finditer(
            rf'(\w+)\s*\((\d+)\)\s*{unit}s?|(\d+)[\s-]*{unit}s?',
            context_lower
        ))
        if not unit_matches:
            # Unit not found in context at all
            return "unverified"

        # Check if the specific number appears near this unit
        for m in unit_matches:
            context_value = m.group(2) or m.group(3)
            if context_value == claim_value:
                return "verified"
        # Found the unit but with a different number -- contradiction
        return "contradicted"

    elif claim["type"] == "monetary":
        # Check if this dollar amount exists in context
        if claim_value.lower() in context_lower:
            return "verified"
        # Check if ANY dollar amount exists (would indicate a mismatch)
        if re.search(r'\$[\d,]+', context):
            return "contradicted"
        return "unverified"

    elif claim["type"] == "section_ref":
        # Check if this section number appears in context
        ref = claim["value"]
        if ref in context or f"section {ref}".lower() in context_lower:
            return "verified"
        return "unverified"

    elif claim["type"] == "geographic":
        # Check if this geographic term appears in context
        if claim["value"].lower() in context_lower:
            return "verified"
        # Check if a DIFFERENT geographic scope appears (contradiction)
        # e.g., output says "North America" but context says "British Columbia"
        geo_terms = ["north america", "british columbia", "vancouver", "canada", "united states"]
        context_geos = [g for g in geo_terms if g in context_lower]
        if context_geos and claim["value"].lower() not in context_geos:
            return "contradicted"
        return "unverified"

    else:
        # Generic claim -- simple text match
        if claim_value.lower() in context_lower:
            return "verified"
        return "unverified"


def check_claims(output: str, context: str | None) -> ClaimCheckResult:
    """Run claim extraction and verification.
    Returns a ClaimCheckResult with per-claim details."""

    if not context:
        return ClaimCheckResult(
            score=0.5,
            flags=["no_context_provided"],
            detail="No source document provided. Claims cannot be verified.",
            claims=0,
            verified=0,
            unverified=0,
        )

    claims = _extract_claims(output)

    if not claims:
        return ClaimCheckResult(
            score=0.7,
            flags=[],
            detail="No specific factual claims detected in the output.",
            claims=0,
            verified=0,
            unverified=0,
        )

    # Verify each claim
    verified_count = 0
    contradicted_count = 0
    unverified_count = 0
    flags: list[str] = []

    for claim in claims:
        status = _verify_claim(claim, context)
        if status == "verified":
            verified_count += 1
        elif status == "contradicted":
            contradicted_count += 1
            flags.append(f"claim: '{claim['text']}' contradicts source")
        else:
            unverified_count += 1
            flags.append(f"claim: '{claim['text']}' not found in source")

    total = len(claims)

    # Score: verified claims are good, contradictions are very bad
    if total > 0:
        verified_ratio = verified_count / total
        contradiction_penalty = contradicted_count * 0.25
        unverified_penalty = unverified_count * 0.05
        score = max(0.0, min(1.0, verified_ratio - contradiction_penalty - unverified_penalty))
    else:
        score = 0.7

    score = round(score, 3)

    # Build detail message
    parts = [f"Extracted {total} factual claim(s)."]
    parts.append(f"{verified_count} verified, {unverified_count} unverified, {contradicted_count} contradicted.")
    if contradicted_count > 0:
        parts.append("Source document contradicts one or more claims.")

    return ClaimCheckResult(
        score=score,
        flags=flags,
        detail=" ".join(parts),
        claims=total,
        verified=verified_count,
        unverified=unverified_count,
    )
