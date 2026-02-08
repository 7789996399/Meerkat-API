import Stripe from "stripe";
import prisma from "../lib/prisma";

let _stripe: Stripe | null = null;

function getStripe(): Stripe {
  if (!_stripe) {
    const key = process.env.STRIPE_SECRET_KEY;
    if (!key) {
      throw new Error("STRIPE_SECRET_KEY environment variable is not set");
    }
    _stripe = new Stripe(key);
  }
  return _stripe;
}

const STARTER_MONTHLY_LIMIT = 1000;

// Stripe product/price IDs cached after idempotent setup
let _productId: string | null = null;
let _priceId: string | null = null;

/**
 * Idempotent setup: creates Stripe product and price if they don't exist.
 * Uses metadata to identify our product across runs.
 */
export async function ensureStripeProducts(): Promise<{
  productId: string;
  priceId: string;
}> {
  if (_productId && _priceId) {
    return { productId: _productId, priceId: _priceId };
  }

  // Search for existing product by metadata
  const products = await getStripe().products.search({
    query: "metadata['meerkat_plan']:'professional'",
  });

  let product: Stripe.Product;

  if (products.data.length > 0) {
    product = products.data[0];
  } else {
    product = await getStripe().products.create({
      name: "Meerkat Governance - Professional",
      description:
        "AI governance platform with unlimited verifications, all 4 governance checks, and full audit trail. Per AI agent pricing.",
      metadata: { meerkat_plan: "professional" },
    });
  }

  // Find existing price for this product
  const prices = await getStripe().prices.list({
    product: product.id,
    active: true,
    limit: 10,
  });

  let price: Stripe.Price;

  const existingPrice = prices.data.find(
    (p) =>
      p.unit_amount === 49900 &&
      p.currency === "usd" &&
      p.recurring?.interval === "month"
  );

  if (existingPrice) {
    price = existingPrice;
  } else {
    price = await getStripe().prices.create({
      product: product.id,
      unit_amount: 49900, // $499.00
      currency: "usd",
      recurring: { interval: "month" },
      metadata: { meerkat_plan: "professional" },
    });
  }

  _productId = product.id;
  _priceId = price.id;

  return { productId: product.id, priceId: price.id };
}

/**
 * Get or create a Stripe customer for an organization.
 */
export async function getOrCreateCustomer(
  orgId: string,
  orgName: string
): Promise<string> {
  const org = await prisma.organization.findUnique({ where: { id: orgId } });

  if (org?.stripeCustomerId) {
    return org.stripeCustomerId;
  }

  const customer = await getStripe().customers.create({
    name: orgName,
    metadata: { meerkat_org_id: orgId },
  });

  await prisma.organization.update({
    where: { id: orgId },
    data: { stripeCustomerId: customer.id },
  });

  return customer.id;
}

/**
 * Create a Stripe Checkout session for Professional plan.
 */
export async function createCheckoutSession(
  orgId: string,
  orgName: string,
  agents: number,
  successUrl: string,
  cancelUrl: string
): Promise<string> {
  const { priceId } = await ensureStripeProducts();
  const customerId = await getOrCreateCustomer(orgId, orgName);

  const session = await getStripe().checkout.sessions.create({
    customer: customerId,
    mode: "subscription",
    line_items: [
      {
        price: priceId,
        quantity: Math.max(1, agents),
      },
    ],
    success_url: successUrl,
    cancel_url: cancelUrl,
    metadata: {
      meerkat_org_id: orgId,
      agents: String(agents),
    },
  });

  return session.url!;
}

/**
 * Create a Stripe Customer Portal session.
 */
export async function createPortalSession(
  orgId: string,
  returnUrl: string
): Promise<string> {
  const org = await prisma.organization.findUnique({ where: { id: orgId } });

  if (!org?.stripeCustomerId) {
    throw new Error("No Stripe customer found for this organization. Subscribe to a plan first.");
  }

  const session = await getStripe().billingPortal.sessions.create({
    customer: org.stripeCustomerId,
    return_url: returnUrl,
  });

  return session.url;
}

/**
 * Get usage data for an organization.
 */
export async function getUsage(orgId: string) {
  const org = await prisma.organization.findUnique({ where: { id: orgId } });
  if (!org) throw new Error("Organization not found");

  const isStarter = org.plan === "starter";
  const isProfessional = org.plan === "professional";

  // Count distinct agent names used in current period
  const periodStart = org.planStartedAt || org.createdAt;
  const agentsResult = await prisma.verification.findMany({
    where: {
      orgId,
      createdAt: { gte: periodStart },
      agentName: { not: null },
    },
    distinct: ["agentName"],
    select: { agentName: true },
  });
  const agentsConnected = agentsResult.length;

  // Get subscription details from Stripe if professional
  let nextInvoice: { amount: number; date: string } | null = null;
  let billingPeriod: { start: string; end: string } | null = null;

  if (isProfessional && org.stripeSubscriptionId) {
    try {
      const sub = await getStripe().subscriptions.retrieve(org.stripeSubscriptionId);

      // Compute current billing period from billing_cycle_anchor
      const anchor = new Date(sub.billing_cycle_anchor * 1000);
      const now = new Date();
      // Find the most recent billing period start
      const periodStart = new Date(anchor);
      while (periodStart < now) {
        const next = new Date(periodStart);
        next.setMonth(next.getMonth() + 1);
        if (next > now) break;
        periodStart.setMonth(periodStart.getMonth() + 1);
      }
      const periodEnd = new Date(periodStart);
      periodEnd.setMonth(periodEnd.getMonth() + 1);

      billingPeriod = {
        start: periodStart.toISOString(),
        end: periodEnd.toISOString(),
      };

      const preview = await getStripe().invoices.createPreview({
        customer: org.stripeCustomerId!,
      });
      nextInvoice = {
        amount: (preview.amount_due || 0) / 100,
        date: billingPeriod.end,
      };
    } catch {
      // Stripe call failed, return what we have
    }
  }

  if (!billingPeriod) {
    // Compute billing period from plan start or creation
    const start = org.planStartedAt || org.createdAt;
    const end = new Date(start);
    end.setMonth(end.getMonth() + 1);
    billingPeriod = {
      start: start.toISOString(),
      end: end.toISOString(),
    };
  }

  return {
    plan: org.plan,
    billing_period: billingPeriod,
    verifications_used: org.currentPeriodVerifications,
    verifications_limit: isStarter ? STARTER_MONTHLY_LIMIT : "unlimited",
    agents_connected: agentsConnected,
    next_invoice: nextInvoice,
  };
}

/**
 * Check if an organization has reached its verification limit.
 * Returns null if OK, or an error object if limit reached.
 */
export function checkVerificationLimit(
  plan: string,
  currentCount: number
): { error: string; upgrade_url: string } | null {
  if (plan !== "starter") return null;
  if (currentCount >= STARTER_MONTHLY_LIMIT) {
    return {
      error:
        "Verification limit reached. Upgrade to Professional for unlimited.",
      upgrade_url: "/billing/upgrade",
    };
  }
  return null;
}

/**
 * Increment the verification counter for an organization.
 */
export async function incrementVerificationCount(orgId: string): Promise<void> {
  await prisma.organization.update({
    where: { id: orgId },
    data: { currentPeriodVerifications: { increment: 1 } },
  });
}

// --- Webhook handlers ---

export async function handleCheckoutCompleted(
  session: Stripe.Checkout.Session
): Promise<void> {
  const orgId = session.metadata?.meerkat_org_id;
  if (!orgId) return;

  const subscriptionId =
    typeof session.subscription === "string"
      ? session.subscription
      : session.subscription?.id;

  await prisma.organization.update({
    where: { id: orgId },
    data: {
      plan: "professional",
      stripeSubscriptionId: subscriptionId || null,
      planStartedAt: new Date(),
      currentPeriodVerifications: 0,
    },
  });

  console.log(`[billing] Org ${orgId} upgraded to professional`);
}

export async function handleInvoicePaid(
  invoice: Stripe.Invoice
): Promise<void> {
  const customerId =
    typeof invoice.customer === "string"
      ? invoice.customer
      : invoice.customer?.id;
  if (!customerId) return;

  const org = await prisma.organization.findFirst({
    where: { stripeCustomerId: customerId },
  });
  if (!org) return;

  // Reset monthly verification counter on successful payment
  await prisma.organization.update({
    where: { id: org.id },
    data: {
      currentPeriodVerifications: 0,
      planStartedAt: new Date(),
    },
  });

  console.log(`[billing] Invoice paid for org ${org.id}, counters reset`);
}

export async function handleInvoicePaymentFailed(
  invoice: Stripe.Invoice
): Promise<void> {
  const customerId =
    typeof invoice.customer === "string"
      ? invoice.customer
      : invoice.customer?.id;
  if (!customerId) return;

  const org = await prisma.organization.findFirst({
    where: { stripeCustomerId: customerId },
  });
  if (!org) return;

  // Log the failure. In production, send email notification and set grace period.
  console.error(
    `[billing] Payment failed for org ${org.id}. Invoice: ${invoice.id}. ` +
      `Grace period: 7 days from now.`
  );
}

export async function handleSubscriptionDeleted(
  subscription: Stripe.Subscription
): Promise<void> {
  const customerId =
    typeof subscription.customer === "string"
      ? subscription.customer
      : subscription.customer?.id;
  if (!customerId) return;

  const org = await prisma.organization.findFirst({
    where: { stripeCustomerId: customerId },
  });
  if (!org) return;

  // Downgrade to starter
  await prisma.organization.update({
    where: { id: org.id },
    data: {
      plan: "starter",
      stripeSubscriptionId: null,
      currentPeriodVerifications: 0,
    },
  });

  console.log(`[billing] Org ${org.id} downgraded to starter`);
}

/**
 * Construct and verify a Stripe webhook event.
 */
export function constructWebhookEvent(
  payload: Buffer,
  signature: string
): Stripe.Event {
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET || "";
  return getStripe().webhooks.constructEvent(payload, signature, webhookSecret);
}
