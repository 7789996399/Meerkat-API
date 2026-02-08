import { Router } from "express";
import { AuthenticatedRequest } from "../middleware/auth";
import {
  createCheckoutSession,
  createPortalSession,
  getUsage,
} from "../services/billing";

const router = Router();

/**
 * POST /v1/billing/checkout
 * Creates a Stripe Checkout session for Professional plan.
 */
router.post("/checkout", async (req: AuthenticatedRequest, res) => {
  const { plan, agents } = req.body;

  if (plan !== "professional") {
    res.status(400).json({
      error: "Only 'professional' plan supports self-serve checkout. Contact sales for enterprise.",
    });
    return;
  }

  const agentCount = typeof agents === "number" && agents > 0 ? agents : 1;

  const orgId = req.context!.orgId;
  const orgName = req.context!.orgName;

  // Build success/cancel URLs
  const baseUrl = `${req.protocol}://${req.get("host")}`;
  const successUrl = `${baseUrl}/v1/billing/usage?checkout=success`;
  const cancelUrl = `${baseUrl}/v1/billing/usage?checkout=cancelled`;

  try {
    const checkoutUrl = await createCheckoutSession(
      orgId, orgName, agentCount, successUrl, cancelUrl
    );
    res.json({ checkout_url: checkoutUrl });
  } catch (err: any) {
    console.error("[billing] Checkout error:", err.message);
    res.status(500).json({ error: "Failed to create checkout session" });
  }
});

/**
 * POST /v1/billing/portal
 * Creates a Stripe Customer Portal session.
 */
router.post("/portal", async (req: AuthenticatedRequest, res) => {
  const orgId = req.context!.orgId;
  const baseUrl = `${req.protocol}://${req.get("host")}`;
  const returnUrl = `${baseUrl}/v1/billing/usage`;

  try {
    const portalUrl = await createPortalSession(orgId, returnUrl);
    res.json({ portal_url: portalUrl });
  } catch (err: any) {
    console.error("[billing] Portal error:", err.message);
    res.status(400).json({ error: err.message });
  }
});

/**
 * GET /v1/billing/usage
 * Returns current billing period usage.
 */
router.get("/usage", async (req: AuthenticatedRequest, res) => {
  const orgId = req.context!.orgId;

  try {
    const usage = await getUsage(orgId);
    res.json(usage);
  } catch (err: any) {
    console.error("[billing] Usage error:", err.message);
    res.status(500).json({ error: "Failed to retrieve usage data" });
  }
});

export default router;
