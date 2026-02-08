import rateLimit from "express-rate-limit";
import { AuthenticatedRequest } from "./auth";

const PLAN_LIMITS: Record<string, number> = {
  starter: 100,
  professional: 1000,
  enterprise: 10000,
};

export const rateLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: (req) => {
    const plan = (req as AuthenticatedRequest).context?.plan;
    return PLAN_LIMITS[plan || "starter"] || 100;
  },
  keyGenerator: (req) => {
    // Rate-limit per org, not per IP
    return (req as AuthenticatedRequest).context?.orgId || req.ip || "anonymous";
  },
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: "Rate limit exceeded. Try again later." },
});
