"""
Clinical text preprocessing for NLI entailment checking.

Problems with raw clinical text + DeBERTa:
1. Clinical abbreviations confuse sentence splitting
   ("Dr. Smith" splits incorrectly, "T 39.1. HR 98." splits mid-vitals)
2. DeBERTa 512-token limit truncates long clinical notes
3. Medical shorthand (BID, TID, PRN) not in DeBERTa's training vocab

This module provides:
- Clinical-aware sentence splitting
- Source context chunking for 512-token limit
- Abbreviation expansion for better NLI inference
- Relevance-based chunk selection per claim
"""

import re

# ── Clinical abbreviation expansions ───────────────────────────────
# Only expand abbreviations that affect NLI inference.
# We DON'T expand lab names (WBC, Hgb) because DeBERTa can handle
# them as tokens. We DO expand dosing/frequency because these
# change meaning in ways that affect entailment.

CLINICAL_EXPANSIONS: dict[str, str] = {
    # Frequency
    r"\bBID\b": "twice daily",
    r"\bTID\b": "three times daily",
    r"\bQID\b": "four times daily",
    r"\bQD\b": "once daily",
    r"\bQ\.?D\.?\b": "once daily",
    r"\bQ\.?H\.?S\.?\b": "at bedtime",
    r"\bPRN\b": "as needed",
    r"\bAC\b": "before meals",
    r"\bPC\b": "after meals",
    r"\bHS\b": "at bedtime",
    # Route
    r"\bPO\b": "by mouth",
    r"\bIV\b": "intravenous",
    r"\bIM\b": "intramuscular",
    r"\bSQ\b": "subcutaneous",
    r"\bSL\b": "sublingual",
    r"\bPR\b": "per rectum",
    # Common clinical
    r"\bNKDA\b": "no known drug allergies",
    r"\bNKA\b": "no known allergies",
    r"\bWNL\b": "within normal limits",
    r"\bNAD\b": "no acute distress",
    r"\bA&O\s*x\s*3\b": "alert and oriented times three",
    r"\bA&Ox3\b": "alert and oriented times three",
    r"\bRA\b(?=[\s,.\)]|$)": "room air",
    # History
    r"\bPMH\b": "past medical history",
    r"\bPSH\b": "past surgical history",
    r"\bFH\b": "family history",
    r"\bSH\b": "social history",
    r"\bHPI\b": "history of present illness",
    r"\bROS\b": "review of systems",
    # Conditions
    r"\bHTN\b": "hypertension",
    r"\bT2DM\b": "type 2 diabetes mellitus",
    r"\bT1DM\b": "type 1 diabetes mellitus",
    r"\bDM\b": "diabetes mellitus",
    r"\bCHF\b": "congestive heart failure",
    r"\bCOPD\b": "chronic obstructive pulmonary disease",
    r"\bCAD\b": "coronary artery disease",
    r"\bAFib\b": "atrial fibrillation",
    r"\bCKD\b": "chronic kidney disease",
    r"\bGERD\b": "gastroesophageal reflux disease",
    r"\bDVT\b": "deep vein thrombosis",
    r"\bPE\b": "pulmonary embolism",
    r"\bACS\b": "acute coronary syndrome",
    r"\bSTEMI\b": "ST-elevation myocardial infarction",
    r"\bNSTEMI\b": "non-ST-elevation myocardial infarction",
    r"\bCVA\b": "cerebrovascular accident",
    r"\bTIA\b": "transient ischemic attack",
    r"\bUTI\b": "urinary tract infection",
    r"\bCAP\b": "community-acquired pneumonia",
    # Procedures / Testing
    r"\bECG\b": "electrocardiogram",
    r"\bEKG\b": "electrocardiogram",
    r"\bCXR\b": "chest X-ray",
    r"\bCT\b": "computed tomography",
    r"\bMRI\b": "magnetic resonance imaging",
    r"\bEBL\b": "estimated blood loss",
    r"\bPICC\b": "peripherally inserted central catheter",
    r"\bPACU\b": "post-anesthesia care unit",
    # Locations
    r"\bRLL\b": "right lower lobe",
    r"\bRUL\b": "right upper lobe",
    r"\bLLL\b": "left lower lobe",
    r"\bLUL\b": "left upper lobe",
    r"\bRUQ\b": "right upper quadrant",
    r"\bLUQ\b": "left upper quadrant",
    r"\bRLQ\b": "right lower quadrant",
    r"\bLLQ\b": "left lower quadrant",
}


def expand_abbreviations(text: str) -> str:
    """
    Expand clinical abbreviations to full terms.
    Only expands abbreviations that could affect NLI inference.
    """
    result = text
    for pattern, expansion in CLINICAL_EXPANSIONS.items():
        result = re.sub(pattern, expansion, result)
    return result


# ── Clinical-aware sentence splitting ──────────────────────────────

# Abbreviations that end with a period but should NOT trigger sentence split
NON_SENTENCE_ENDINGS = re.compile(
    r"\b(?:"
    r"Dr|Mr|Mrs|Ms|Prof|Jr|Sr|"      # Titles
    r"vs|etc|approx|est|"             # Common abbrevs
    r"q\.\d+h|q\.h\.s|q\.d|"         # Dosing: q.4h., q.h.s.
    r"a\.m|p\.m|"                     # Time
    r"e\.g|i\.e|"                     # Latin
    r"pt|wt|ht|"                      # Clinical shorthand
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"  # Months
    r")\.\s*$"
)


def split_clinical_sentences(text: str) -> list[str]:
    """
    Split clinical text into sentences, handling medical abbreviations.

    Handles:
    - "Dr. Smith" (don't split)
    - "T 39.1. HR 98." (split after vitals)
    - "Metoprolol 50mg BID." (split)
    - "Labs: WBC 14.2, Cr 1.2." (keep as one sentence)
    """
    # First pass: split on period-space where the period is likely sentence-ending
    # Use a more careful approach than simple regex
    sentences = []
    current = []
    words = text.split()

    for i, word in enumerate(words):
        current.append(word)

        # Check if this word ends a sentence
        if word.endswith((".")) and len(word) > 1:
            joined = " ".join(current)

            # Don't split if this looks like an abbreviation
            if NON_SENTENCE_ENDINGS.search(joined):
                continue

            # Don't split if the period is inside a number (e.g., "14.2.")
            # but DO split if it's a sentence-ending number like "WBC 14.2."
            if re.search(r"\d+\.\d+\.$", word):
                # This is "14.2." -- check if next word starts with uppercase
                if i + 1 < len(words) and words[i + 1][0:1].isupper():
                    sentences.append(joined)
                    current = []
                    continue
                # Otherwise keep accumulating
                continue

            # Split here
            sentences.append(joined)
            current = []

        elif word.endswith(("!", "?")):
            sentences.append(" ".join(current))
            current = []

    # Don't forget the last chunk
    if current:
        sentences.append(" ".join(current))

    # Filter out very short fragments
    return [s.strip() for s in sentences if len(s.strip()) > 10]


# ── Source context chunking for 512-token limit ────────────────────

def chunk_context(text: str, max_tokens: int = 400, overlap_tokens: int = 50) -> list[str]:
    """
    Split source context into overlapping chunks that fit within
    DeBERTa's 512-token limit.

    max_tokens: ~400 leaves room for the hypothesis (claim) tokens.
    overlap_tokens: ensures claims near chunk boundaries are covered.

    Uses word count as a proxy for token count (conservative).
    """
    words = text.split()

    if len(words) <= max_tokens:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + max_tokens, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)

        if end >= len(words):
            break
        start = end - overlap_tokens

    return chunks


def find_relevant_chunk(chunks: list[str], claim: str) -> str:
    """
    Find the chunk most relevant to a given claim.
    Uses word overlap as a fast heuristic.
    """
    if len(chunks) == 1:
        return chunks[0]

    claim_words = set(claim.lower().split())
    # Remove common words that don't help with matching
    stop_words = {"the", "a", "an", "is", "was", "were", "are", "been",
                  "be", "have", "has", "had", "do", "does", "did",
                  "will", "would", "could", "should", "may", "might",
                  "shall", "can", "and", "or", "but", "in", "on", "at",
                  "to", "for", "of", "with", "by", "from", "as", "into",
                  "that", "which", "who", "whom", "this", "these", "those",
                  "it", "its", "not", "no", "nor", "so", "if", "then",
                  "than", "too", "very", "just", "about", "also", "only"}
    claim_words -= stop_words

    best_chunk = chunks[0]
    best_score = 0

    for chunk in chunks:
        chunk_words = set(chunk.lower().split())
        overlap = len(claim_words & chunk_words)
        if overlap > best_score:
            best_score = overlap
            best_chunk = chunk

    return best_chunk
