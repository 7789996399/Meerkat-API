import { Router } from "express";
import { AuthenticatedRequest } from "../middleware/auth";
import { scan, Sensitivity } from "../services/prompt-shield";
import prisma from "../lib/prisma";

const router = Router();

const VALID_SENSITIVITIES = new Set(["low", "medium", "high"]);

router.post("/", async (req: AuthenticatedRequest, res) => {
  const { input, domain, sensitivity } = req.body;

  if (!input || typeof input !== "string") {
    res.status(400).json({ error: "input is required and must be a string" });
    return;
  }

  const sens: Sensitivity = VALID_SENSITIVITIES.has(sensitivity) ? sensitivity : "medium";

  const result = scan(input, sens);

  // Log every detection to threat_log
  if (!result.safe && req.context) {
    await prisma.threatLog.create({
      data: {
        orgId: req.context.orgId,
        inputText: input.slice(0, 5000), // Truncate for storage
        threatLevel: result.threat_level as "LOW" | "MEDIUM" | "HIGH",
        attackType: result.attack_type || "unknown",
        actionTaken: result.action as "BLOCK" | "FLAG" | "SANITIZE",
        detail: result.detail,
      },
    });
  }

  res.json(result);
});

export default router;
