import { Router, Request, Response } from "express";
import { getAuthUrl, handleCallback, verifyToken } from "../services/auth";
import prisma from "../lib/prisma";

const router = Router();

/**
 * GET /auth/microsoft
 * Redirects the user to Microsoft login page.
 */
router.get("/microsoft", async (_req: Request, res: Response) => {
  try {
    const url = await getAuthUrl();
    res.redirect(url);
  } catch (err: any) {
    console.error("[auth] Failed to generate auth URL:", err.message);
    res.status(500).json({ error: "SSO configuration error. Check server environment variables." });
  }
});

/**
 * GET /auth/microsoft/callback
 * Handles the redirect from Microsoft after authentication.
 * Sets an httpOnly cookie with the JWT session token.
 */
router.get("/microsoft/callback", async (req: Request, res: Response) => {
  const code = req.query.code as string;
  const error = req.query.error as string;

  if (error) {
    const errorDescription = req.query.error_description as string;
    console.error(`[auth] Microsoft login error: ${error} - ${errorDescription}`);
    res.status(400).json({ error: "Microsoft login failed", detail: errorDescription });
    return;
  }

  if (!code) {
    res.status(400).json({ error: "Missing authorization code" });
    return;
  }

  try {
    const result = await handleCallback(code);

    // Set httpOnly cookie
    res.cookie("meerkat_session", result.token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      maxAge: 8 * 60 * 60 * 1000, // 8 hours
      path: "/",
    });

    // If a frontend URL is configured, redirect there
    const frontendUrl = process.env.FRONTEND_URL;
    if (frontendUrl) {
      res.redirect(`${frontendUrl}/auth/success`);
      return;
    }

    // Otherwise return JSON
    res.json({
      message: "Authentication successful",
      user: result.user,
    });
  } catch (err: any) {
    console.error("[auth] Callback error:", err.message);
    res.status(500).json({ error: "Authentication failed", detail: err.message });
  }
});

/**
 * GET /auth/me
 * Returns the current user's profile. Requires a valid JWT cookie.
 */
router.get("/me", async (req: Request, res: Response) => {
  const token = req.cookies?.meerkat_session;

  if (!token) {
    res.status(401).json({ error: "Not authenticated" });
    return;
  }

  try {
    const payload = verifyToken(token);

    const user = await prisma.user.findUnique({
      where: { id: payload.sub },
      include: { org: true },
    });

    if (!user) {
      res.status(401).json({ error: "User not found" });
      return;
    }

    res.json({
      id: user.id,
      email: user.email,
      name: user.name,
      role: user.role,
      org: {
        id: user.org.id,
        name: user.org.name,
        plan: user.org.plan,
        domain: user.org.domain,
      },
    });
  } catch (err: any) {
    res.status(401).json({ error: "Invalid or expired session" });
  }
});

/**
 * POST /auth/logout
 * Clears the session cookie.
 */
router.post("/logout", (_req: Request, res: Response) => {
  res.clearCookie("meerkat_session", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
  });

  res.json({ message: "Logged out successfully" });
});

export default router;
