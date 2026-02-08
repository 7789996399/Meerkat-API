"""
POST /v1/shield -- Prompt injection detection.

Pre-flight scan of user input BEFORE it reaches the AI model.
Catches direct injection, jailbreak attempts, and policy violations.

DEMO MODE: Uses pattern matching against known injection phrases.
Production would use a fine-tuned classifier (distilbert or similar).
"""

import re

from fastapi import APIRouter

from api.models.schemas import ShieldRequest, ShieldResponse

router = APIRouter()

# ---------------------------------------------------------------------------
# Known injection patterns (demo mode)
#
# Each tuple is (pattern, attack_type, severity, description)
# Severity helps rank the seriousness of each match.
# ---------------------------------------------------------------------------

INJECTION_PATTERNS: list[tuple[str, str, str, str]] = [
    # Direct instruction overrides
    (r"ignore\s+(all\s+)?previous\s+instructions", "direct_injection", "HIGH",
     "Attempts to override the model's instructions."),
    (r"forget\s+(all\s+)?(your\s+)?instructions", "direct_injection", "HIGH",
     "Attempts to clear the model's instructions."),
    (r"disregard\s+(all\s+)?(previous|prior|above)", "direct_injection", "HIGH",
     "Attempts to disregard prior instructions."),
    (r"do\s+not\s+follow\s+(your|any|the|previous)", "direct_injection", "HIGH",
     "Attempts to prevent the model from following instructions."),
    (r"override\s+(your|all|any|the)\s+(rules|instructions|guidelines)", "direct_injection", "HIGH",
     "Attempts to override the model's rules."),
    (r"bypass\s+(your|all|any|the)\s+(rules|filters|restrictions|safety)", "direct_injection", "HIGH",
     "Attempts to bypass safety mechanisms."),

    # Role manipulation
    (r"you\s+are\s+now\s+", "role_manipulation", "MEDIUM",
     "Attempts to reassign the model's role."),
    (r"act\s+as\s+(if\s+you\s+are|a|an)\s+", "role_manipulation", "MEDIUM",
     "Attempts to make the model assume a different identity."),
    (r"pretend\s+(you\s+are|to\s+be)\s+", "role_manipulation", "MEDIUM",
     "Attempts role-play to bypass safety measures."),
    (r"from\s+now\s+on\s+you\s+(are|will|must|should)", "role_manipulation", "MEDIUM",
     "Attempts to permanently alter the model's behavior."),

    # System prompt extraction
    (r"(show|reveal|display|print|output)\s+(me\s+)?(your\s+)?(system\s+)?prompt", "prompt_extraction", "HIGH",
     "Attempts to extract the system prompt."),
    (r"what\s+(are|is)\s+your\s+(system\s+)?instructions", "prompt_extraction", "MEDIUM",
     "Attempts to extract the model's instructions."),
    (r"repeat\s+(your\s+)?(system\s+)?(prompt|instructions)", "prompt_extraction", "HIGH",
     "Attempts to make the model repeat its instructions."),
    (r"(show|reveal)\s+(your\s+)?system\s+message", "prompt_extraction", "HIGH",
     "Attempts to extract the system message."),

    # Jailbreak patterns
    (r"do\s+anything\s+now", "jailbreak", "HIGH",
     "Contains a known jailbreak pattern (DAN)."),
    (r"developer\s+mode", "jailbreak", "HIGH",
     "Attempts to enable a fake developer mode."),
    (r"no\s+restrictions", "jailbreak", "HIGH",
     "Attempts to remove safety restrictions."),
    (r"without\s+(any\s+)?(restrictions|limitations|rules|filters)", "jailbreak", "MEDIUM",
     "Attempts to operate without safety restrictions."),

    # Indirect injection techniques
    (r"translate\s+the\s+(above|previous|following)\s+", "indirect_injection", "LOW",
     "Possible indirect injection via translation request."),
    (r"summarize\s+the\s+(above|previous)\s+(text|instructions|message)", "indirect_injection", "LOW",
     "Possible indirect injection via summarization request."),
]

# Additional heuristic checks for "high" sensitivity
HIGH_SENSITIVITY_EXTRAS: list[tuple[str, str, str, str]] = [
    (r"<\s*/?script", "code_injection", "MEDIUM",
     "Input contains script tags."),
    (r"\{\{.*\}\}", "template_injection", "MEDIUM",
     "Input contains template syntax."),
    (r"%7B%7B", "template_injection", "MEDIUM",
     "Input contains URL-encoded template syntax."),
    # Base64 detection: look for long runs of base64 characters
    (r"[A-Za-z0-9+/]{40,}={0,2}", "obfuscation", "MEDIUM",
     "Input contains a possible base64-encoded payload."),
]

# Sensitivity thresholds: how many patterns need to match to trigger each level
SENSITIVITY_THRESHOLDS = {
    "low": 2,     # need 2+ matches to flag
    "medium": 1,  # any single match flags
    "high": 1,    # any match flags, plus extra heuristic checks
}

# Severity rankings for ordering
SEVERITY_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


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

    # Collect all matching patterns with their severity
    matches: list[tuple[str, str, str]] = []  # (attack_type, severity, description)

    for pattern, attack_type, severity, description in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            matches.append((attack_type, severity, description))

    # High sensitivity adds extra heuristic checks
    if request.sensitivity == "high":
        for pattern, attack_type, severity, description in HIGH_SENSITIVITY_EXTRAS:
            if re.search(pattern, text, re.IGNORECASE):
                matches.append((attack_type, severity, description))

    # Apply sensitivity threshold
    threshold = SENSITIVITY_THRESHOLDS[request.sensitivity]

    if len(matches) >= threshold:
        # Sort matches by severity (highest first)
        matches.sort(key=lambda m: SEVERITY_RANK.get(m[1], 0), reverse=True)

        primary_attack = matches[0][0]
        primary_severity = matches[0][1]
        primary_detail = matches[0][2]

        # Determine overall threat level from the worst match
        max_severity = max(SEVERITY_RANK.get(m[1], 0) for m in matches)
        if max_severity >= 3 or len(matches) >= 3:
            threat_level = "HIGH"
            action = "BLOCK"
        elif max_severity >= 2 or len(matches) >= 2:
            threat_level = "MEDIUM"
            action = "BLOCK"
        else:
            threat_level = "LOW"
            action = "FLAG"

        # Build a detailed explanation
        detail_parts = [f"{primary_detail} (Severity: {primary_severity}.)"]
        if len(matches) > 1:
            detail_parts.append(f"{len(matches)} total threat pattern(s) detected.")
            # List the attack types found
            attack_types = sorted(set(m[0] for m in matches))
            detail_parts.append(f"Types: {', '.join(attack_types)}.")

        # Attempt to produce a sanitized version
        sanitized = text
        for pattern, _, _, _ in INJECTION_PATTERNS:
            sanitized = re.sub(pattern, "[REMOVED]", sanitized, flags=re.IGNORECASE)
        sanitized = sanitized.strip()

        has_useful_content = len(sanitized.replace("[REMOVED]", "").strip()) > 10
        sanitized_input = sanitized if has_useful_content else None

        return ShieldResponse(
            safe=False,
            threat_level=threat_level,
            attack_type=primary_attack,
            detail=" ".join(detail_parts),
            action=action,
            sanitized_input=sanitized_input,
        )

    # No threats detected
    return ShieldResponse(
        safe=True,
        threat_level="NONE",
        attack_type=None,
        detail="Input passed all threat checks. No injection patterns detected.",
        action="ALLOW",
        sanitized_input=None,
    )
