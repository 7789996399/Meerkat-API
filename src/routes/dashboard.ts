import { Router } from "express";
import { AuthenticatedRequest } from "../middleware/auth";
import prisma from "../lib/prisma";

const router = Router();

const PERIOD_MS: Record<string, number> = {
  "24h": 24 * 60 * 60 * 1000,
  "7d": 7 * 24 * 60 * 60 * 1000,
  "30d": 30 * 24 * 60 * 60 * 1000,
  "90d": 90 * 24 * 60 * 60 * 1000,
};

router.get("/", async (req: AuthenticatedRequest, res) => {
  const orgId = req.context!.orgId;

  const periodKey = (req.query.period as string) || "7d";
  const periodMs = PERIOD_MS[periodKey];
  if (!periodMs) {
    res.status(400).json({ error: "Invalid period. Use 24h, 7d, 30d, or 90d." });
    return;
  }

  const now = new Date();
  const periodStart = new Date(now.getTime() - periodMs);
  const prevPeriodStart = new Date(periodStart.getTime() - periodMs);

  // Current period + previous period in parallel
  const [verifications, prevVerifications, threats] = await Promise.all([
    prisma.verification.findMany({
      where: { orgId, createdAt: { gte: periodStart } },
    }),
    prisma.verification.findMany({
      where: { orgId, createdAt: { gte: prevPeriodStart, lt: periodStart } },
    }),
    prisma.threatLog.findMany({
      where: { orgId, createdAt: { gte: periodStart } },
    }),
  ]);

  const total = verifications.length;
  const avgScore = total > 0
    ? Math.round(verifications.reduce((s, v) => s + v.trustScore, 0) / total)
    : 0;
  const passed = verifications.filter((v) => v.status === "PASS").length;
  const flagged = verifications.filter((v) => v.status === "FLAG").length;
  const blocked = verifications.filter((v) => v.status === "BLOCK").length;

  // Top flags
  const flagCounts: Record<string, number> = {};
  for (const v of verifications) {
    const flags = v.flags as string[];
    for (const f of flags) {
      flagCounts[f] = (flagCounts[f] || 0) + 1;
    }
  }
  const topFlags = Object.entries(flagCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([type, count]) => ({ type, count }));

  // Compliance
  const complianceScore = total > 0 ? Math.round((passed / total) * 100) : 100;

  // Trend: compare compliance to previous period
  const prevTotal = prevVerifications.length;
  const prevPassed = prevVerifications.filter((v) => v.status === "PASS").length;
  const prevCompliance = prevTotal > 0 ? Math.round((prevPassed / prevTotal) * 100) : 100;

  let trend: "improving" | "stable" | "declining";
  if (prevTotal === 0) {
    trend = "stable";
  } else if (complianceScore > prevCompliance + 5) {
    trend = "improving";
  } else if (complianceScore < prevCompliance - 5) {
    trend = "declining";
  } else {
    trend = "stable";
  }

  res.json({
    period: `${periodStart.toISOString().slice(0, 10)} to ${now.toISOString().slice(0, 10)}`,
    total_verifications: total,
    avg_trust_score: avgScore,
    auto_approved: passed,
    flagged_for_review: flagged,
    auto_blocked: blocked,
    injection_attempts_blocked: threats.length,
    top_flags: topFlags,
    compliance_score: complianceScore,
    trend,
  });
});

export default router;
