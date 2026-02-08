import express from "express";
import cookieParser from "cookie-parser";
import dotenv from "dotenv";
import { authenticate } from "./middleware/auth";
import { rateLimiter } from "./middleware/rateLimit";
import routes from "./routes";
import mcpRouter from "./mcp/route";
import billingWebhookRouter from "./routes/billing-webhook";
import authRouter from "./routes/auth";

dotenv.config();

const app = express();
const port = process.env.PORT || 3000;

// Stripe webhook needs raw body for signature verification -- mount BEFORE express.json()
app.use("/v1/billing/webhook", express.raw({ type: "application/json" }), billingWebhookRouter);

app.use(express.json());
app.use(cookieParser());

// Health check (unauthenticated, no rate limit)
app.get("/v1/health", (_req, res) => {
  res.json({ status: "healthy", version: "1.0.0" });
});

// Auth routes (unauthenticated -- handles its own auth via MSAL)
app.use("/auth", authRouter);

// MCP server (SSE transport) -- handles its own auth
app.use("/mcp", mcpRouter);

// All /v1 routes: authenticate first, then rate-limit per plan, then route
app.use("/v1", authenticate, rateLimiter, routes);

app.listen(port, () => {
  console.log(`Meerkat API running on port ${port}`);
});

export default app;
