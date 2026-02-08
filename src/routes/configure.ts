import { Router } from "express";
import { AuthenticatedRequest } from "../middleware/auth";
import prisma from "../lib/prisma";

const router = Router();

const VALID_CHECKS = ["entailment", "semantic_entropy", "implicit_preference", "claim_extraction"];

router.post("/", async (req: AuthenticatedRequest, res) => {
  const orgId = req.context!.orgId;

  const {
    auto_approve_threshold,
    auto_block_threshold,
    required_checks,
    optional_checks,
    domain_rules,
    notification_settings,
    knowledge_base_enabled,
    kb_top_k,
    kb_min_relevance,
  } = req.body;

  // Validate thresholds
  if (auto_approve_threshold != null && (typeof auto_approve_threshold !== "number" || auto_approve_threshold < 0 || auto_approve_threshold > 100)) {
    res.status(400).json({ error: "auto_approve_threshold must be a number between 0 and 100" });
    return;
  }
  if (auto_block_threshold != null && (typeof auto_block_threshold !== "number" || auto_block_threshold < 0 || auto_block_threshold > 100)) {
    res.status(400).json({ error: "auto_block_threshold must be a number between 0 and 100" });
    return;
  }

  // Load existing to merge partial updates
  const existing = await prisma.configuration.findFirst({ where: { orgId } });

  const approve = auto_approve_threshold ?? existing?.autoApproveThreshold ?? 85;
  const block = auto_block_threshold ?? existing?.autoBlockThreshold ?? 40;

  if (approve <= block) {
    res.status(400).json({ error: `auto_approve_threshold (${approve}) must be greater than auto_block_threshold (${block})` });
    return;
  }

  // Validate check names if provided
  if (required_checks != null) {
    if (!Array.isArray(required_checks)) {
      res.status(400).json({ error: "required_checks must be an array" });
      return;
    }
    const invalid = required_checks.filter((c: string) => !VALID_CHECKS.includes(c));
    if (invalid.length > 0) {
      res.status(400).json({ error: `Invalid check names: ${invalid.join(", ")}. Valid: ${VALID_CHECKS.join(", ")}` });
      return;
    }
  }

  const data = {
    autoApproveThreshold: approve,
    autoBlockThreshold: block,
    requiredChecks: required_checks ?? existing?.requiredChecks ?? VALID_CHECKS,
    optionalChecks: optional_checks ?? existing?.optionalChecks ?? [],
    domainRules: domain_rules ?? existing?.domainRules ?? {},
    notificationSettings: notification_settings ?? existing?.notificationSettings ?? {},
    knowledgeBaseEnabled: knowledge_base_enabled ?? existing?.knowledgeBaseEnabled ?? false,
    kbTopK: kb_top_k ?? existing?.kbTopK ?? 5,
    kbMinRelevance: kb_min_relevance ?? existing?.kbMinRelevance ?? 0.75,
  };

  const config = existing
    ? await prisma.configuration.update({ where: { id: existing.id }, data })
    : await prisma.configuration.create({ data: { orgId, ...data } });

  res.json({
    config_id: config.id,
    org_id: config.orgId,
    auto_approve_threshold: config.autoApproveThreshold,
    auto_block_threshold: config.autoBlockThreshold,
    required_checks: config.requiredChecks,
    optional_checks: config.optionalChecks,
    domain_rules: config.domainRules,
    notification_settings: config.notificationSettings,
    knowledge_base_enabled: config.knowledgeBaseEnabled,
    kb_top_k: config.kbTopK,
    kb_min_relevance: config.kbMinRelevance,
    updated_at: config.updatedAt,
  });
});

router.get("/", async (req: AuthenticatedRequest, res) => {
  const config = await prisma.configuration.findFirst({
    where: { orgId: req.context!.orgId },
  });

  if (!config) {
    res.status(404).json({ error: "No configuration found. POST to create one." });
    return;
  }

  res.json({
    config_id: config.id,
    org_id: config.orgId,
    auto_approve_threshold: config.autoApproveThreshold,
    auto_block_threshold: config.autoBlockThreshold,
    required_checks: config.requiredChecks,
    optional_checks: config.optionalChecks,
    domain_rules: config.domainRules,
    notification_settings: config.notificationSettings,
    knowledge_base_enabled: config.knowledgeBaseEnabled,
    kb_top_k: config.kbTopK,
    kb_min_relevance: config.kbMinRelevance,
    updated_at: config.updatedAt,
  });
});

export default router;
