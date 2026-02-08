"""
Claim extraction using spaCy en_core_web_trf.

Identifies verifiable factual claims based on:
- Named entities (PERSON, ORG, DATE, MONEY, PERCENT, CARDINAL, etc.)
- Specific numbers or measurements
- Temporal references
- Causal assertions ("causes", "requires", "leads to")
- Legal/medical/financial assertions ("is enforceable", "is indicated", "exceeds")
"""

import re
import spacy

_nlp = None

# Entity types that indicate a factual claim
FACTUAL_ENTITY_TYPES = {
    "PERSON", "ORG", "GPE", "DATE", "TIME", "MONEY", "PERCENT",
    "CARDINAL", "ORDINAL", "QUANTITY", "LAW", "PRODUCT", "EVENT",
    "NORP", "FAC", "LOC", "WORK_OF_ART",
}

# Patterns indicating causal assertions
CAUSAL_PATTERNS = [
    r"\b(?:causes?|caused|causing)\b",
    r"\b(?:requires?|required|requiring)\b",
    r"\b(?:leads?\s+to|led\s+to|leading\s+to)\b",
    r"\b(?:results?\s+in|resulted\s+in|resulting\s+in)\b",
    r"\b(?:due\s+to|because\s+of|as\s+a\s+result\s+of)\b",
    r"\b(?:therefore|consequently|hence|thus)\b",
    r"\b(?:if\s+.+then)\b",
]

# Patterns indicating legal/medical/financial assertions
DOMAIN_ASSERTION_PATTERNS = [
    # Legal
    r"\bis\s+(?:enforceable|binding|prohibited|unlawful|lawful|permitted)\b",
    r"\b(?:in\s+(?:breach|violation|compliance|accordance))\b",
    r"\b(?:shall|must\s+not|is\s+required\s+to)\b",
    # Medical
    r"\bis\s+(?:indicated|contraindicated|diagnosed|prescribed)\b",
    r"\b(?:effective\s+(?:for|in|at)|clinically\s+significant)\b",
    r"\b(?:associated\s+with|risk\s+(?:of|factor))\b",
    # Financial
    r"\b(?:exceeds?\s+(?:threshold|limit|target|benchmark))\b",
    r"\b(?:increased|decreased|grew|declined)\s+(?:by|to)\s+\d",
    r"\b(?:valued\s+at|priced\s+at|worth)\b",
]

# Hedging indicators -- sentences with these are less likely factual claims
HEDGE_PATTERNS = [
    r"\b(?:may|might|could|possibly|perhaps|probably)\b",
    r"\b(?:it\s+(?:seems|appears)|(?:seems|appears)\s+(?:to|that))\b",
    r"\b(?:in\s+my\s+opinion|I\s+think|I\s+believe)\b",
    r"\b(?:arguably|debatable|uncertain)\b",
]

# Number/measurement pattern
NUMBER_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|percent|dollars?|USD|EUR|GBP|kg|mg|ml|km|miles?|"
    r"months?|years?|days?|hours?|minutes?|weeks?|billion|million|thousand)\b",
    re.IGNORECASE,
)


def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_trf")
    return _nlp


def extract_claims(text: str) -> list[dict]:
    """
    Extract verifiable factual claims from text.

    Returns a list of dicts:
      { "text": str, "source_sentence": str, "entities": [str] }
    """
    nlp = _get_nlp()
    doc = nlp(text)

    claims = []
    for sent in doc.sents:
        sent_text = sent.text.strip()
        if len(sent_text) < 10:
            continue

        # Check if this sentence is hedged (opinion, not factual)
        if _is_hedged(sent_text):
            continue

        # Collect entities in this sentence
        entities = []
        has_factual_entity = False
        for ent in sent.ents:
            if ent.label_ in FACTUAL_ENTITY_TYPES:
                has_factual_entity = True
                entities.append(ent.text)

        # Check for other factual indicators
        has_number = bool(NUMBER_PATTERN.search(sent_text))
        has_causal = _matches_any(sent_text, CAUSAL_PATTERNS)
        has_domain_assertion = _matches_any(sent_text, DOMAIN_ASSERTION_PATTERNS)

        if has_factual_entity or has_number or has_causal or has_domain_assertion:
            # Extract the claim text -- use the sentence as-is for now
            claim_text = _clean_claim(sent_text)
            claims.append({
                "text": claim_text,
                "source_sentence": sent_text,
                "entities": entities,
            })

    return claims


def _is_hedged(text: str) -> bool:
    """Check if text contains hedging language that marks it as opinion."""
    for pattern in HEDGE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _matches_any(text: str, patterns: list[str]) -> bool:
    """Check if text matches any of the given regex patterns."""
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _clean_claim(text: str) -> str:
    """Clean up a claim string."""
    # Remove leading conjunctions/transitions
    text = re.sub(r"^(?:However|Additionally|Furthermore|Moreover|Also|In addition),?\s*", "", text)
    return text.strip()
