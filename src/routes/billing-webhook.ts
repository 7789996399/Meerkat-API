/**
 * Stripe webhook handler.
 *
 * Mounted separately from authenticated routes because:
 * 1. No API key auth -- uses Stripe signature verification instead
 * 2. Needs raw body (not JSON-parsed) for signature validation
 */

import { Router, Request, Response } from "express";
import {
  constructWebhookEvent,
  handleCheckoutCompleted,
  handleInvoicePaid,
  handleInvoicePaymentFailed,
  handleSubscriptionDeleted,
} from "../services/billing";
import type Stripe from "stripe";

const router = Router();

router.post("/", async (req: Request, res: Response) => {
  const signature = req.headers["stripe-signature"] as string;

  if (!signature) {
    res.status(400).json({ error: "Missing stripe-signature header" });
    return;
  }

  let event: Stripe.Event;

  try {
    // req.body is a raw Buffer when express.raw() middleware is used
    event = constructWebhookEvent(req.body as Buffer, signature);
  } catch (err: any) {
    console.error("[billing-webhook] Signature verification failed:", err.message);
    res.status(400).json({ error: `Webhook signature verification failed: ${err.message}` });
    return;
  }

  try {
    switch (event.type) {
      case "checkout.session.completed":
        await handleCheckoutCompleted(event.data.object as Stripe.Checkout.Session);
        break;

      case "invoice.paid":
        await handleInvoicePaid(event.data.object as Stripe.Invoice);
        break;

      case "invoice.payment_failed":
        await handleInvoicePaymentFailed(event.data.object as Stripe.Invoice);
        break;

      case "customer.subscription.deleted":
        await handleSubscriptionDeleted(event.data.object as Stripe.Subscription);
        break;

      default:
        console.log(`[billing-webhook] Unhandled event type: ${event.type}`);
    }

    res.json({ received: true });
  } catch (err: any) {
    console.error(`[billing-webhook] Error handling ${event.type}:`, err.message);
    res.status(500).json({ error: "Webhook handler failed" });
  }
});

export default router;
