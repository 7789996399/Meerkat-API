/**
 * Clinical text preprocessing for NLI entailment checking.
 *
 * Problems with raw clinical text + DeBERTa:
 * 1. Clinical abbreviations confuse NLI ("BID" not in training vocab)
 * 2. DeBERTa's 512-token limit truncates long clinical notes
 * 3. "T 39.1. HR 98." splits mid-number with naive sentence splitting
 *
 * This module ports the Python clinical_preprocessing.py to TypeScript.
 */

// ── Clinical abbreviation expansions ──────────────────────────────

const CLINICAL_EXPANSIONS: [RegExp, string][] = [
  // Frequency
  [/\bBID\b/g, "twice daily"],
  [/\bTID\b/g, "three times daily"],
  [/\bQID\b/g, "four times daily"],
  [/\bQD\b/g, "once daily"],
  [/\bPRN\b/g, "as needed"],
  [/\bAC\b/g, "before meals"],
  [/\bPC\b/g, "after meals"],
  [/\bHS\b/g, "at bedtime"],
  // Route
  [/\bPO\b/g, "by mouth"],
  [/\bIV\b/g, "intravenous"],
  [/\bIM\b/g, "intramuscular"],
  [/\bSQ\b/g, "subcutaneous"],
  [/\bSL\b/g, "sublingual"],
  // Common clinical
  [/\bNKDA\b/g, "no known drug allergies"],
  [/\bNKA\b/g, "no known allergies"],
  [/\bWNL\b/g, "within normal limits"],
  [/\bNAD\b/g, "no acute distress"],
  [/\bRA\b(?=[\s,.);\-]|$)/g, "room air"],
  // History
  [/\bPMH\b/g, "past medical history"],
  [/\bHPI\b/g, "history of present illness"],
  // Conditions
  [/\bHTN\b/g, "hypertension"],
  [/\bT2DM\b/g, "type 2 diabetes mellitus"],
  [/\bDM\b/g, "diabetes mellitus"],
  [/\bCHF\b/g, "congestive heart failure"],
  [/\bCOPD\b/g, "chronic obstructive pulmonary disease"],
  [/\bCAD\b/g, "coronary artery disease"],
  [/\bAFib\b/g, "atrial fibrillation"],
  [/\bCKD\b/g, "chronic kidney disease"],
  [/\bGERD\b/g, "gastroesophageal reflux disease"],
  [/\bACS\b/g, "acute coronary syndrome"],
  [/\bCAP\b/g, "community-acquired pneumonia"],
  [/\bUTI\b/g, "urinary tract infection"],
  // Procedures
  [/\bECG\b/g, "electrocardiogram"],
  [/\bEKG\b/g, "electrocardiogram"],
  [/\bCXR\b/g, "chest X-ray"],
  [/\bEBL\b/g, "estimated blood loss"],
  [/\bPICC\b/g, "peripherally inserted central catheter"],
  // Locations
  [/\bRLL\b/g, "right lower lobe"],
  [/\bRUL\b/g, "right upper lobe"],
  [/\bLLL\b/g, "left lower lobe"],
  [/\bLUL\b/g, "left upper lobe"],
];

/**
 * Expand clinical abbreviations to full terms for better NLI inference.
 * Only expands abbreviations that could affect entailment checking.
 */
export function expandAbbreviations(text: string): string {
  let result = text;
  for (const [pattern, expansion] of CLINICAL_EXPANSIONS) {
    result = result.replace(pattern, expansion);
  }
  return result;
}

// ── Clinical-aware sentence splitting ─────────────────────────────

// Abbreviations that end with a period but should NOT trigger sentence split
const NON_SENTENCE_ENDINGS = /\b(?:Dr|Mr|Mrs|Ms|Prof|Jr|Sr|vs|etc|approx|est)\.\s*$/;

/**
 * Split clinical text into sentences, handling medical abbreviations.
 *
 * Handles:
 * - "Dr. Smith" (don't split)
 * - "T 39.1. HR 98." (split after complete vitals, not mid-number)
 * - "Metoprolol 50mg BID." (split)
 * - "Labs: WBC 14.2, Cr 1.2." (keep as one sentence)
 */
export function splitClinicalSentences(text: string): string[] {
  const sentences: string[] = [];
  let current = "";

  // Split on explicit sentence boundaries, being careful with decimals
  // Strategy: split on period followed by space and uppercase letter,
  // but NOT when the period is between digits (14.2)
  const parts = text.split(/(?<=\w)\.(?=\s+[A-Z])/);

  for (const part of parts) {
    const trimmed = (current + part).trim();
    if (!trimmed) continue;

    // Check for non-sentence-ending abbreviation
    if (NON_SENTENCE_ENDINGS.test(trimmed + ".")) {
      current = trimmed + ". ";
      continue;
    }

    // This is a complete sentence
    const sentence = trimmed.endsWith(".") ? trimmed : trimmed + ".";
    if (sentence.length > 10) {
      sentences.push(sentence);
    }
    current = "";
  }

  // Handle remaining text
  if (current.trim().length > 10) {
    sentences.push(current.trim());
  }

  return sentences;
}

// ── Source context chunking for 512-token limit ───────────────────

/**
 * Split source context into overlapping chunks that fit within
 * DeBERTa's 512-token limit.
 *
 * maxTokens: ~380 leaves room for the hypothesis (claim) tokens.
 * overlapTokens: ensures claims near chunk boundaries are covered.
 *
 * Uses word count as a proxy for token count (conservative).
 */
export function chunkContext(
  text: string,
  maxTokens: number = 380,
  overlapTokens: number = 50,
): string[] {
  const words = text.split(/\s+/).filter(w => w.length > 0);

  if (words.length <= maxTokens) {
    return [text];
  }

  const chunks: string[] = [];
  let start = 0;

  while (start < words.length) {
    const end = Math.min(start + maxTokens, words.length);
    chunks.push(words.slice(start, end).join(" "));

    if (end >= words.length) break;
    start = end - overlapTokens;
  }

  return chunks;
}

/**
 * Find the chunk most relevant to a given claim.
 * Uses word overlap (excluding stop words) as a fast heuristic.
 */
export function findRelevantChunk(chunks: string[], claim: string): string {
  if (chunks.length === 1) return chunks[0];

  const stopWords = new Set([
    "the", "a", "an", "is", "was", "were", "are", "been", "be",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "and", "or", "but", "in",
    "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "that", "which", "who", "this", "these", "those", "it", "its",
    "not", "no", "so", "if", "then", "than", "too", "very", "just",
    "about", "also", "only", "patient", "noted", "showed", "found",
  ]);

  const claimWords = new Set(
    claim.toLowerCase().split(/\s+/).filter(w => w.length > 2 && !stopWords.has(w))
  );

  let bestChunk = chunks[0];
  let bestScore = 0;

  for (const chunk of chunks) {
    const chunkWords = new Set(chunk.toLowerCase().split(/\s+/));
    let overlap = 0;
    for (const w of claimWords) {
      if (chunkWords.has(w)) overlap++;
    }
    if (overlap > bestScore) {
      bestScore = overlap;
      bestChunk = chunk;
    }
  }

  return bestChunk;
}
