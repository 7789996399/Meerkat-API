import { Router } from "express";
import crypto from "crypto";
import { AuthenticatedRequest } from "../middleware/auth";
import { scanEnhanced, Sensitivity } from "../services/prompt-shield";
import prisma from "../lib/prisma";

const router = Router();

const VALID_SENSITIVITIES = new Set(["low", "medium", "high"]);

router.post("/", async (req: AuthenticatedRequest, res) => {
  const { input, domain, sensitivity, session_id } = req.body;

  if (!input || typeof input !== "string") {
    res.status(400).json({ error: "input is required and must be a string" });
    return;
  }

  const sens: Sensitivity = VALID_SENSITIVITIES.has(sensitivity) ? sensitivity : "medium";
  const orgId = req.context?.orgId;

  // --- Session resolution ---
  let sessionId: string;
  if (session_id && typeof session_id === "string") {
    // Validate existing session
    if (orgId) {
      const existingSession = await prisma.verificationSession.findUnique({
        where: { sessionId: session_id },
      });

      if (existingSession && existingSession.orgId !== orgId) {
        res.status(403).json({ error: "Access denied to this session" });
        return;
      }
    }
    sessionId = session_id;
  } else {
    sessionId = `ses_${crypto.randomUUID()}`;
  }

  // --- Run enhanced scan ---
  const result = scanEnhanced(input, sens);

  // --- Generate audit ID ---
  const timestamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 8);
  const hash = crypto.randomBytes(4).toString("hex");
  const auditId = `aud_shd_${timestamp}_${hash}`;

  // --- Persist threat log ---
  if (!result.safe && orgId) {
    const primaryType = result.threats[0]?.type || "unknown";

    // Map suggested_action to ThreatAction enum
    let actionTaken: "BLOCK" | "FLAG" | "SANITIZE";
    if (result.remediation?.suggested_action === "QUARANTINE_FULL_MESSAGE") {
      actionTaken = "BLOCK";
    } else if (result.remediation?.suggested_action === "REQUEST_HUMAN_REVIEW") {
      actionTaken = "FLAG";
    } else {
      actionTaken = "SANITIZE";
    }

    // Map threat_level to ThreatLevel enum
    const threatLevelMap: Record<string, "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"> = {
      LOW: "LOW",
      MEDIUM: "MEDIUM",
      HIGH: "HIGH",
      CRITICAL: "CRITICAL",
    };
    const threatLevel = threatLevelMap[result.threat_level] || "HIGH";

    // --- Upsert session (must exist before threat log due to FK) ---
    const existingSession = await prisma.verificationSession.findUnique({
      where: { sessionId },
    });

    // Use BLOCK for threats, PASS for safe
    const sessionStatus = result.safe ? "PASS" as const : "BLOCK" as const;

    if (existingSession) {
      // Session exists — update it, upgrade type to full_pipeline if it was "verify"
      const newType =
        existingSession.type === "verify" ? "full_pipeline" : existingSession.type;
      await prisma.verificationSession.update({
        where: { sessionId },
        data: {
          latestAudit: auditId,
          attemptCount: existingSession.attemptCount + 1,
          type: newType,
        },
      });
    } else {
      // New session
      await prisma.verificationSession.create({
        data: {
          sessionId,
          orgId,
          type: "shield",
          firstAudit: auditId,
          latestAudit: auditId,
          attemptCount: 1,
          initialStatus: sessionStatus,
          resolved: result.safe,
          resolvedAt: result.safe ? new Date() : null,
          finalStatus: result.safe ? sessionStatus : null,
        },
      });
    }

    await prisma.threatLog.create({
      data: {
        orgId,
        auditId,
        sessionId,
        inputText: input.slice(0, 5000),
        threatLevel,
        attackType: primaryType,
        actionTaken,
        detail: result.remediation?.message || "Threat detected.",
        sanitizedInput: result.sanitized_input?.slice(0, 5000) || null,
        threats: result.threats as any,
        remediation: result.remediation as any,
      },
    });
  }

  // --- Response ---
  const response: any = {
    safe: result.safe,
    threat_level: result.threat_level,
    audit_id: auditId,
    session_id: sessionId,
  };

  if (!result.safe) {
    response.threats = result.threats;
    response.sanitized_input = result.sanitized_input;
    response.remediation = result.remediation;
  }

  res.json(response);
});

export default router;
