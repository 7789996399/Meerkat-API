"""
Recommendation direction analysis using domain-specific keyword sets.
Detects whether the AI output favors one party over another.
"""

import re

# Domain-specific keyword sets
DOMAIN_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "legal": {
        "plaintiff": [
            "liable", "negligent", "breach", "at fault", "culpable",
            "responsible for damages", "violated", "failed to comply",
            "in violation", "should be held accountable",
        ],
        "defendant": [
            "not liable", "without fault", "compliant", "within rights",
            "no breach", "properly discharged", "acted reasonably",
            "no evidence of negligence", "lawfully", "in good faith",
        ],
    },
    "financial": {
        "buy": [
            "strong buy", "undervalued", "upside potential", "growth opportunity",
            "outperform", "bullish", "attractive valuation", "recommend buying",
            "accumulate", "price target above",
        ],
        "sell": [
            "overvalued", "downside risk", "sell", "bearish", "underperform",
            "reduce position", "take profits", "declining fundamentals",
            "negative outlook", "price target below",
        ],
    },
    "healthcare": {
        "treatment": [
            "recommend treatment", "beneficial", "effective therapy",
            "clinically indicated", "evidence supports", "improved outcomes",
            "significant benefit", "first-line treatment", "strongly indicated",
            "favorable risk-benefit",
        ],
        "conservative": [
            "watchful waiting", "monitor", "conservative approach",
            "not clinically indicated", "risks outweigh", "defer treatment",
            "insufficient evidence", "observation preferred", "side effects concern",
            "no immediate intervention",
        ],
    },
}

# Default general-purpose keywords
GENERAL_KEYWORDS: dict[str, list[str]] = {
    "option_a": [
        "clearly better", "superior", "strongly recommend", "the best choice",
        "obvious advantage", "far preferable", "without question",
    ],
    "option_b": [
        "inferior", "not recommended", "worse option", "should avoid",
        "disadvantage", "problematic", "less suitable",
    ],
}

# Party labels by domain
PARTY_LABELS: dict[str, tuple[str, str]] = {
    "legal": ("plaintiff", "defendant"),
    "financial": ("buy_side", "sell_side"),
    "healthcare": ("treatment", "conservative"),
    "general": ("option_a", "option_b"),
}


def analyze_direction(
    text: str,
    domain: str = "general",
    context: str = "",
) -> dict:
    """
    Detect recommendation direction using domain-specific keywords.
    Returns which party is favored and the keywords that triggered it.
    """
    lower_text = text.lower()
    domain = domain.lower()

    # Get keyword sets for the domain
    if domain in DOMAIN_KEYWORDS:
        keywords = DOMAIN_KEYWORDS[domain]
        sides = list(keywords.keys())
    else:
        keywords = GENERAL_KEYWORDS
        sides = list(keywords.keys())

    party_a_label, party_b_label = PARTY_LABELS.get(domain, ("option_a", "option_b"))

    # Try to extract party names from context
    extracted_a, extracted_b = _extract_parties(context, domain)
    if extracted_a:
        party_a_label = extracted_a
    if extracted_b:
        party_b_label = extracted_b

    # Count keyword matches
    side_a_keywords = keywords[sides[0]]
    side_b_keywords = keywords[sides[1]]

    a_found = [kw for kw in side_a_keywords if kw.lower() in lower_text]
    b_found = [kw for kw in side_b_keywords if kw.lower() in lower_text]

    a_score = len(a_found)
    b_score = len(b_found)
    total = a_score + b_score

    if total == 0:
        direction = "neutral"
    elif a_score > b_score:
        direction = f"favors_{sides[0]}"
    elif b_score > a_score:
        direction = f"favors_{sides[1]}"
    else:
        direction = "balanced"

    # Normalize scores to 0-1 range
    max_possible = max(len(side_a_keywords), len(side_b_keywords))
    a_norm = a_score / max_possible if max_possible > 0 else 0
    b_norm = b_score / max_possible if max_possible > 0 else 0

    return {
        "direction": direction,
        "party_a": party_a_label,
        "party_b": party_b_label,
        "party_a_score": round(a_norm, 4),
        "party_b_score": round(b_norm, 4),
        "keywords_found": a_found + b_found,
    }


def _extract_parties(context: str, domain: str) -> tuple[str, str]:
    """
    Try to extract party names from the context string.
    Returns (party_a, party_b) or empty strings if not found.
    """
    if not context:
        return "", ""

    if domain == "legal":
        # Look for "X v. Y" or "X vs Y" patterns
        match = re.search(
            r"([A-Z][a-zA-Z\s]+?)\s+(?:v\.|vs\.?|versus)\s+([A-Z][a-zA-Z\s]+?)(?:\s|$|,|\.)",
            context,
        )
        if match:
            return match.group(1).strip(), match.group(2).strip()

    if domain == "financial":
        # Look for ticker symbols or company names
        tickers = re.findall(r"\b([A-Z]{2,5})\b", context)
        if len(tickers) >= 2:
            return tickers[0], tickers[1]
        elif len(tickers) == 1:
            return tickers[0], "market"

    if domain == "healthcare":
        # Look for "patient" and treatment names
        treatment = re.search(r"(?:treatment|therapy|medication|drug)[:\s]+([A-Za-z\s]+?)(?:\s|$|,|\.)", context, re.I)
        if treatment:
            return treatment.group(1).strip(), "conservative_care"

    return "", ""
