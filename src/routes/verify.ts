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
import { buildRemediation } from "../services/remediation";
import { Remediation } from "../types/remediation";
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
  const { input, output, context, checks, domain, config_id, agent_name, model, session_id } = req.body;

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
  const maxRetries = config?.maxRetries ?? 3;

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

  // --- Determine verification mode ---
  let verificationMode: string;
  if (context && context.trim().length > 0) {
    verificationMode = "grounded";
  } else if (knowledgeBaseUsed) {
    verificationMode = "knowledge_base";
  } else {
    verificationMode = "self_consistency";
  }

  // --- Session resolution ---
  let sessionId: string;
  let attempt: number;
  let linkedAttempts: string[] | undefined;

  if (session_id && typeof session_id === "string") {
    const existingSession = await prisma.verificationSession.findUnique({
      where: { sessionId: session_id },
    });

    if (!existingSession) {
      res.status(404).json({ error: `Session not found: ${session_id}` });
      return;
    }
    if (existingSession.orgId !== orgId) {
      res.status(403).json({ error: "Access denied to this session" });
      return;
    }
    if (existingSession.resolved) {
      res.status(409).json({ error: "Session is already resolved" });
      return;
    }
    if (existingSession.attemptCount >= maxRetries) {
      res.status(409).json({ error: `Maximum retries (${maxRetries}) reached for this session` });
      return;
    }

    sessionId = session_id;
    attempt = existingSession.attemptCount + 1;

    // Fetch linked audit IDs
    const linkedVerifications = await prisma.verification.findMany({
      where: { sessionId },
      select: { auditId: true },
      orderBy: { createdAt: "asc" },
    });
    linkedAttempts = linkedVerifications.map((v) => v.auditId);
  } else {
    sessionId = `ses_${crypto.randomUUID()}`;
    attempt = 1;
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
          corrections: claims.corrections,
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

  // --- Build remediation for non-PASS ---
  let remediation: Remediation | undefined;
  if (status !== "PASS") {
    remediation = buildRemediation({
      status,
      checksResults,
      allFlags,
      attempt,
      maxRetries,
    });

    // Prepend self-consistency warning if no source context
    if (verificationMode === "self_consistency") {
      remediation.message =
        "Limited verification: no source context provided. Connect a knowledge base for full grounded verification. " +
        remediation.message;
    }
  }

  // --- Generate audit ID ---
  const timestamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 8);
  const hash = crypto.randomBytes(4).toString("hex");
  const auditId = `aud_${timestamp}_${hash}`;

  // --- Persist verification ---
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
      sessionId,
      attempt,
      remediation: remediation ? (remediation as any) : null,
      verificationMode,
    },
  });

  // --- Upsert session ---
  if (attempt === 1) {
    await prisma.verificationSession.create({
      data: {
        sessionId,
        orgId,
        firstAudit: auditId,
        latestAudit: auditId,
        attemptCount: 1,
        initialStatus: status,
        resolved: status === "PASS",
        resolvedAt: status === "PASS" ? new Date() : null,
        finalStatus: status === "PASS" ? status : null,
      },
    });
  } else {
    const isResolved = status === "PASS" || attempt >= maxRetries;
    await prisma.verificationSession.update({
      where: { sessionId },
      data: {
        latestAudit: auditId,
        attemptCount: attempt,
        resolved: isResolved,
        resolvedAt: isResolved ? new Date() : null,
        finalStatus: isResolved ? status : null,
      },
    });
  }

  // --- Increment verification counter ---
  await incrementVerificationCount(orgId);

  // --- Strip internal corrections from checks before response ---
  const responseChecks: Record<string, { score: number; flags: string[]; detail: string }> = {};
  for (const [key, result] of Object.entries(checksResults)) {
    responseChecks[key] = {
      score: result.score,
      flags: result.flags,
      detail: result.detail,
    };
  }

  // --- Response ---
  const response: any = {
    trust_score: trustScore,
    status,
    checks: responseChecks,
    audit_id: auditId,
    attempt,
    session_id: sessionId,
    verification_mode: verificationMode,
    recommendations,
    knowledge_base_used: knowledgeBaseUsed,
    knowledge_base_matches: kbMatches.map((m) => ({
      chunk_id: m.chunk_id,
      document_name: m.document_name,
      relevance_score: m.relevance_score,
      content_preview: m.content_preview,
    })),
  };

  if (remediation) {
    response.remediation = remediation;
  }

  if (linkedAttempts && linkedAttempts.length > 0) {
    response.linked_attempts = linkedAttempts;
  }

  res.json(response);
});

export default router;
