/**
 * Standalone MCP server entry point (stdio transport).
 *
 * Usage: npx tsx src/mcp/index.ts
 *
 * This runs the Meerkat governance MCP server over stdin/stdout,
 * suitable for local development and desktop MCP clients.
 */

import dotenv from "dotenv";
dotenv.config();

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { createMeerkatMcpServer } from "./server";

async function main() {
  const mcpServer = createMeerkatMcpServer();
  const transport = new StdioServerTransport();

  await mcpServer.connect(transport);

  // Use stderr for logging since stdout is used by MCP JSON-RPC
  console.error("[meerkat-mcp] Server running on stdio transport");
}

main().catch((err) => {
  console.error("[meerkat-mcp] Fatal error:", err);
  process.exit(1);
});
