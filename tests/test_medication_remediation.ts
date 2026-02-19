/**
 * Tests for healthcare medication remediation rules.
 * Ensures dose discrepancies route to human review while clear hallucinations auto-correct.
 *
 * Run with: npx tsx tests/test_medication_remediation.ts
 */

import { buildRemediation } from "../src/services/remediation";
import { CheckResult } from "../src/services/governance-checks";
import { CorrectionDetail } from "../src/types/remediation";

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

// ── Helper: build a minimal checksResults with numerical corrections ──

function makeChecksResults(corrections: CorrectionDetail[]): Record<string, CheckResult> {
  return {
    numerical_verify: {
      score: 0.3,
      flags: ["numerical_distortion"],
      detail: "test",
      corrections,
    },
  };
}

// ══════════════════════════════════════════════════════════════
// Test 1: 2x dose discrepancy → REQUEST_HUMAN_REVIEW
// Doctor changed Metoprolol 50mg → 100mg. This is a 1x deviation
// (within clinical adjustment range). Must NOT auto-correct.
// ══════════════════════════════════════════════════════════════

console.log("\n=== Test 1: 2x dose discrepancy → REQUEST_HUMAN_REVIEW ===");

const discrepancyCorrection: CorrectionDetail = {
  type: "numerical_distortion",
  check: "numerical_verify",
  found: "100 mg",
  expected: "50 mg",
  severity: "medium",
  source_reference: "Metoprolol 50mg PO daily",
  subtype: "discrepancy",
  requires_clinical_review: true,
  rationale: "Dose deviation 1.0x within clinical adjustment range — may be intentional",
};

const result1 = buildRemediation({
  status: "BLOCK",
  checksResults: makeChecksResults([discrepancyCorrection]),
  allFlags: ["numerical_distortion"],
  attempt: 1,
  maxRetries: 3,
  domain: "healthcare",
});

assert(result1.suggested_action === "REQUEST_HUMAN_REVIEW", "2x dose discrepancy → REQUEST_HUMAN_REVIEW");
assert(result1.agent_instruction.includes("MEDICATION DOSE DISCREPANCY"), "agent instruction mentions MEDICATION DOSE DISCREPANCY");
assert(result1.agent_instruction.includes("Verify") || result1.agent_instruction.includes("verify") || result1.agent_instruction.includes("prescriber"), "agent instruction mentions verification/prescriber");

// ══════════════════════════════════════════════════════════════
// Test 2: 10x dose error → RETRY_WITH_CORRECTION
// AI hallucinated Metoprolol 500mg when source says 50mg. deviation=9.0
// This is clearly wrong — safe to auto-correct.
// ══════════════════════════════════════════════════════════════

console.log("\n=== Test 2: 10x dose error → RETRY_WITH_CORRECTION ===");

const hallucinationCorrection: CorrectionDetail = {
  type: "numerical_distortion",
  check: "numerical_verify",
  found: "500 mg",
  expected: "50 mg",
  severity: "critical",
  source_reference: "Metoprolol 50mg PO daily",
  subtype: "error",
  requires_clinical_review: false,
  rationale: "Dose deviation 9.0x exceeds 5x threshold — likely hallucination",
};

const result2 = buildRemediation({
  status: "BLOCK",
  checksResults: makeChecksResults([hallucinationCorrection]),
  allFlags: ["numerical_distortion", "critical_numerical_mismatch"],
  attempt: 1,
  maxRetries: 3,
  domain: "healthcare",
});

assert(result2.suggested_action === "RETRY_WITH_CORRECTION", "10x dose error → RETRY_WITH_CORRECTION");
assert(result2.agent_instruction.includes("NUMERICAL ERROR"), "agent instruction contains NUMERICAL ERROR directive");

// ══════════════════════════════════════════════════════════════
// Test 3: Drug name swap (claim_extraction only) → RETRY_WITH_CORRECTION
// claim_extraction found a contradicted claim that happens to contain "mg".
// Keyword matching is restricted to numerical_distortion corrections to
// avoid false positives from clinical text saturated with unit strings.
// Without requires_clinical_review, this should NOT trigger the override.
// ══════════════════════════════════════════════════════════════

console.log("\n=== Test 3: Drug name swap (claim_extraction + mg, no numerical) → RETRY_WITH_CORRECTION ===");

const drugSwapCorrection: CorrectionDetail = {
  type: "source_contradiction",
  check: "claim_extraction",
  found: "Lisinopril 10 mg daily",
  expected: "Losartan 50 mg daily",
  severity: "high",
};

const result3 = buildRemediation({
  status: "BLOCK",
  checksResults: {
    claim_extraction: {
      score: 0.4,
      flags: ["unverified_claims"],
      detail: "test",
      corrections: [drugSwapCorrection],
    },
  },
  allFlags: ["unverified_claims"],
  attempt: 1,
  maxRetries: 3,
  domain: "healthcare",
});

assert(result3.suggested_action === "RETRY_WITH_CORRECTION", "drug swap from claim_extraction only → RETRY_WITH_CORRECTION (no medication override)");

// ══════════════════════════════════════════════════════════════
// Test 3b: Drug name swap caught by BOTH claim_extraction and
// numerical_verify (with requires_clinical_review) → REQUEST_HUMAN_REVIEW
// When numerical_verify flags the dose as a discrepancy, the override fires.
// ══════════════════════════════════════════════════════════════

console.log("\n=== Test 3b: Drug swap with numerical discrepancy → REQUEST_HUMAN_REVIEW ===");

const drugSwapNumerical: CorrectionDetail = {
  type: "numerical_distortion",
  check: "numerical_verify",
  found: "10 mg",
  expected: "50 mg",
  severity: "medium",
  subtype: "discrepancy",
  requires_clinical_review: true,
  rationale: "Dose deviation 1.6x within clinical adjustment range — may be intentional",
};

const result3b = buildRemediation({
  status: "BLOCK",
  checksResults: {
    claim_extraction: {
      score: 0.4,
      flags: ["unverified_claims"],
      detail: "test",
      corrections: [drugSwapCorrection],
    },
    numerical_verify: {
      score: 0.5,
      flags: ["numerical_distortion"],
      detail: "test",
      corrections: [drugSwapNumerical],
    },
  },
  allFlags: ["unverified_claims", "numerical_distortion"],
  attempt: 1,
  maxRetries: 3,
  domain: "healthcare",
});

assert(result3b.suggested_action === "REQUEST_HUMAN_REVIEW", "drug swap with numerical discrepancy → REQUEST_HUMAN_REVIEW");

// ══════════════════════════════════════════════════════════════
// Test 4: Non-healthcare domain with same discrepancy → RETRY_WITH_CORRECTION
// Financial domain: same deviation pattern should NOT trigger clinical review.
// ══════════════════════════════════════════════════════════════

console.log("\n=== Test 4: Non-healthcare domain → RETRY_WITH_CORRECTION ===");

const financialDiscrepancy: CorrectionDetail = {
  type: "numerical_distortion",
  check: "numerical_verify",
  found: "$100",
  expected: "$50",
  severity: "medium",
  source_reference: "Invoice total: $50",
  subtype: "error",
};

const result4 = buildRemediation({
  status: "BLOCK",
  checksResults: makeChecksResults([financialDiscrepancy]),
  allFlags: ["numerical_distortion"],
  attempt: 1,
  maxRetries: 3,
  domain: "financial",
});

assert(result4.suggested_action === "RETRY_WITH_CORRECTION", "financial domain discrepancy → RETRY_WITH_CORRECTION (no healthcare override)");

// ── Summary ─────────────────────────────────────────────────

console.log(`\n${"=".repeat(60)}`);
console.log(`Results: ${passed} passed, ${failed} failed out of ${passed + failed} total`);
console.log(`${"=".repeat(60)}`);

if (failed > 0) {
  process.exit(1);
}
