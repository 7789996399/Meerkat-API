/**
 * Tests for the Meerkat OpenClaw interceptor.
 * Tests decision logic, action classification, and source classification
 * without hitting a real API.
 *
 * Run with: npx tsx openclaw/tests/test_interceptor.ts
 */

import { MeerkatInterceptor } from "../interceptor/index";

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

// Create interceptor (won't call real API in these tests)
const meerkat = new MeerkatInterceptor({
  apiKey: "mk_test_fake_key",
  baseUrl: "http://localhost:9999", // won't be called
});

// ── Action classification tests ───────────────────────────────────

console.log("\n=== Action Classification (requiresVerification) ===");

// High-impact actions SHOULD require verification
const highImpact = [
  "send_email", "send_message", "execute_command", "run_shell",
  "write_file", "delete_file", "post_tweet", "make_purchase",
  "share_file", "create_event", "run_code", "deploy",
  "reply_email", "forward_email", "post_slack",
];

for (const action of highImpact) {
  assert(meerkat.requiresVerification(action), `${action} requires verification`);
}

// With namespace prefix (OpenClaw uses "exec.run_shell" format)
assert(meerkat.requiresVerification("exec.run_shell"), "exec.run_shell (namespaced)");
assert(meerkat.requiresVerification("mail.send_email"), "mail.send_email (namespaced)");

// Low-impact actions should NOT require verification
const lowImpact = [
  "read_file", "list_directory", "get_time", "search_web",
  "read_email", "list_events", "check_weather",
];

for (const action of lowImpact) {
  assert(!meerkat.requiresVerification(action), `${action} does NOT require verification`);
}

// ── Source classification tests ───────────────────────────────────

console.log("\n=== Source Classification (shouldShield) ===");

const untrustedSources = [
  "email", "email_attachment", "web_page", "web_search",
  "document", "forwarded_message", "skill_install",
  "calendar_invite", "shared_file", "webhook",
  "unknown_sender", "public_channel",
];

for (const source of untrustedSources) {
  assert(meerkat.shouldShield(source), `${source} should be shielded`);
}

// Trusted sources (user's direct input)
assert(!meerkat.shouldShield("user_direct"), "user_direct should NOT be shielded");
assert(!meerkat.shouldShield("cli_input"), "cli_input should NOT be shielded");

// ── Result evaluation tests ──────────────────────────────────────

console.log("\n=== Result Evaluation (evaluateResult) ===");

// High trust score -> execute
assert(
  meerkat.evaluateResult({
    trust_score: 85,
    status: "PASS",
    checks: {},
    flags: [],
    recommendations: [],
    audit_id: "test_1",
  }) === "execute",
  "Score 85 + PASS -> execute",
);

// Medium trust score -> confirm
assert(
  meerkat.evaluateResult({
    trust_score: 55,
    status: "FLAG",
    checks: {},
    flags: ["moderate_uncertainty"],
    recommendations: ["Review before proceeding"],
    audit_id: "test_2",
  }) === "confirm",
  "Score 55 + FLAG -> confirm",
);

// Low trust score -> block
assert(
  meerkat.evaluateResult({
    trust_score: 25,
    status: "BLOCK",
    checks: {},
    flags: ["critical_numerical_mismatch"],
    recommendations: ["Medication dose error detected"],
    audit_id: "test_3",
  }) === "block",
  "Score 25 + BLOCK -> block",
);

// Edge case: BLOCK status overrides high score
assert(
  meerkat.evaluateResult({
    trust_score: 80,
    status: "BLOCK",
    checks: {},
    flags: ["critical_numerical_mismatch"],
    recommendations: [],
    audit_id: "test_4",
  }) === "block",
  "BLOCK status overrides high score",
);

// Edge case: FLAG status with high score -> confirm
assert(
  meerkat.evaluateResult({
    trust_score: 75,
    status: "FLAG",
    checks: {},
    flags: ["numerical_warning"],
    recommendations: [],
    audit_id: "test_5",
  }) === "confirm",
  "FLAG status with score 75 -> confirm",
);

// Edge case: Score exactly at threshold
assert(
  meerkat.evaluateResult({
    trust_score: 70,
    status: "PASS",
    checks: {},
    flags: [],
    recommendations: [],
    audit_id: "test_6",
  }) === "execute",
  "Score exactly 70 + PASS -> execute",
);

assert(
  meerkat.evaluateResult({
    trust_score: 40,
    status: "PASS",
    checks: {},
    flags: [],
    recommendations: [],
    audit_id: "test_7",
  }) === "confirm",
  "Score exactly 40 + PASS -> confirm (below auto-approve)",
);

// Custom thresholds
const strictMeerkat = new MeerkatInterceptor({
  apiKey: "mk_test_fake_key",
  autoApproveThreshold: 90,
  blockThreshold: 60,
});

assert(
  strictMeerkat.evaluateResult({
    trust_score: 85,
    status: "PASS",
    checks: {},
    flags: [],
    recommendations: [],
    audit_id: "test_8",
  }) === "confirm",
  "Strict mode: Score 85 -> confirm (threshold 90)",
);

assert(
  strictMeerkat.evaluateResult({
    trust_score: 55,
    status: "FLAG",
    checks: {},
    flags: [],
    recommendations: [],
    audit_id: "test_9",
  }) === "block",
  "Strict mode: Score 55 -> block (threshold 60)",
);

// ── Summary ───────────────────────────────────────────────────────

console.log(`\n${"=".repeat(60)}`);
console.log(`Results: ${passed} passed, ${failed} failed out of ${passed + failed} total`);
console.log(`${"=".repeat(60)}`);

if (failed > 0) {
  process.exit(1);
}
