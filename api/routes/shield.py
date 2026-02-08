"""
POST /v1/shield -- Prompt injection detection.

Pre-flight scan of user input BEFORE it reaches the AI model.
Catches direct injection, jailbreak attempts, and policy violations.

DEMO MODE: Uses pattern matching against known injection phrases.
Production would use a fine-tuned classifier (distilbert or similar).
"""

import re

from fastapi import APIRouter

from api.models.schemas import DomainType, ShieldRequest, ShieldResponse

router = APIRouter()

# ---------------------------------------------------------------------------
# Known injection patterns (demo mode)
#
# These are common prompt injection / jailbreak patterns. In production,
# a trained classifier would catch novel attacks too. For the demo,
# pattern matching is good enough to show the concept.
# ---------------------------------------------------------------------------

# Each tuple is (pattern, attack_type, description)
INJECTION_PATTERNS: list[tuple[str, str, str]] = [
    # Direct instruction overrides
    (r"ignore\s+(all\s+)?previous\s+instructions", "direct_injection",
     "Input attempts to override the model's instructions."),
    (r"forget\s+(all\s+)?(your\s+)?instructions", "direct_injection",
     "Input attempts to clear the model's instructions."),
    (r"disregard\s+(all\s+)?(previous|prior|above)", "direct_injection",
     "Input attempts to disregard prior instructions."),

    # Role manipulation
    (r"you\s+are\s+now\s+", "role_manipulation",
     "Input attempts to reassign the model's role."),
    (r"act\s+as\s+(if\s+you\s+are|a|an)\s+", "role_manipulation",
     "Input attempts to make the model assume a different identity."),
    (r"pretend\s+(you\s+are|to\s+be)\s+", "role_manipulation",
     "Input attempts role-play to bypass safety measures."),

    # System prompt extraction
    (r"(show|reveal|display|print|output)\s+(me\s+)?(your\s+)?(system\s+)?prompt", "prompt_extraction",
     "Input attempts to extract the system prompt."),
    (r"what\s+(are|is)\s+your\s+(system\s+)?instructions", "prompt_extraction",
     "Input attempts to extract the model's instructions."),
    (r"repeat\s+(your\s+)?(system\s+)?(prompt|instructions)", "prompt_extraction",
     "Input attempts to make the model repeat its instructions."),

    # Jailbreak patterns
    (r"do\s+anything\s+now", "jailbreak",
     "Input contains a known jailbreak pattern (DAN)."),
    (r"developer\s+mode", "jailbreak",
     "Input attempts to enable a fake developer mode."),
    (r"no\s+restrictions", "jailbreak",
     "Input attempts to remove safety restrictions."),
]

# Sensitivity multipliers: how many patterns need to match to trigger each level
SENSITIVITY_THRESHOLDS = {
    "low": 2,     # need 2+ matches to flag
    "medium": 1,  # any single match flags
    "high": 1,    # any match flags, plus extra heuristic checks
}

# Additional heuristic checks for "high" sensitivity
HIGH_SENSITIVITY_EXTRAS: list[tuple[str, str, str]] = [
    (r"<\s*/?script", "code_injection", "Input contains script tags."),
    (r"\{\{.*\}\}", "template_injection", "Input contains template syntax."),
    (r"{{|%7B%7B", "template_injection", "Input contains encoded template syntax."),
]


@router.post(
    "/v1/shield",
    response_model=ShieldResponse,
    summary="Scan input for prompt injection",
    description=(
        "Pre-flight security check. Scan user input BEFORE it reaches the AI model. "
        "Detects direct injection, jailbreak attempts, role manipulation, "
        "and prompt extraction attacks."
    ),
    tags=["Security"],
)
async def shield(request: ShieldRequest) -> ShieldResponse:
    text = request.input
    text_lower = text.lower()

    # Collect all matching patterns
    matches: list[tuple[str, str]] = []  # (attack_type, description)

    for pattern, attack_type, description in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            matches.append((attack_type, description))

    # High sensitivity adds extra heuristic checks
    if request.sensitivity == "high":
        for pattern, attack_type, description in HIGH_SENSITIVITY_EXTRAS:
            if re.search(pattern, text_lower):
                matches.append((attack_type, description))

    # Apply sensitivity threshold
    threshold = SENSITIVITY_THRESHOLDS[request.sensitivity]

    if len(matches) >= threshold:
        # Threat detected
        primary_attack = matches[0][0]
        primary_detail = matches[0][1]

        # Determine severity based on number and type of matches
        if len(matches) >= 3 or primary_attack == "jailbreak":
            threat_level = "HIGH"
            action = "BLOCK"
        elif len(matches) >= 2 or primary_attack == "direct_injection":
            threat_level = "MEDIUM"
            action = "BLOCK"
        else:
            threat_level = "LOW"
            action = "FLAG"

        # Attempt to produce a sanitized version by removing the injection
        sanitized = text
        for pattern, _, _ in INJECTION_PATTERNS:
            sanitized = re.sub(pattern, "[REMOVED]", sanitized, flags=re.IGNORECASE)
        sanitized = sanitized.strip()

        # Only offer sanitized input if something useful remains
        has_useful_content = len(sanitized.replace("[REMOVED]", "").strip()) > 10
        sanitized_input = sanitized if has_useful_content else None

        return ShieldResponse(
            safe=False,
            threat_level=threat_level,
            attack_type=primary_attack,
            detail=f"{primary_detail} ({len(matches)} pattern(s) matched.)",
            action=action,
            sanitized_input=sanitized_input,
        )

    # No threats detected
    return ShieldResponse(
        safe=True,
        threat_level="NONE",
        attack_type=None,
        detail="Input passed all threat checks.",
        action="ALLOW",
        sanitized_input=None,
    )
