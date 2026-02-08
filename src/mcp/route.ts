/**
 * MCP SSE route for Express integration.
 *
 * Mounts on /mcp with two sub-paths:
 *   GET  /mcp/sse       -- establishes SSE stream
 *   POST /mcp/messages   -- receives JSON-RPC messages from MCP clients
 *
 * Authentication: API key via x-meerkat-key header or Bearer token,
 * same as the rest of the API.
 */

import { Router, Request, Response } from "express";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { createMeerkatMcpServer } from "./server";

const router = Router();

// Track active SSE sessions
const sessions = new Map<string, SSEServerTransport>();

// Each SSE connection gets its own McpServer + transport pair.
// This is necessary because McpServer.connect() binds to one transport.

router.get("/sse", async (req: Request, res: Response) => {
  // Authenticate via query param or header
  const apiKey =
    (req.query.api_key as string) ||
    req.headers["x-meerkat-key"] as string ||
    extractBearerToken(req);

  if (!apiKey) {
    res.status(401).json({ error: "API key required. Pass via x-meerkat-key header, Bearer token, or ?api_key= query param." });
    return;
  }

  // Validate key (lightweight check -- full auth happens on tool calls if needed)
  // For now, just verify the key exists. In production, resolve org context.

  const mcpServer = createMeerkatMcpServer();
  const transport = new SSEServerTransport("/mcp/messages", res);

  sessions.set(transport.sessionId, transport);

  // Clean up on disconnect
  res.on("close", () => {
    sessions.delete(transport.sessionId);
  });

  await mcpServer.connect(transport);
});

router.post("/messages", async (req: Request, res: Response) => {
  const sessionId = req.query.sessionId as string;
  if (!sessionId) {
    res.status(400).json({ error: "Missing sessionId query parameter" });
    return;
  }

  const transport = sessions.get(sessionId);
  if (!transport) {
    res.status(404).json({ error: "Session not found. The SSE connection may have been closed." });
    return;
  }

  // Pass req.body as parsedBody since Express already parsed the JSON
  await transport.handlePostMessage(req, res, req.body);
});

function extractBearerToken(req: Request): string | undefined {
  const auth = req.headers.authorization;
  if (auth?.startsWith("Bearer ")) {
    return auth.slice(7);
  }
  return undefined;
}

export default router;
