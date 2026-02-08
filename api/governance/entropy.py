"""
Semantic Entropy Check (demo mode)

Measures how confident the AI model appears in its output. In production,
this would sample N completions and measure semantic divergence. In demo
mode, we analyze the output text itself for signals of uncertainty.

HIGH confidence (low entropy, high score):
  - Specific numbers, dates, section references
  - Definitive language ("is", "contains", "requires")
  - Structured, factual statements

LOW confidence (high entropy, low score):
  - Hedge words ("may", "might", "could", "possibly", "appears")
  - Qualifying phrases ("it seems", "it is unclear", "arguably")
  - Self-contradicting statements within the same output
  - Vague language without specifics

PRODUCTION MODE:
  Would make N parallel API calls with temperature > 0, embed with
  sentence-transformers, cluster semantically, compute entropy over
  cluster distribution.
"""

import re

from api.models.schemas import CheckResult

# Words that indicate the model is uncertain
HEDGE_WORDS = {
    "may", "might", "could", "possibly", "perhaps", "uncertain",
    "likely", "unlikely", "appears", "seems", "arguably", "potentially",
    "suggest", "suggests", "probable", "presumably", "conceivably",
}

# Stronger hedging phrases (multi-word)
HEDGE_PHRASES = [
    "it is unclear", "it seems", "it appears", "it is possible",
    "it is likely", "it is unlikely", "there may be", "there might be",
    "not entirely clear", "difficult to determine", "hard to say",
    "open to interpretation", "subject to debate",
]

# Confidence boosters -- specific, factual language
CONFIDENCE_PATTERNS = [
    r'\b\d+[\s-](?:day|week|month|year|mile)s?\b',  # "30 days", "12-month"
    r'(?:Section|Clause|Article)\s+\d',               # legal references
    r'\$[\d,]+',                                       # dollar amounts
    r'\d+(?:\.\d+)?%',                                 # percentages
    r'\b(?:requires|contains|states|specifies|provides|mandates)\b',
]

# Self-contradiction signals
CONTRADICTION_PAIRS = [
    (r'\bbut\s+(?:also|however)', "hedging_qualifier"),
    (r'\bhowever.*(?:nevertheless|nonetheless)', "contradictory_structure"),
    (r'\bon\s+(?:the\s+)?one\s+hand.*on\s+the\s+other', "on_the_other_hand"),
]


def check_entropy(output: str) -> CheckResult:
    """Run the semantic entropy check. Returns a CheckResult with score 0.0-1.0.
    Higher score = more confident = lower entropy = better."""

    text_lower = output.lower()
    words = text_lower.split()
    word_count = max(len(words), 1)

    # Count hedge words
    hedge_count = sum(1 for w in words if w in HEDGE_WORDS)
    hedge_ratio = hedge_count / word_count

    # Count hedge phrases
    phrase_count = sum(1 for phrase in HEDGE_PHRASES if phrase in text_lower)

    # Count confidence boosters
    confidence_count = sum(
        len(re.findall(pattern, output, re.IGNORECASE))
        for pattern in CONFIDENCE_PATTERNS
    )

    # Check for self-contradictions
    contradiction_count = sum(
        1 for pattern, _ in CONTRADICTION_PAIRS
        if re.search(pattern, text_lower)
    )

    # Build the score:
    # Start at 0.5 (neutral), boost for confidence signals, penalize for hedging
    score = 0.5

    # Confidence boosters push the score up
    score += min(confidence_count * 0.08, 0.4)  # up to +0.4 for lots of specifics

    # Hedging pushes the score down
    score -= hedge_ratio * 3.0          # heavy penalty for hedge word density
    score -= phrase_count * 0.08        # each hedge phrase costs 0.08
    score -= contradiction_count * 0.15  # contradictions are a big red flag

    # Very short responses with no specifics are slightly uncertain
    if word_count < 20 and confidence_count == 0:
        score -= 0.1

    score = round(max(0.0, min(1.0, score)), 3)

    # Determine flags and detail
    flags: list[str] = []
    details: list[str] = []

    if score < 0.35:
        flags.append("high_uncertainty")
        details.append("Output shows significant hedging and lacks specific details.")
    elif score < 0.65:
        flags.append("moderate_uncertainty")
        details.append("Output contains some hedging language.")

    if contradiction_count > 0:
        flags.append("self_contradicting")
        details.append("Output contains self-contradicting statements.")

    if hedge_count > 0 and not details:
        details.append(f"Detected {hedge_count} hedge word(s) but overall confidence is acceptable.")

    if not details:
        details.append("Output shows high confidence with specific facts and definitive language.")

    return CheckResult(score=score, flags=flags, detail=" ".join(details))
