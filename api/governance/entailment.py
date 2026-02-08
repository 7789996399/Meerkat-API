"""
Entailment Check (DeBERTa NLI -- demo mode)

Checks whether the AI's output is logically supported by the source
document. This is the primary hallucination detector.

HOW IT WORKS (demo mode):
  1. Split the AI output into sentences
  2. Extract "claim-like" fragments: sentences with numbers, dates,
     durations, legal references, or proper nouns
  3. For each claim, search the context for matching or contradicting
     evidence by comparing key terms (especially numbers)
  4. A claim is SUPPORTED if its key numbers/terms appear in context
  5. A claim is CONTRADICTED if a different number appears in the
     same context (e.g., output says "90 days", context says "30 days")
  6. Score = fraction of supported claims, with heavy penalties for
     contradictions

PRODUCTION MODE:
  Would use microsoft/deberta-v3-large fine-tuned on NLI pairs,
  exported to ONNX for ~50ms per claim pair.
"""

import re

from api.models.schemas import CheckResult


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences. Handles abbreviations like 'Inc.' and 'Corp.'"""
    # Protect common abbreviations from splitting
    protected = text.replace("Inc.", "Inc_").replace("Corp.", "Corp_")
    protected = protected.replace("Dr.", "Dr_").replace("Mr.", "Mr_")
    protected = protected.replace("Ms.", "Ms_").replace("Blvd.", "Blvd_")
    protected = protected.replace("St.", "St_").replace("B.C.", "BC_")
    sentences = re.split(r'[.!?]+\s+', protected)
    return [s.replace("_", ".").strip() for s in sentences if s.strip()]


def _extract_numbers(text: str) -> list[str]:
    """Extract all number-like tokens from text: digits, dollar amounts,
    percentages, durations expressed as words (e.g., 'twelve')."""
    # Digit-based numbers
    numbers = re.findall(r'\$[\d,]+(?:\.\d+)?|\d+(?:\.\d+)?%|\d+', text)
    # Word-form numbers that commonly appear in legal docs
    word_numbers = {
        "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
        "twelve": "12", "fifteen": "15", "twenty": "20", "thirty": "30",
        "fifty": "50", "sixty": "60", "ninety": "90", "hundred": "100",
    }
    for word, digit in word_numbers.items():
        if word in text.lower():
            numbers.append(digit)
    return numbers


def _find_context_window(term: str, context: str, window: int = 200) -> str | None:
    """Find the chunk of context surrounding a term. Returns None if not found."""
    idx = context.lower().find(term.lower())
    if idx == -1:
        return None
    start = max(0, idx - window)
    end = min(len(context), idx + len(term) + window)
    return context[start:end]


def check_entailment(output: str, context: str | None) -> CheckResult:
    """Run the entailment check. Returns a CheckResult with score 0.0-1.0."""

    if not context:
        return CheckResult(
            score=0.5,
            flags=["no_context_provided"],
            detail="No source document provided. Entailment check requires context for accurate scoring.",
        )

    sentences = _split_sentences(output)
    context_lower = context.lower()

    supported = 0
    contradicted = 0
    neutral = 0
    flags: list[str] = []
    total_checked = 0

    for sentence in sentences:
        if len(sentence.split()) < 4:
            continue  # skip trivially short fragments

        # Extract numbers and key terms from this sentence
        sentence_numbers = _extract_numbers(sentence)
        # Also grab duration phrases like "12-month" or "30 days"
        duration_phrases = re.findall(
            r'(\d+)[\s-]*(day|week|month|year|mile)s?', sentence, re.IGNORECASE
        )
        # Section references (use \d+(?:\.\d+)* to avoid capturing trailing periods)
        section_refs = re.findall(r'(?:Section|Clause|Article)\s+(\d+(?:\.\d+)*)', sentence, re.IGNORECASE)

        # If this sentence has no checkable facts, skip it
        if not sentence_numbers and not duration_phrases and not section_refs:
            continue

        total_checked += 1
        sentence_supported = True
        sentence_contradicted = False

        # Check each duration phrase (most important for legal docs)
        for value, unit in duration_phrases:
            unit_lower = unit.lower()
            # Find where this unit appears in context
            unit_window = _find_context_window(unit_lower, context)
            if unit_window:
                # Get numbers near this unit in the context
                context_numbers = _extract_numbers(unit_window)
                if value in context_numbers:
                    # Exact match -- supported
                    pass
                elif context_numbers:
                    # Different number near same unit -- contradiction
                    sentence_contradicted = True
                    sentence_supported = False
                    flags.append(f"contradiction: '{value} {unit_lower}s' vs source")
                else:
                    sentence_supported = False
            else:
                # Unit not mentioned in context at all
                sentence_supported = False

        # Check section references
        for ref in section_refs:
            if f"section {ref}".lower() not in context_lower and ref not in context_lower:
                # References a section that doesn't exist
                sentence_supported = False

        # Check if key proper nouns from the sentence appear in context
        proper_nouns = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', sentence)
        for noun in proper_nouns:
            if len(noun) > 3 and noun.lower() not in context_lower:
                # References an entity not in the document
                if noun not in ("The", "This", "That", "These", "Section", "Clause"):
                    sentence_supported = False

        if sentence_contradicted:
            contradicted += 1
        elif sentence_supported:
            supported += 1
        else:
            neutral += 1

    # Score calculation:
    # - Each supported claim adds to the score
    # - Each contradiction heavily penalizes
    # - Neutral claims (can't verify) slightly penalize
    if total_checked == 0:
        score = 0.7  # no checkable claims -- moderate confidence
    else:
        base = supported / total_checked
        contradiction_penalty = contradicted * 0.2  # each contradiction costs 0.2
        neutral_penalty = neutral * 0.05             # each unverifiable costs 0.05
        score = max(0.0, min(1.0, base - contradiction_penalty - neutral_penalty))

    # Build detail message
    if contradicted > 0:
        detail = (
            f"Found {contradicted} contradiction(s) with the source document. "
            f"{supported}/{total_checked} claims supported, "
            f"{contradicted} contradicted, {neutral} unverifiable."
        )
        if "entailment_contradiction" not in [f.split(":")[0] for f in flags]:
            flags.insert(0, "entailment_contradiction")
    elif neutral > 0 and supported == 0:
        detail = f"None of the {total_checked} claims could be verified against the source."
        flags.append("weak_entailment")
    elif neutral > 0:
        detail = (
            f"{supported}/{total_checked} claims supported by the source. "
            f"{neutral} could not be verified."
        )
    else:
        detail = f"All {supported} claims are grounded in the source document."

    return CheckResult(score=round(score, 3), flags=flags, detail=detail)
