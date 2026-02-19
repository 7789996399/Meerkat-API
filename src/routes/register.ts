import { Router, Request, Response } from "express";
import crypto from "crypto";
import prisma from "../lib/prisma";

const router = Router();

// ---------------------------------------------------------------------------
// In-memory rate limiting: max 5 registrations per IP per hour
// ---------------------------------------------------------------------------
const ipAttempts = new Map<string, number[]>();
const RATE_LIMIT_WINDOW = 60 * 60 * 1000; // 1 hour
const RATE_LIMIT_MAX = 5;

function isRateLimited(ip: string): boolean {
  const cutoff = Date.now() - RATE_LIMIT_WINDOW;
  const attempts = (ipAttempts.get(ip) || []).filter((t) => t > cutoff);
  ipAttempts.set(ip, attempts);
  return attempts.length >= RATE_LIMIT_MAX;
}

function recordAttempt(ip: string): void {
  const cutoff = Date.now() - RATE_LIMIT_WINDOW;
  const attempts = (ipAttempts.get(ip) || []).filter((t) => t > cutoff);
  attempts.push(Date.now());
  ipAttempts.set(ip, attempts);
}

// ---------------------------------------------------------------------------
// POST /v1/register
// ---------------------------------------------------------------------------
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

router.post("/", async (req: Request, res: Response) => {
  const ip = req.ip || "unknown";

  if (isRateLimited(ip)) {
    res.status(429).json({ error: "Too many registration attempts. Try again later." });
    return;
  }

  const { email } = req.body;

  if (!email || typeof email !== "string" || !EMAIL_RE.test(email.trim())) {
    res.status(400).json({ error: "Valid email address is required." });
    return;
  }

  const normalizedEmail = email.toLowerCase().trim();

  // Check if email already registered
  const existing = await prisma.organization.findUnique({
    where: { email: normalizedEmail },
    include: { apiKeys: { where: { status: "active" }, take: 1 } },
  });

  if (existing) {
    const hint = existing.apiKeys[0]?.keyPrefix
      ? `${existing.apiKeys[0].keyPrefix}****`
      : null;
    res.status(409).json({
      error: "Email already registered. Use your existing API key.",
      key_hint: hint,
    });
    return;
  }

  // Record successful registration attempt for rate limiting
  recordAttempt(ip);

  // Generate API key
  const rawKey = `mk_live_${crypto.randomUUID()}`;
  const keyHash = crypto.createHash("sha256").update(rawKey).digest("hex");
  const orgName = normalizedEmail.split("@")[0];

  // Create org + API key + default configuration in a transaction
  await prisma.$transaction(async (tx) => {
    const org = await tx.organization.create({
      data: {
        name: orgName,
        email: normalizedEmail,
        plan: "starter",
        domain: "legal",
      },
    });

    await tx.apiKey.create({
      data: {
        orgId: org.id,
        keyPrefix: "mk_live_",
        keyHash,
        name: "default",
        status: "active",
      },
    });

    await tx.configuration.create({
      data: {
        orgId: org.id,
        autoApproveThreshold: 85,
        autoBlockThreshold: 40,
        requiredChecks: [
          "numerical_verify",
          "claim_extraction",
          "implicit_preference",
        ],
        optionalChecks: [],
        domainRules: {},
        notificationSettings: { email: normalizedEmail },
      },
    });
  });

  res.status(201).json({
    api_key: rawKey,
    plan: "starter",
    limits: {
      verifications_per_month: 10000,
      checks: [
        "numerical_verify",
        "claim_extraction",
        "implicit_preference",
      ],
      audit_retention_days: 7,
    },
  });
});

export default router;
