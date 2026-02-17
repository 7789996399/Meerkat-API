/**
 * Tests for clinical-preprocessing.ts
 *
 * Run with: npx tsx tests/test_clinical_preprocessing.ts
 */

import {
  expandAbbreviations,
  splitClinicalSentences,
  chunkContext,
  findRelevantChunk,
} from "../src/services/clinical-preprocessing";

let passed = 0;
let failed = 0;

function assert(condition: boolean, name: string) {
  if (condition) {
    passed++;
    console.log(`  PASS: ${name}`);
  } else {
    failed++;
    console.log(`  FAIL: ${name}`);
  }
}

function assertIncludes(text: string, expected: string, name: string) {
  assert(text.includes(expected), `${name} (expected "${expected}")`);
}

// ── Abbreviation expansion tests ──────────────────────────────────

console.log("\n=== Abbreviation Expansion ===");

const expanded1 = expandAbbreviations("Metoprolol 50mg BID, Lisinopril 10mg PO daily");
assertIncludes(expanded1, "twice daily", "BID -> twice daily");
assertIncludes(expanded1, "by mouth", "PO -> by mouth");

const expanded2 = expandAbbreviations("Allergies: NKDA. PMH: HTN, T2DM, COPD.");
assertIncludes(expanded2, "no known drug allergies", "NKDA expansion");
assertIncludes(expanded2, "hypertension", "HTN expansion");
assertIncludes(expanded2, "type 2 diabetes mellitus", "T2DM expansion");
assertIncludes(expanded2, "chronic obstructive pulmonary disease", "COPD expansion");

const expanded3 = expandAbbreviations("SpO2 91% on RA. CXR shows RLL consolidation.");
assertIncludes(expanded3, "room air", "RA -> room air");
assertIncludes(expanded3, "chest X-ray", "CXR -> chest X-ray");
assertIncludes(expanded3, "right lower lobe", "RLL -> right lower lobe");

// ── Sentence splitting tests ──────────────────────────────────────

console.log("\n=== Clinical Sentence Splitting ===");

// Should NOT split on decimal points in vitals
const vitals = "Vitals: T 39.1. HR 98. BP 132/78. SpO2 91%.";
const vitalSentences = splitClinicalSentences(vitals);
// It's OK if this splits into individual vital readings, but NOT mid-number
const allJoined = vitalSentences.join(" ");
assert(!allJoined.includes("39. ") || !allJoined.includes(". 1."), "Does not split mid-decimal (39.1)");
assert(vitalSentences.length >= 1, `Produces at least 1 sentence (got ${vitalSentences.length})`);

// Should handle medication list
const meds = "Medications: Metoprolol 50mg BID. Lisinopril 10mg daily. Metformin 500mg BID.";
const medSentences = splitClinicalSentences(meds);
assert(medSentences.length >= 1, `Medication list: at least 1 sentence (got ${medSentences.length})`);

// Should handle Dr. abbreviation
const doc = "Dr. Smith performed the procedure. Patient tolerated well.";
const docSentences = splitClinicalSentences(doc);
// "Dr." should not cause a split
const drSmithInOneSentence = docSentences.some(s => s.includes("Dr") && s.includes("Smith") && s.includes("procedure"));
assert(drSmithInOneSentence, "Dr. Smith not split from procedure");

// ── Context chunking tests ────────────────────────────────────────

console.log("\n=== Context Chunking ===");

// Short text should be one chunk
const shortText = "Patient admitted with pneumonia. WBC elevated.";
const shortChunks = chunkContext(shortText, 380, 50);
assert(shortChunks.length === 1, `Short text: 1 chunk (got ${shortChunks.length})`);
assert(shortChunks[0] === shortText, "Short text: unchanged");

// Long text should be multiple chunks
const longWords = Array.from({ length: 500 }, (_, i) => `word${i}`).join(" ");
const longChunks = chunkContext(longWords, 380, 50);
assert(longChunks.length >= 2, `Long text: 2+ chunks (got ${longChunks.length})`);

// Chunks should overlap
if (longChunks.length >= 2) {
  const chunk1Words = new Set(longChunks[0].split(/\s+/));
  const chunk2Words = new Set(longChunks[1].split(/\s+/));
  let overlapCount = 0;
  for (const w of chunk1Words) {
    if (chunk2Words.has(w)) overlapCount++;
  }
  assert(overlapCount >= 30, `Chunks overlap by at least 30 words (got ${overlapCount})`);
}

// ── Chunk relevance tests ─────────────────────────────────────────

console.log("\n=== Chunk Relevance ===");

const chunks = [
  "Patient admitted with pneumonia. WBC 14.2, procalcitonin elevated. Started on Ceftriaxone.",
  "Social history: former smoker, quit 10 years ago. Lives alone. Independent with ADLs.",
  "Medications on discharge: Metoprolol 50mg BID, Lisinopril 10mg daily.",
];

const labClaim = "WBC was elevated at 14.2 with high procalcitonin.";
const medClaim = "Patient discharged on Metoprolol 50mg twice daily.";
const socialClaim = "Former smoker who quit 10 years ago.";

const labChunk = findRelevantChunk(chunks, labClaim);
const medChunk = findRelevantChunk(chunks, medClaim);
const socialChunk = findRelevantChunk(chunks, socialClaim);

assert(labChunk.includes("WBC"), "Lab claim matched to lab chunk");
assert(medChunk.includes("Metoprolol"), "Med claim matched to med chunk");
assert(socialChunk.includes("smoker"), "Social claim matched to social chunk");

// ── Summary ───────────────────────────────────────────────────────

console.log(`\n${"=".repeat(60)}`);
console.log(`Results: ${passed} passed, ${failed} failed out of ${passed + failed} total`);
console.log(`${"=".repeat(60)}`);

if (failed > 0) {
  process.exit(1);
}
