import { Request, Response, NextFunction } from "express";
import crypto from "crypto";
import prisma from "../lib/prisma";
import { verifyToken, JwtPayload } from "../services/auth";

export interface OrgContext {
  orgId: string;
  orgName: string;
  plan: "starter" | "professional" | "enterprise";
  domain: string;
}

export interface UserContext {
  userId: string;
  email: string;
  name: string;
  role: string;
}

export interface AuthenticatedRequest extends Request {
  context?: OrgContext;
  user?: UserContext;
}

function extractKey(req: Request): string | null {
  // Try Authorization: Bearer mk_live_xxx
  const authHeader = req.headers.authorization;
  if (authHeader && authHeader.startsWith("Bearer ")) {
    return authHeader.slice(7);
  }

  // Try x-meerkat-key: mk_live_xxx
  const meerkatKey = req.headers["x-meerkat-key"];
  if (typeof meerkatKey === "string" && meerkatKey.length > 0) {
    return meerkatKey;
  }

  return null;
}

/**
 * Dual auth middleware: accepts API key OR JWT session cookie.
 * API key auth sets req.context (org context).
 * JWT cookie auth sets both req.context and req.user.
 */
export async function authenticate(
  req: AuthenticatedRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  // --- Try API key first ---
  const rawKey = extractKey(req);
  if (rawKey) {
    const keyHash = crypto.createHash("sha256").update(rawKey).digest("hex");

    const apiKey = await prisma.apiKey.findFirst({
      where: { keyHash },
      include: { org: true },
    });

    if (apiKey && apiKey.status === "active") {
      // Fire-and-forget timestamp update
      prisma.apiKey.update({
        where: { id: apiKey.id },
        data: { lastUsedAt: new Date() },
      }).catch(() => {});

      req.context = {
        orgId: apiKey.org.id,
        orgName: apiKey.org.name,
        plan: apiKey.org.plan as OrgContext["plan"],
        domain: apiKey.org.domain,
      };

      next();
      return;
    }
  }

  // --- Try JWT cookie ---
  const token = req.cookies?.meerkat_session;
  if (token) {
    try {
      const payload: JwtPayload = verifyToken(token);

      const user = await prisma.user.findUnique({
        where: { id: payload.sub },
        include: { org: true },
      });

      if (user) {
        req.context = {
          orgId: user.org.id,
          orgName: user.org.name,
          plan: user.org.plan as OrgContext["plan"],
          domain: user.org.domain,
        };

        req.user = {
          userId: user.id,
          email: user.email,
          name: user.name,
          role: user.role,
        };

        next();
        return;
      }
    } catch {
      // Invalid token, fall through to 401
    }
  }

  res.status(401).json({ error: "Authentication required. Provide an API key or sign in via Microsoft SSO." });
}
