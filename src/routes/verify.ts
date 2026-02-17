import { Router } from "express";
import crypto from "crypto";
import { AuthenticatedRequest } from "../middleware/auth";
import {
  entailment_check,
  semantic_entropy_check,
  implicit_preference_check,
  claim_extraction_check,
  numerical_verify_check,
  CheckResult,
} from "../services/governance-checks";
import { searchKnowledgeBase, ChunkMatch } from "../services/semantic-search";
import { checkVerificationLimit, incrementVerificationCount } from "../services/billing";
import prisma from "../lib/prisma";

const router = Router();

const ALL_CHECKS = ["entailment", "numerical_verify", "semantic_entropy", "implicit_preference", "claim_extraction"];

const WEIGHTS: Record<string, number> = {
  entailment: 0.30,
  numerical_verify: 0.20,
  semantic_entropy: 0.20,
  implicit_preference: 0.15,
  claim_extraction: 0.15,
};

router.post("/", async (req: AuthenticatedRequest, res) => {
  const { input, output, context, checks, domain, config_id, agent_name, model } = req.body;

  // --- Validate ---
  if (!input || typeof input !== "string") {
    res.status(400).json({ error: "input is required and must be a string" });
    return;
  }
  if (!output || typeof output !== "string") {
    res.status(400).json({ error: "output is required and must be a string" });
    return;
  }

  const orgId = req.context!.orgId;
  const resolvedDomain = domain || req.context!.domain;

  // --- Check verification limit (Starter plan) ---
  const org = await prisma.organization.findUnique({ where: { id: orgId } });
  if (org) {
    const limitError = checkVerificationLimit(org.plan, org.currentPeriodVerifications);
    if (limitError) {
      res.status(429).json(limitError);
      return;
    }
  }

  // --- Load org configuration ---
  let config;
  if (config_id) {
    config = await prisma.configuration.findFirst({
      where: { id: config_id, orgId },
    });
  }
  if (!config) {
    config = await prisma.configuration.findFirst({
      where: { orgId },
    });
  }

  const approveThreshold = config?.autoApproveThreshold ?? 85;
  const blockThreshold = config?.autoBlockThreshold ?? 40;
  const requiredChecks = (config?.requiredChecks as string[]) ?? ALL_CHECKS;
  const kbEnabled = config?.knowledgeBaseEnabled ?? false;
  const kbTopK = config?.kbTopK ?? 5;
  const kbMinRelevance = config?.kbMinRelevance ?? 0.75;

  // --- Knowledge base retrieval ---
  let knowledgeBaseUsed = false;
  let kbMatches: ChunkMatch[] = [];
  let kbContext = "";

  if (kbEnabled) {
    // Check if org has any indexed knowledge bases
    const indexedKbCount = await prisma.knowledgeBase.count({
      where: { orgId, status: "indexed" },
    });
    if (indexedKbCount > 0) {
      kbMatches = await searchKnowledgeBase(orgId, output, kbTopK, kbMinRelevance);
      if (kbMatches.length > 0) {
        knowledgeBaseUsed = true;
        kbContext = kbMatches.map((m) => m.content).join("\n\n");
      }
    }
  }

  // Merge requested checks with required checks (required always run)
  const requestedChecks = Array.isArray(checks) ? checks : [];
  const checksToRun = [...new Set([...requiredChecks, ...requestedChecks])].filter(
    (c) => ALL_CHECKS.includes(c)
  );

  // --- Run governance checks ---
  const checksResults: Record<string, CheckResult> = {};

  for (const check of checksToRun) {
    switch (check) {
      case "entailment":
        checksResults.entailment = await entailment_check(
          output,
          context || "",
          knowledgeBaseUsed ? kbContext : undefined,
        );
        break;
      case "semantic_entropy":
        checksResults.semantic_entropy = await semantic_entropy_check(input, output);
        break;
      case "implicit_preference":
        checksResults.implicit_preference = await implicit_preference_check(output, resolvedDomain, context);
        break;
      case "claim_extraction": {
        const claims = await claim_extraction_check(output, context || "");
        checksResults.claim_extraction = {
          score: claims.score,
          flags: claims.flags,
          detail: claims.detail,
        };
        break;
      }
      case "numerical_verify":
        checksResults.numerical_verify = await numerical_verify_check(
          output,
          context || "",
          resolvedDomain,
        );
        break;
    }
  }

  // --- Weighted trust score ---
  let weightedSum = 0;
  let totalWeight = 0;
  for (const [check, result] of Object.entries(checksResults)) {
    const w = WEIGHTS[check] ?? 0.25;
    weightedSum += result.score * w;
    totalWeight += w;
  }
  const trustScore = Math.round((weightedSum / Math.max(totalWeight, 0.01)) * 100);

  // --- Status from org thresholds ---
  let status: "PASS" | "FLAG" | "BLOCK";
  if (trustScore >= approveThreshold) status = "PASS";
  else if (trustScore >= blockThreshold) status = "FLAG";
  else status = "BLOCK";

  const allFlags = Object.values(checksResults).flatMap((r) => r.flags);
  const humanReviewRequired = status === "FLAG";

  // --- Recommendations ---
  const recommendations: string[] = [];
  if (allFlags.includes("entailment_contradiction")) {
    recommendations.push("Review AI output against source documents -- contradictions detected.");
  }
  if (allFlags.includes("low_entailment")) {
    recommendations.push("AI output has weak grounding in the source context. Verify key claims manually.");
  }
  if (allFlags.includes("high_uncertainty")) {
    recommendations.push("AI response shows low confidence. Consider requesting a more specific prompt.");
  }
  if (allFlags.includes("moderate_uncertainty")) {
    recommendations.push("AI response contains hedging language. Confidence is moderate.");
  }
  if (allFlags.includes("strong_bias")) {
    recommendations.push("Response contains strong directional language. Review for bias before delivery.");
  }
  if (allFlags.includes("mild_preference")) {
    recommendations.push("Mild directional preference detected. Consider balanced framing.");
  }
  if (allFlags.includes("unverified_claims")) {
    recommendations.push("Some factual claims could not be verified against source context.");
  }
  if (allFlags.includes("majority_unverified")) {
    recommendations.push("Most claims are unverified. This response should not be trusted without review.");
  }
  if (allFlags.includes("critical_numerical_mismatch")) {
    recommendations.push("CRITICAL: Numerical values (medication doses, lab values, or financial figures) do not match source. Immediate review required.");
  }
  if (allFlags.includes("numerical_distortion")) {
    recommendations.push("Numerical values in AI output differ from source data. Verify all numbers manually.");
  }
  if (allFlags.includes("ungrounded_numbers")) {
    recommendations.push("AI output contains numbers not present in source context. These may be fabricated.");
  }
  if (allFlags.includes("possible_fabrication")) {
    recommendations.push("Some claims have no supporting evidence in source context. Review for fabricated content.");
  }

  // --- Generate audit ID ---
  const timestamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 8);
  const hash = crypto.randomBytes(4).toString("hex");
  const auditId = `aud_${timestamp}_${hash}`;

  // --- Persist ---
  await prisma.verification.create({
    data: {
      orgId,
      auditId,
      agentName: agent_name || null,
      modelUsed: model || null,
      domain: resolvedDomain,
      userInput: input,
      aiOutput: output,
      sourceContext: context || null,
      trustScore,
      status,
      checksResults: checksResults as any,
      flags: allFlags as any,
      humanReviewRequired,
    },
  });

  // --- Increment verification counter ---
  await incrementVerificationCount(orgId);

  // --- Response ---
  res.json({
    trust_score: trustScore,
    status,
    checks: checksResults,
    audit_id: auditId,
    recommendations,
    knowledge_base_used: knowledgeBaseUsed,
    knowledge_base_matches: kbMatches.map((m) => ({
      chunk_id: m.chunk_id,
      document_name: m.document_name,
      relevance_score: m.relevance_score,
      content_preview: m.content_preview,
    })),
  });
});

export default router;
