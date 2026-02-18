"""
Number matching and comparison between source and AI output.

Two-step process:
1. Match: Pair each AI output number with the most likely source number
   based on surrounding context similarity (not the numbers themselves).
2. Compare: Check if matched pairs are within domain-specific tolerances.

Also detects ungrounded numbers (numbers in AI output with no source match).
"""

import re
from dataclasses import dataclass

from .extractor import ExtractedNumber
from .domain_rules import get_tolerance_rule, ToleranceRule
from .normalizer import normalize_value


@dataclass
class NumberMatch:
    source: ExtractedNumber
    ai: ExtractedNumber
    match: bool                  # True if values are within tolerance
    deviation: float             # Relative deviation (0.0 = exact match)
    tolerance: float             # Applied tolerance threshold
    severity: str                # "critical" | "high" | "medium" | "low"
    detail: str                  # Human-readable explanation


@dataclass
class ComparisonResult:
    score: float                 # 0.0 (all wrong) to 1.0 (all correct)
    status: str                  # "pass" | "fail" | "warning"
    matches: list[NumberMatch]
    ungrounded: list[ExtractedNumber]   # AI numbers with no source match
    numbers_in_source: int
    numbers_in_ai: int
    critical_mismatches: int
    detail: str


def _context_similarity(a: "ExtractedNumber", b: "ExtractedNumber") -> float:
    """
    Similarity between two ExtractedNumbers for matching.
    Uses word overlap on context + specific label matching.
    """
    words_a = set(re.findall(r"[a-zA-Z]{2,}", a.context.lower()))
    words_b = set(re.findall(r"[a-zA-Z]{2,}", b.context.lower()))

    if not words_a or not words_b:
        return 0.0

    intersection = words_a & words_b
    union = words_a | words_b
    jaccard = len(intersection) / len(union)

    # Extract the immediate label before each number
    label_a = _extract_label(a.context, a.value, a.raw)
    label_b = _extract_label(b.context, b.value, b.raw)

    # Strong boost if the specific labels match
    if label_a and label_b and label_a == label_b:
        jaccard += 0.4

    return jaccard


def _extract_label(context: str, value: float = None, raw: str = None) -> str:
    """
    Extract the key label word closest to the number in the context.
    If value/raw are provided, finds the specific number in the context
    and returns the word immediately before it.
    """
    search_for = raw if raw else (str(value) if value is not None else None)

    if search_for and search_for in context:
        idx = context.index(search_for)
        pre_text = context[:idx].rstrip()
        words = re.findall(r"\b[a-zA-Z]{2,}\b", pre_text)
        if words:
            return words[-1].lower()

    # Fallback: find the last word before first digit
    digit_match = re.search(r"\d", context)
    if digit_match:
        pre_text = context[:digit_match.start()].rstrip()
        words = re.findall(r"\b[a-zA-Z]{2,}\b", pre_text)
        if words:
            return words[-1].lower()
    return ""


def _compute_deviation(source_val: float, ai_val: float) -> float:
    """Compute relative deviation between two numbers."""
    if source_val == 0 and ai_val == 0:
        return 0.0
    if source_val == 0:
        return 999.0  # Cap instead of inf to stay JSON-serializable
    return abs(ai_val - source_val) / abs(source_val)


def match_and_compare(
    source_numbers: list[ExtractedNumber],
    ai_numbers: list[ExtractedNumber],
    domain: str,
) -> ComparisonResult:
    """
    Match AI output numbers to source numbers and compare values.

    Strategy:
    1. For each AI number, find the source number with the highest
       context similarity (above a minimum threshold).
    2. If context types match (both "lab_value", both "medication_dose"),
       boost the match score.
    3. Compare matched pairs against domain-specific tolerances.
    4. Flag unmatched AI numbers as "ungrounded".
    """
    if not ai_numbers:
        return ComparisonResult(
            score=1.0,
            status="pass",
            matches=[],
            ungrounded=[],
            numbers_in_source=len(source_numbers),
            numbers_in_ai=0,
            critical_mismatches=0,
            detail="No numbers found in AI output to verify.",
        )

    if not source_numbers:
        # AI has numbers but source doesn't -- all are ungrounded
        return ComparisonResult(
            score=0.5,
            status="warning",
            matches=[],
            ungrounded=ai_numbers,
            numbers_in_source=0,
            numbers_in_ai=len(ai_numbers),
            critical_mismatches=0,
            detail=f"{len(ai_numbers)} number(s) in AI output but none in source to compare against.",
        )

    matches: list[NumberMatch] = []
    ungrounded: list[ExtractedNumber] = []
    used_source_indices: set[int] = set()
    critical_count = 0

    for ai_num in ai_numbers:
        best_source_idx = -1
        best_similarity = 0.3  # Minimum threshold to consider a match

        for i, src_num in enumerate(source_numbers):
            if i in used_source_indices:
                continue

            sim = _context_similarity(ai_num, src_num)

            # Boost if context types match
            if ai_num.context_type == src_num.context_type and ai_num.context_type != "default":
                sim += 0.2

            # Boost if units match
            if ai_num.unit and src_num.unit and ai_num.unit.lower() == src_num.unit.lower():
                sim += 0.15

            if sim > best_similarity:
                best_similarity = sim
                best_source_idx = i

        if best_source_idx == -1:
            ungrounded.append(ai_num)
            continue

        src_num = source_numbers[best_source_idx]
        used_source_indices.add(best_source_idx)

        # Normalize units before comparison
        src_val, src_unit = normalize_value(src_num.value, src_num.unit)
        ai_val, ai_unit = normalize_value(ai_num.value, ai_num.unit)

        # Get tolerance rule for this context type
        rule = get_tolerance_rule(domain, ai_num.context_type)
        deviation = _compute_deviation(src_val, ai_val)
        is_match = deviation <= rule.tolerance

        if not is_match and rule.severity == "critical":
            critical_count += 1

        matches.append(NumberMatch(
            source=src_num,
            ai=ai_num,
            match=is_match,
            deviation=round(deviation, 4),
            tolerance=rule.tolerance,
            severity=rule.severity,
            detail=(
                f"{ai_num.context_type}: source={src_num.raw} ({src_num.context_type}), "
                f"ai={ai_num.raw}, deviation={deviation:.1%}, "
                f"tolerance={rule.tolerance:.1%}, "
                f"{'PASS' if is_match else 'FAIL (' + rule.severity + ')'}"
            ),
        ))

    # Compute overall score
    if not matches:
        score = 0.5 if ungrounded else 1.0
    else:
        passing = sum(1 for m in matches if m.match)
        score = passing / len(matches)

    # Determine status
    if critical_count > 0:
        status = "fail"
    elif score < 0.5:
        status = "fail"
    elif score < 1.0 or ungrounded:
        status = "warning"
    else:
        status = "pass"

    # Build detail string
    passing = sum(1 for m in matches if m.match)
    failing = len(matches) - passing
    detail_parts = [f"{len(matches)} matched pair(s): {passing} pass, {failing} fail."]
    if ungrounded:
        detail_parts.append(f"{len(ungrounded)} ungrounded number(s) in AI output.")
    if critical_count > 0:
        detail_parts.append(f"{critical_count} CRITICAL mismatch(es).")

    return ComparisonResult(
        score=round(score, 4),
        status=status,
        matches=matches,
        ungrounded=ungrounded,
        numbers_in_source=len(source_numbers),
        numbers_in_ai=len(ai_numbers),
        critical_mismatches=critical_count,
        detail=" ".join(detail_parts),
    )
