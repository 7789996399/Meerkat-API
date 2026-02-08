"""
Entity cross-reference between AI output and source context.

Extracts named entities from both texts using spaCy NER, then identifies
entities present in the AI output that do NOT appear in the source context.
These are flagged as potentially hallucinated.
"""

import spacy

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_trf")
    return _nlp


def find_hallucinated_entities(
    ai_output: str,
    source_context: str,
) -> list[str]:
    """
    Find entities in the AI output that don't appear in the source context.

    Returns a list of entity text strings that are present in the AI output
    but absent from the source context (potential hallucinations).
    """
    if not source_context.strip():
        return []

    nlp = _get_nlp()

    output_doc = nlp(ai_output)
    context_doc = nlp(source_context)

    # Collect normalized entity texts from source context
    context_entities: set[str] = set()
    for ent in context_doc.ents:
        context_entities.add(ent.text.lower().strip())
        # Also add without punctuation for fuzzy matching
        cleaned = ent.text.lower().strip().rstrip(".,;:")
        context_entities.add(cleaned)

    # Find output entities not in context
    hallucinated: list[str] = []
    seen: set[str] = set()

    for ent in output_doc.ents:
        normalized = ent.text.lower().strip()
        cleaned = normalized.rstrip(".,;:")

        # Skip if already reported
        if normalized in seen:
            continue

        # Skip very short entities (single chars, common words)
        if len(cleaned) < 2:
            continue

        # Check if entity appears in context (exact or cleaned match)
        if normalized not in context_entities and cleaned not in context_entities:
            # Also check substring containment for partial matches
            if not _fuzzy_match(cleaned, context_entities):
                hallucinated.append(ent.text)
                seen.add(normalized)

    return hallucinated


def _fuzzy_match(entity: str, context_entities: set[str]) -> bool:
    """Check if entity is a substring of any context entity or vice versa."""
    for ctx_ent in context_entities:
        if entity in ctx_ent or ctx_ent in entity:
            return True
    return False
