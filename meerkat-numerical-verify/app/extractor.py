"""
Regex-based numerical value extraction from text.

Extracts numbers along with their surrounding context (what the number
refers to) so we can match "WBC 14.2" in the source to "WBC 16.8" in
the AI output, rather than randomly comparing unrelated numbers.

Each extracted number is a dict:
  {
    "value": 14.2,
    "raw": "14.2",
    "unit": "",
    "context": "WBC",
    "context_type": "lab_value",
    "position": 42,
  }
"""

import re
from dataclasses import dataclass, field


@dataclass
class ExtractedNumber:
    value: float
    raw: str                    # Original string, e.g., "14.2", "$4.2B", "50mg"
    unit: str                   # Detected unit: "mg", "%", "months", ""
    context: str                # Surrounding words for matching
    context_type: str           # Classified type: "medication_dose", "lab_value", etc.
    position: int               # Character offset in source text


# ── Context classifiers (what kind of number is this?) ─────────────

# Patterns that indicate the number is a medication dose
MEDICATION_PATTERNS = re.compile(
    r"\b(?:mg|mcg|µg|ug|g|ml|units?|iu|meq)\b"
    r"|"
    r"\b(?:dose|dosage|dosing|tid|bid|qid|qd|daily|twice|prn|po|iv|im|sq|sl|pr)\b",
    re.IGNORECASE,
)

LAB_VALUE_PATTERNS = re.compile(
    r"\b(?:WBC|RBC|Hgb|Hb|Hct|PLT|BUN|Cr|creatinine|Na|K|Cl|CO2|glucose|"
    r"troponin|BNP|procalcitonin|lactate|AST|ALT|ALP|GFR|eGFR|INR|PT|PTT|"
    r"A1c|HbA1c|TSH|T3|T4|CRP|ESR|albumin|bilirubin|lipase|amylase|"
    r"ferritin|iron|TIBC|folate|B12|magnesium|phosphorus|calcium|urate)\b",
    re.IGNORECASE,
)

VITAL_SIGN_PATTERNS = re.compile(
    r"\b(?:HR|heart\s+rate|BP|blood\s+pressure|SBP|DBP|systolic|diastolic|"
    r"SpO2|O2\s*sat|saturation|RR|resp(?:iratory)?\s+rate|temp(?:erature)?|"
    r"BMI|weight|height|MAP)\b",
    re.IGNORECASE,
)

DURATION_PATTERNS = re.compile(
    r"\b(?:day|days|week|weeks|month|months|year|years|hour|hours|"
    r"minute|minutes|duration|period|term)\b",
    re.IGNORECASE,
)

MONETARY_PATTERNS = re.compile(
    r"(?:[$€£¥]|USD|EUR|GBP|CAD|revenue|cost|price|salary|fee|"
    r"payment|amount|value|worth|damages|penalty|fine)\b",
    re.IGNORECASE,
)

PERCENTAGE_PATTERNS = re.compile(
    r"\b(?:%|percent|pct|margin|rate|ratio|yield|return|growth|"
    r"efficacy|sensitivity|specificity|probability|p-value|CI)\b",
    re.IGNORECASE,
)

AE_COUNT_PATTERNS = re.compile(
    r"\b(?:adverse|event|events|case|cases|incident|incidents|"
    r"occurrence|occurrences|patient|patients|subject|subjects|"
    r"death|deaths|SAE|AE|TEAE)\b",
    re.IGNORECASE,
)


def classify_context(context: str, unit: str) -> str:
    """Classify what type of number this is based on surrounding context."""
    combined = f"{context} {unit}"

    # Check more specific patterns first, then broader ones
    if MEDICATION_PATTERNS.search(combined):
        return "medication_dose"

    # For lab values vs vital signs: check the IMMEDIATE preceding word.
    # This prevents "SpO2" at the end of a context string from overriding
    # "WBC" at the start.
    # Extract the last few meaningful tokens before any number
    preceding = re.split(r"[\d.,%]+", context)[0].strip()
    if LAB_VALUE_PATTERNS.search(preceding):
        return "lab_value"
    if LAB_VALUE_PATTERNS.search(combined):
        return "lab_value"
    if AE_COUNT_PATTERNS.search(combined):
        return "adverse_event_count"
    if VITAL_SIGN_PATTERNS.search(combined):
        return "vital_sign"
    if MONETARY_PATTERNS.search(combined):
        return "monetary_value"
    if PERCENTAGE_PATTERNS.search(combined):
        return "percentage"
    if DURATION_PATTERNS.search(combined):
        return "duration_months"
    return "default"


# ── Main number extraction regex ───────────────────────────────────

# Matches patterns like:
#   14.2, 4,200, $4.2B, 50mg, 100%, 0.005, 120/80
NUMBER_PATTERN = re.compile(
    r"(?:[$€£¥]\s*)?"                           # Optional leading currency
    r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\.\d+)"    # The number itself (with commas, decimals)
    r"\s*"
    r"(%|"                                       # Percent sign
    r"mg|mcg|µg|ug|g|kg|ml|l|dl|cc|"            # Medical units
    r"mm|cm|m|km|miles?|"                        # Distance
    r"days?|weeks?|months?|years?|hours?|minutes?|"  # Time
    r"billion|million|thousand|bn|tn|"           # Multipliers
    r"units?|iu|meq|"                            # Medical units
    r"[BMKTbmkt])?"                              # Short multipliers
    r"(?=[\s,;.\-)\]:/FfMm]|$)",                # Lookahead: boundary (added F/M for 67F, 45M)
    re.IGNORECASE,
)

# 4-digit year pattern to avoid splitting years
YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")

# Blood pressure pattern: 120/80
BP_PATTERN = re.compile(
    r"\b(\d{2,3})\s*/\s*(\d{2,3})\b"
)


def get_context_window(text: str, position: int, window: int = 30) -> str:
    """Get surrounding words around a position in text."""
    start = max(0, position - window)
    end = min(len(text), position + window)
    return text[start:end].strip()


def extract_numbers(text: str) -> list[ExtractedNumber]:
    """
    Extract all numerical values from text with their context.

    Returns a list of ExtractedNumber objects, each containing:
    - The numeric value (float)
    - The raw string as it appeared
    - Any detected unit
    - Surrounding context for matching
    - Classified context type
    """
    results: list[ExtractedNumber] = []
    seen_positions: set[int] = set()

    # Extract blood pressure values (special case: 120/80)
    for match in BP_PATTERN.finditer(text):
        pos = match.start()
        if pos in seen_positions:
            continue

        systolic = float(match.group(1))
        diastolic = float(match.group(2))
        context = get_context_window(text, pos)

        results.append(ExtractedNumber(
            value=systolic,
            raw=match.group(1),
            unit="mmHg",
            context=context,
            context_type="vital_sign",
            position=pos,
        ))
        results.append(ExtractedNumber(
            value=diastolic,
            raw=match.group(2),
            unit="mmHg",
            context=context,
            context_type="vital_sign",
            position=pos + len(match.group(1)) + 1,
        ))

        # Mark positions in a range to avoid re-capture
        for p in range(pos, pos + len(match.group(0))):
            seen_positions.add(p)

    # Extract 4-digit years separately (to avoid splitting "2024" as "20" + "24")
    for match in YEAR_PATTERN.finditer(text):
        pos = match.start()
        if any(abs(pos - sp) < 5 for sp in seen_positions):
            continue

        year = float(match.group(1))
        context = get_context_window(text, pos)

        results.append(ExtractedNumber(
            value=year,
            raw=match.group(1),
            unit="year",
            context=context,
            context_type="default",
            position=pos,
        ))
        for p in range(pos, pos + len(match.group(0))):
            seen_positions.add(p)

    # Extract all other numbers
    for match in NUMBER_PATTERN.finditer(text):
        pos = match.start()

        # Skip if this position was already captured (e.g., BP, year)
        if any(abs(pos - sp) < 3 for sp in seen_positions):
            continue

        raw_number = match.group(1)
        unit = (match.group(2) or "").strip()

        # Parse the number (strip commas)
        try:
            value = float(raw_number.replace(",", ""))
        except ValueError:
            continue

        # Skip numbers that are clearly part of abbreviations
        # e.g., "SpO2" -> the "2" is not a standalone number
        # e.g., "T2DM" -> the "2" is not a standalone number
        pre_char = text[pos - 1] if pos > 0 else " "
        if pre_char.isalpha() and len(raw_number) <= 1:
            continue

        # Apply multiplier if unit is a multiplier (B, M, K, billion, etc.)
        multiplier_map = {
            "k": 1_000, "K": 1_000, "thousand": 1_000,
            "m": 1_000_000, "M": 1_000_000, "million": 1_000_000,
            "b": 1_000_000_000, "B": 1_000_000_000, "billion": 1_000_000_000,
            "bn": 1_000_000_000,
            "t": 1_000_000_000_000, "T": 1_000_000_000_000, "trillion": 1_000_000_000_000,
            "tn": 1_000_000_000_000,
        }
        if unit in multiplier_map:
            value *= multiplier_map[unit]
            unit = ""  # Multiplier consumed

        # Get surrounding context for matching (wider window)
        context = get_context_window(text, pos)

        # Get immediate context for classification (narrower -- just what's
        # directly before/after the number, to avoid SpO2 polluting WBC)
        immediate_start = max(0, pos - 15)
        immediate_end = min(len(text), pos + len(match.group(0)) + 10)
        immediate_context = text[immediate_start:immediate_end].strip()

        # Check for currency symbol before the number
        pre_text = text[max(0, pos - 3):pos]
        if re.search(r"[$€£¥]", pre_text):
            unit = unit or "$"

        # Classify the context type using IMMEDIATE context
        context_type = classify_context(immediate_context, unit)

        results.append(ExtractedNumber(
            value=value,
            raw=match.group(0).strip(),
            unit=unit,
            context=context,
            context_type=context_type,
            position=pos,
        ))
        seen_positions.add(pos)

    return results
