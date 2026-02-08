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

  res.json({
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
    review: {
      reviewed_by: record.reviewedBy,
      action: record.reviewAction,
      note: record.reviewNote,
      reviewed_at: record.reviewedAt,
    },
  });
});

export default router;
