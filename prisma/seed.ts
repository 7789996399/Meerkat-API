import { PrismaClient } from "@prisma/client";
import crypto from "crypto";

const prisma = new PrismaClient();

function makeAuditId(index: number): string {
  const hash = crypto.randomBytes(4).toString("hex");
  return `aud_20260207_${hash}${index}`;
}

async function main() {
  // Clean existing data
  await prisma.threatLog.deleteMany();
  await prisma.verification.deleteMany();
  await prisma.configuration.deleteMany();
  await prisma.apiKey.deleteMany();
  await prisma.organization.deleteMany();

  // Create test organization
  const org = await prisma.organization.create({
    data: {
      name: "Meerkat Demo Org",
      plan: "professional",
      domain: "legal",
    },
  });

  console.log(`Created organization: ${org.name} (${org.id})`);

  // Create API key (raw key: mk_demo_test123)
  const rawKey = "mk_demo_test123";
  const keyHash = crypto.createHash("sha256").update(rawKey).digest("hex");

  const apiKey = await prisma.apiKey.create({
    data: {
      orgId: org.id,
      keyPrefix: "mk_demo_",
      keyHash,
      name: "production",
      status: "active",
    },
  });

  console.log(`Created API key: ${apiKey.keyPrefix}*** (${apiKey.id})`);

  // Create configuration
  const config = await prisma.configuration.create({
    data: {
      orgId: org.id,
      autoApproveThreshold: 85,
      autoBlockThreshold: 40,
      requiredChecks: ["entailment", "semantic_entropy", "implicit_preference", "claim_extraction"],
      optionalChecks: [],
      domainRules: {
        legal: { min_entailment: 0.7, max_entropy: 0.4 },
        financial: { min_entailment: 0.8, max_entropy: 0.3 },
        healthcare: { min_entailment: 0.9, max_entropy: 0.2 },
      },
      notificationSettings: {
        email: "admin@demo.meerkat.ai",
        slack_webhook: null,
        notify_on_block: true,
        notify_on_flag: false,
      },
    },
  });

  console.log(`Created configuration: ${config.id}`);

  // 10 sample verifications
  const verifications = [
    {
      agentName: "legal-review-agent",
      modelUsed: "claude-sonnet-4-5-20250929",
      domain: "legal" as const,
      userInput: "Review this NDA and identify high-risk clauses.",
      aiOutput: "Section 3.1 contains a 12-month non-compete clause limited to a 50-mile radius of Vancouver, BC. Section 5.2 establishes a 2-year confidentiality period. Section 7.1 requires 30 days written notice for termination. These are standard provisions for a technology-sector NDA in British Columbia.",
      sourceContext: "Section 3.1: Non-Compete. For a period of twelve (12) months following termination, Employee shall not engage in competing business within a fifty (50) mile radius of Vancouver, British Columbia. Section 5.2: Confidentiality obligations shall survive for two (2) years post-termination. Section 7.1: Either party may terminate this agreement with thirty (30) days written notice.",
      trustScore: 94,
      status: "PASS" as const,
      checksResults: {
        entailment: { score: 0.96, flags: [], detail: "All claims grounded in source document." },
        semantic_entropy: { score: 0.91, flags: [], detail: "High confidence with specific facts." },
        implicit_preference: { score: 0.88, flags: [], detail: "Neutral, balanced language." },
        claim_extraction: { score: 1.0, flags: [], detail: "8 claims extracted. 8 verified." },
      },
      flags: [],
    },
    {
      agentName: "clinical-notes-agent",
      modelUsed: "claude-sonnet-4-5-20250929",
      domain: "healthcare" as const,
      userInput: "Verify this clinical note against the patient EHR.",
      aiOutput: "Patient presents with Type 2 diabetes managed with Metformin 500mg twice daily. HbA1c of 7.2% recorded on last visit. Blood pressure 128/82 mmHg within target range. No documented allergies. Follow-up scheduled in 3 months.",
      sourceContext: "EHR Summary: Dx: Type 2 Diabetes Mellitus (E11.9). Current medications: Metformin 500mg BID. Lab results (2026-01-15): HbA1c 7.2%, FBG 142 mg/dL. Vitals: BP 128/82, HR 72, Temp 98.6F. Allergies: NKDA. Next appointment: 2026-04-15.",
      trustScore: 88,
      status: "PASS" as const,
      checksResults: {
        entailment: { score: 0.94, flags: [], detail: "Clinical details match EHR records." },
        semantic_entropy: { score: 0.87, flags: [], detail: "Specific clinical values cited." },
        implicit_preference: { score: 0.82, flags: [], detail: "Clinical language is neutral." },
        claim_extraction: { score: 0.85, flags: [], detail: "6 claims extracted. 5 verified, 1 unverified." },
      },
      flags: [],
    },
    {
      agentName: "portfolio-analysis-agent",
      modelUsed: "gpt-4o",
      domain: "financial" as const,
      userInput: "Analyze the risk profile of this investment portfolio.",
      aiOutput: "Portfolio is overweight in technology equities at 42% allocation versus the benchmark 28%. Fixed income allocation of 25% provides moderate downside protection. The Sharpe ratio of 1.34 indicates strong risk-adjusted returns over the trailing 12-month period. Recommendation: rebalance technology to 35% to reduce sector concentration risk.",
      sourceContext: "Portfolio Holdings Report (Q4 2025): Technology sector: 42.1% (Benchmark: 28.3%). Fixed Income: 25.4%. Healthcare: 15.2%. Consumer: 10.1%. Cash: 7.2%. Performance metrics (trailing 12M): Return 18.7%, Volatility 14.0%, Sharpe Ratio 1.34, Max Drawdown -8.2%.",
      trustScore: 85,
      status: "PASS" as const,
      checksResults: {
        entailment: { score: 0.91, flags: [], detail: "Portfolio figures match source report." },
        semantic_entropy: { score: 0.78, flags: [], detail: "Analysis shows moderate confidence." },
        implicit_preference: { score: 0.80, flags: ["mild_preference"], detail: "Rebalance recommendation shows mild directional bias." },
        claim_extraction: { score: 0.88, flags: [], detail: "5 claims extracted. 4 verified, 1 unverified." },
      },
      flags: ["mild_preference"],
    },
    {
      agentName: "legal-review-agent",
      modelUsed: "claude-sonnet-4-5-20250929",
      domain: "legal" as const,
      userInput: "Check this employment contract termination clause.",
      aiOutput: "The termination clause in Section 9.3 allows either party to terminate with 60 days written notice. The employer retains the right to terminate for cause immediately. Severance of 2 weeks per year of service applies for termination without cause, capped at 12 months.",
      sourceContext: "Section 9.3 Termination: (a) Either party may terminate this agreement by providing sixty (60) calendar days written notice. (b) Employer may terminate immediately for cause as defined in Section 9.4. (c) Upon termination without cause, Employee shall receive severance equal to two (2) weeks base salary per completed year of service, not to exceed twelve (12) months of base salary.",
      trustScore: 79,
      status: "PASS" as const,
      checksResults: {
        entailment: { score: 0.88, flags: [], detail: "Termination terms accurately reflected." },
        semantic_entropy: { score: 0.72, flags: [], detail: "Moderate confidence in clause interpretation." },
        implicit_preference: { score: 0.70, flags: ["mild_preference"], detail: "Slightly employer-favoring framing." },
        claim_extraction: { score: 0.75, flags: [], detail: "4 claims extracted. 3 verified, 1 unverified." },
      },
      flags: ["mild_preference"],
    },
    {
      agentName: "clinical-notes-agent",
      modelUsed: "claude-sonnet-4-5-20250929",
      domain: "healthcare" as const,
      userInput: "Reconcile this medication list with the pharmacy record.",
      aiOutput: "The patient's medication list includes Lisinopril 10mg daily and Amlodipine 5mg daily for hypertension. The pharmacy record shows Lisinopril 20mg daily, which may indicate a recent dosage change not yet reflected in the chart. Atorvastatin 40mg appears in both records. Aspirin 81mg is listed in the pharmacy but not in the provider's medication list.",
      sourceContext: "Provider medication list: Lisinopril 10mg QD, Amlodipine 5mg QD, Atorvastatin 40mg QD. Pharmacy fill history (last 90 days): Lisinopril 20mg #30 (filled 2026-01-20), Amlodipine 5mg #30 (filled 2026-01-18), Atorvastatin 40mg #30 (filled 2026-01-18), Aspirin 81mg #90 (filled 2025-12-15).",
      trustScore: 67,
      status: "FLAG" as const,
      checksResults: {
        entailment: { score: 0.72, flags: [], detail: "Most medications match. Lisinopril dosage discrepancy noted." },
        semantic_entropy: { score: 0.55, flags: ["moderate_uncertainty"], detail: "Hedging language around dosage change." },
        implicit_preference: { score: 0.82, flags: [], detail: "Neutral clinical tone." },
        claim_extraction: { score: 0.50, flags: ["unverified_claims"], detail: "6 claims extracted. 3 verified, 2 unverified, 1 contradicted." },
      },
      flags: ["moderate_uncertainty", "unverified_claims"],
      humanReviewRequired: true,
    },
    {
      agentName: "risk-assessment-agent",
      modelUsed: "gpt-4o",
      domain: "financial" as const,
      userInput: "Evaluate the credit risk of this loan application.",
      aiOutput: "The applicant's debt-to-income ratio of approximately 38% is borderline for the requested loan amount. Credit history shows possibly 2 late payments in the past 24 months. The collateral valuation may need independent appraisal. Overall risk assessment suggests cautious approval with conditions.",
      sourceContext: "Loan Application #2026-0892: Requested amount: $450,000. Annual income: $125,000. Existing debt obligations: $47,500/year. Credit score: 712. Payment history: 2 late payments (30-day) in 24 months. Collateral: residential property, estimated value $580,000 (automated valuation).",
      trustScore: 58,
      status: "FLAG" as const,
      checksResults: {
        entailment: { score: 0.65, flags: [], detail: "Key figures approximately match but lack precision." },
        semantic_entropy: { score: 0.40, flags: ["moderate_uncertainty"], detail: "Multiple hedge words: approximately, possibly, may." },
        implicit_preference: { score: 0.72, flags: ["mild_preference"], detail: "Leans toward cautious approval without quantified basis." },
        claim_extraction: { score: 0.50, flags: ["unverified_claims"], detail: "4 claims extracted. 2 verified, 2 unverified." },
      },
      flags: ["moderate_uncertainty", "mild_preference", "unverified_claims"],
      humanReviewRequired: true,
    },
    {
      agentName: "legal-review-agent",
      modelUsed: "claude-sonnet-4-5-20250929",
      domain: "legal" as const,
      userInput: "Analyze the jurisdiction and governing law clauses.",
      aiOutput: "The agreement is governed by the laws of British Columbia, Canada. However, the arbitration clause in Section 14.2 may create complexity as it references JAMS arbitration rules, which are primarily a US-based arbitration body. This could potentially create enforcement challenges if disputes arise. The forum selection clause appears somewhat ambiguous.",
      sourceContext: "Section 14.1 Governing Law: This Agreement shall be governed by and construed in accordance with the laws of British Columbia, Canada. Section 14.2 Dispute Resolution: Any dispute arising under this Agreement shall be resolved by binding arbitration administered by JAMS in accordance with its Comprehensive Arbitration Rules. Section 14.3 Forum: Arbitration shall be conducted in Vancouver, British Columbia.",
      trustScore: 51,
      status: "FLAG" as const,
      checksResults: {
        entailment: { score: 0.60, flags: [], detail: "Governing law correctly identified. JAMS reference accurate." },
        semantic_entropy: { score: 0.35, flags: ["moderate_uncertainty"], detail: "Significant hedging: may, could, potentially, appears, somewhat." },
        implicit_preference: { score: 0.68, flags: ["mild_preference"], detail: "Frames JAMS negatively without balanced analysis." },
        claim_extraction: { score: 0.33, flags: ["unverified_claims"], detail: "3 claims extracted. 1 verified, 2 unverified." },
      },
      flags: ["moderate_uncertainty", "mild_preference", "unverified_claims"],
      humanReviewRequired: true,
    },
    {
      agentName: "clinical-notes-agent",
      modelUsed: "gpt-4o",
      domain: "healthcare" as const,
      userInput: "Verify this diagnosis against the lab results and clinical findings.",
      aiOutput: "Based on the presented symptoms and lab results, the patient has Stage 3 chronic kidney disease with an eGFR of 42 mL/min. The elevated creatinine of 2.8 mg/dL confirms renal impairment. Recommend nephrology referral and ACE inhibitor therapy initiation.",
      sourceContext: "Lab results (2026-02-01): Creatinine 1.8 mg/dL, eGFR 58 mL/min, BUN 24 mg/dL. Urinalysis: protein trace. Clinical notes: Patient reports mild fatigue. No edema. BP 138/88. Assessment: Stage 2 CKD, monitor and recheck in 3 months.",
      trustScore: 28,
      status: "BLOCK" as const,
      checksResults: {
        entailment: { score: 0.20, flags: ["entailment_contradiction"], detail: "Creatinine and eGFR values contradict source. Stage misclassified." },
        semantic_entropy: { score: 0.70, flags: [], detail: "Confident tone but factually incorrect." },
        implicit_preference: { score: 0.75, flags: [], detail: "Treatment recommendation not supported by evidence." },
        claim_extraction: { score: 0.0, flags: ["unverified_claims"], detail: "4 claims extracted. 0 verified, 1 unverified, 3 contradicted." },
      },
      flags: ["entailment_contradiction", "unverified_claims"],
    },
    {
      agentName: "portfolio-analysis-agent",
      modelUsed: "gpt-4o",
      domain: "financial" as const,
      userInput: "Compare this quarterly report against the SEC filing.",
      aiOutput: "Revenue for Q4 2025 was $847 million, representing 23% year-over-year growth. Operating margin improved to 18.5%. The company raised full-year 2026 guidance to $3.8 billion, citing strong enterprise demand. Net income was $156 million.",
      sourceContext: "SEC Form 10-Q (Q4 2025): Revenue: $782.3 million (YoY growth: 17.2%). Operating income: $118.4 million (operating margin: 15.1%). Net income: $89.7 million. 2026 guidance: Revenue $3.2-3.4 billion. Management commentary: Enterprise segment showed solid demand.",
      trustScore: 19,
      status: "BLOCK" as const,
      checksResults: {
        entailment: { score: 0.10, flags: ["entailment_contradiction"], detail: "Revenue, margin, net income, and guidance all contradict SEC filing." },
        semantic_entropy: { score: 0.85, flags: [], detail: "Very confident assertions with specific numbers." },
        implicit_preference: { score: 0.60, flags: ["mild_preference"], detail: "Uniformly positive framing of financials." },
        claim_extraction: { score: 0.0, flags: ["unverified_claims"], detail: "5 claims extracted. 0 verified, 0 unverified, 5 contradicted." },
      },
      flags: ["entailment_contradiction", "mild_preference", "unverified_claims"],
    },
    {
      agentName: "legal-review-agent",
      modelUsed: "claude-sonnet-4-5-20250929",
      domain: "legal" as const,
      userInput: "Assess enforceability of this non-compete clause.",
      aiOutput: "The non-compete restricts the employee from working in any capacity in the technology industry worldwide for a period of 5 years. Courts in British Columbia have consistently upheld such broad restrictions as reasonable and enforceable. The $500,000 liquidated damages clause is standard for this type of agreement.",
      sourceContext: "Section 3.1 Non-Compete: Employee agrees not to engage in competing business within a 50-mile radius of Vancouver for twelve (12) months post-termination. Section 3.5 Remedies: In the event of breach, Employer shall be entitled to injunctive relief. No liquidated damages clause present. BC case law: generally restrictive non-competes limited in scope, duration, and geography are enforceable; overly broad restrictions are routinely struck down.",
      trustScore: 12,
      status: "BLOCK" as const,
      checksResults: {
        entailment: { score: 0.05, flags: ["entailment_contradiction"], detail: "Duration, scope, geography, damages all fabricated or contradicted." },
        semantic_entropy: { score: 0.80, flags: [], detail: "Highly confident but entirely wrong." },
        implicit_preference: { score: 0.30, flags: ["strong_bias"], detail: "Presents fabricated terms as standard. Strong employer-favoring bias." },
        claim_extraction: { score: 0.0, flags: ["unverified_claims"], detail: "5 claims extracted. 0 verified, 0 unverified, 5 contradicted." },
      },
      flags: ["entailment_contradiction", "strong_bias", "unverified_claims"],
    },
  ];

  for (let i = 0; i < verifications.length; i++) {
    const v = verifications[i];
    await prisma.verification.create({
      data: {
        orgId: org.id,
        auditId: makeAuditId(i),
        agentName: v.agentName,
        modelUsed: v.modelUsed,
        domain: v.domain,
        userInput: v.userInput,
        aiOutput: v.aiOutput,
        sourceContext: v.sourceContext,
        trustScore: v.trustScore,
        status: v.status,
        checksResults: v.checksResults,
        flags: v.flags,
        humanReviewRequired: "humanReviewRequired" in v ? v.humanReviewRequired : false,
      },
    });
  }

  console.log(`Created ${verifications.length} sample verifications`);

  // Summary
  const pass = verifications.filter((v) => v.status === "PASS").length;
  const flag = verifications.filter((v) => v.status === "FLAG").length;
  const block = verifications.filter((v) => v.status === "BLOCK").length;
  console.log(`  PASS: ${pass}, FLAG: ${flag}, BLOCK: ${block}`);
  console.log(`\nAPI key for testing: ${rawKey}`);
  console.log("Done.");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
