/**
 * Tests for the heuristic entailment fallback in governance-checks.ts
 *
 * These test the offline/heuristic path (no DeBERTa service running).
 * The heuristic should:
 * 1. Not give high scores just because source and AI share medical vocabulary
 * 2. Give lower scores when AI output contradicts source
 * 3. Give higher scores when AI output closely matches source facts
 *
 * Run with: npx tsx tests/test_entailment_heuristic.ts
 */

import {
  expandAbbreviations,
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

/**
 * Simplified version of the heuristic fallback from governance-checks.ts
 * (extracted here for unit testing without needing the full Express app)
 */
function heuristicEntailmentScore(output: string, context: string): number {
  const expandedOutput = expandAbbreviations(output);
  const expandedContext = expandAbbreviations(context);

  const outputTokens = expandedOutput.toLowerCase().split(/\s+/).filter(w => w.length > 3);
  const contextTokens = new Set(expandedContext.toLowerCase().split(/\s+/).filter(w => w.length > 3));

  const fillerWords = new Set([
    "patient", "noted", "showed", "found", "present", "history",
    "admitted", "discharged", "treated", "started", "continued",
    "stable", "improved", "clinical", "medical", "assessment",
    "plan", "with", "that", "this", "from", "were", "been",
    "have", "does", "will", "would", "about", "also", "into",
  ]);

  let overlap = 0;
  let totalMeaningful = 0;
  for (const w of outputTokens) {
    if (fillerWords.has(w)) continue;
    totalMeaningful++;
    if (contextTokens.has(w)) overlap++;
  }

  const overlapRatio = totalMeaningful > 0 ? overlap / totalMeaningful : 0;
  return Math.min(overlapRatio * 2.0, 1.0);
}

// ── Test: Correct discharge summary should score well ─────────────

console.log("\n=== Heuristic Entailment: Correct Content ===");

const sourceCorrect = "67F admitted for CAP. PMH: COPD, HTN, T2DM. Allergies: PCN (rash). Vitals: T 39.1, HR 98, BP 132/78, SpO2 91% on RA. Labs: WBC 14.2, Procalcitonin 0.8. Treatment: Ceftriaxone 1g IV daily.";
const aiCorrect = "67-year-old female admitted with community-acquired pneumonia. History of COPD, hypertension, and type 2 diabetes. Penicillin allergy (rash). Temperature 39.1, heart rate 98, blood pressure 132/78, SpO2 91% on room air. WBC 14.2, procalcitonin 0.8. Treated with Ceftriaxone 1g IV daily.";

const correctScore = heuristicEntailmentScore(aiCorrect, sourceCorrect);
console.log(`  Correct summary score: ${correctScore.toFixed(3)}`);
assert(correctScore > 0.5, `Correct summary scores > 0.5 (got ${correctScore.toFixed(3)})`);

// ── Test: Contradicted content should score lower ─────────────────

console.log("\n=== Heuristic Entailment: Contradictions ===");

const aiContradicted = "67-year-old female admitted with myocardial infarction. History of asthma and hypotension. No drug allergies. Temperature 36.5, heart rate 62, blood pressure 180/110, SpO2 99% on high-flow. WBC 6.8, procalcitonin normal. Treated with Amoxicillin 500mg PO.";

const contradictedScore = heuristicEntailmentScore(aiContradicted, sourceCorrect);
console.log(`  Contradicted summary score: ${contradictedScore.toFixed(3)}`);
assert(contradictedScore < correctScore, `Contradicted scores lower than correct (${contradictedScore.toFixed(3)} < ${correctScore.toFixed(3)})`);

// ── Test: Fabricated content should score low ─────────────────────

console.log("\n=== Heuristic Entailment: Fabrication ===");

const aiFabricated = "Patient underwent emergent cardiac catheterization with placement of two drug-eluting stents to the LAD and RCA. Post-procedure transferred to cardiac ICU on heparin drip and dual antiplatelet therapy.";

const fabricatedScore = heuristicEntailmentScore(aiFabricated, sourceCorrect);
console.log(`  Fabricated content score: ${fabricatedScore.toFixed(3)}`);
assert(fabricatedScore < 0.4, `Fabricated content scores < 0.4 (got ${fabricatedScore.toFixed(3)})`);

// ── Test: Shared medical vocabulary shouldn't inflate scores ──────

console.log("\n=== Heuristic Entailment: Vocabulary Control ===");

// This AI output is about a DIFFERENT patient but uses medical terms
const aiDifferentPatient = "Patient admitted with pneumonia was treated with antibiotics and showed clinical improvement. Vitals were stable throughout the admission. Labs were monitored daily. Patient was discharged in stable condition.";

const differentScore = heuristicEntailmentScore(aiDifferentPatient, sourceCorrect);
console.log(`  Different-patient-same-vocabulary score: ${differentScore.toFixed(3)}`);
assert(differentScore < correctScore, `Different patient scores lower than correct (${differentScore.toFixed(3)} < ${correctScore.toFixed(3)})`);

// ── Test: Abbreviation expansion helps matching ───────────────────

console.log("\n=== Heuristic Entailment: Abbreviation Expansion ===");

const sourceAbbrev = "PMH: HTN, T2DM, COPD. Meds: Metoprolol 50mg BID, Lisinopril 10mg PO daily.";
const aiExpanded = "Past medical history includes hypertension, type 2 diabetes mellitus, and chronic obstructive pulmonary disease. Medications include Metoprolol 50mg twice daily and Lisinopril 10mg by mouth daily.";

const expandedScore = heuristicEntailmentScore(aiExpanded, sourceAbbrev);
console.log(`  Abbreviation-expanded matching score: ${expandedScore.toFixed(3)}`);
assert(expandedScore > 0.5, `Expanded abbreviations match well (got ${expandedScore.toFixed(3)})`);

// ── Summary ───────────────────────────────────────────────────────

console.log(`\n${"=".repeat(60)}`);
console.log(`Results: ${passed} passed, ${failed} failed out of ${passed + failed} total`);
console.log(`${"=".repeat(60)}`);

if (failed > 0) {
  process.exit(1);
}
