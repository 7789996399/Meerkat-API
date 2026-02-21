import express from "express";
import cors from "cors";
import cookieParser from "cookie-parser";
import path from "path";
import dotenv from "dotenv";
import { authenticate } from "./middleware/auth";
import { rateLimiter } from "./middleware/rateLimit";
import routes from "./routes";
import mcpRouter from "./mcp/route";
import billingWebhookRouter from "./routes/billing-webhook";
import authRouter from "./routes/auth";
import registerRouter from "./routes/register";

dotenv.config();

const app = express();
const port = process.env.PORT || 3000;

// Stripe webhook needs raw body for signature verification -- mount BEFORE express.json()
app.use("/v1/billing/webhook", express.raw({ type: "application/json" }), billingWebhookRouter);

const corsOptions = {
  origin: ['https://meerkatplatform.com', 'https://www.meerkatplatform.com', 'http://localhost:3000'],
  credentials: true,
};
app.use(cors(corsOptions));
app.options('*', cors(corsOptions));
app.use(express.json());
app.use(cookieParser());

// Landing page
app.get("/", (_req, res) => {
  res.sendFile(path.resolve(__dirname, "../meerkat-dev-landing.html"));
});

// Docs page
app.get("/docs", (_req, res) => {
  res.sendFile(path.resolve(__dirname, "../meerkat-docs.html"));
});

// Privacy page
app.get("/privacy", (_req, res) => {
  res.sendFile(path.resolve(__dirname, "../meerkat-privacy.html"));
});

// Health check (unauthenticated, no rate limit)
app.get("/v1/health", (_req, res) => {
  res.json({ status: "healthy", version: "1.0.0" });
});

// Auth routes (unauthenticated -- handles its own auth via MSAL)
app.use("/auth", authRouter);

// MCP server (SSE transport) -- handles its own auth
app.use("/mcp", mcpRouter);

// Self-service registration (unauthenticated -- this IS the key creation endpoint)
app.use("/v1/register", registerRouter);

// All /v1 routes: authenticate first, then rate-limit per plan, then route
app.use("/v1", authenticate, rateLimiter, routes);

app.listen(port, () => {
  console.log(`Meerkat API running on port ${port}`);
});

export default app;
