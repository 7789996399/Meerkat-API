import { Router } from "express";
import { AuthenticatedRequest } from "../middleware/auth";
import prisma from "../lib/prisma";

const router = Router();

router.get("/:auditId", async (req: AuthenticatedRequest, res) => {
  const auditId = req.params.auditId as string;

  const record = await prisma.verification.findUnique({
    where: { auditId },
  });

  if (!record) {
    res.status(404).json({ error: `Audit record not found: ${auditId}` });
    return;
  }

  if (record.orgId !== req.context!.orgId) {
    res.status(403).json({ error: "Access denied to this audit record" });
    return;
  }

  const response: any = {
    audit_id: record.auditId,
    org_id: record.orgId,
    timestamp: record.createdAt,
    domain: record.domain,
    agent_name: record.agentName,
    model_used: record.modelUsed,
    user_input: record.userInput,
    ai_output: record.aiOutput,
    source_context: record.sourceContext,
    trust_score: record.trustScore,
    status: record.status,
    checks: record.checksResults,
    flags: record.flags,
    human_review_required: record.humanReviewRequired,
    attempt: record.attempt,
    session_id: record.sessionId,
    verification_mode: record.verificationMode,
    remediation: record.remediation,
    review: {
      reviewed_by: record.reviewedBy,
      action: record.reviewAction,
      note: record.reviewNote,
      reviewed_at: record.reviewedAt,
    },
  };

  // Support ?include=session for full session history
  const include = req.query.include as string | undefined;
  if (include === "session" && record.sessionId) {
    const session = await prisma.verificationSession.findUnique({
      where: { sessionId: record.sessionId },
    });
    const sessionVerifications = await prisma.verification.findMany({
      where: { sessionId: record.sessionId },
      orderBy: { createdAt: "asc" },
      select: {
        auditId: true,
        attempt: true,
        trustScore: true,
        status: true,
        remediation: true,
        createdAt: true,
      },
    });

    if (session) {
      response.session = {
        session_id: session.sessionId,
        attempt_count: session.attemptCount,
        initial_status: session.initialStatus,
        final_status: session.finalStatus,
        resolved: session.resolved,
        created_at: session.createdAt,
        resolved_at: session.resolvedAt,
        attempts: sessionVerifications.map((v) => ({
          audit_id: v.auditId,
          attempt: v.attempt,
          trust_score: v.trustScore,
          status: v.status,
          remediation: v.remediation,
          timestamp: v.createdAt,
        })),
      };
    }
  }

  res.json(response);
});

export default router;
