import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import {
  entailment_check,
  semantic_entropy_check,
  implicit_preference_check,
  claim_extraction_check,
} from "../services/governance-checks";
import { scan, Sensitivity } from "../services/prompt-shield";
import { searchKnowledgeBase, ChunkMatch } from "../services/semantic-search";
import prisma from "../lib/prisma";
import crypto from "crypto";

const ALL_CHECKS = ["entailment", "semantic_entropy", "implicit_preference", "claim_extraction"];

const WEIGHTS: Record<string, number> = {
  entailment: 0.40,
  semantic_entropy: 0.25,
  implicit_preference: 0.20,
  claim_extraction: 0.15,
};

export function createMeerkatMcpServer(): McpServer {
  const server = new McpServer({
    name: "meerkat-governance",
    version: "1.0.0",
  });

  // --- Tool 1: meerkat_verify ---
  server.registerTool(
    "meerkat_verify",
    {
      description:
        "Verify an AI output for hallucinations, bias, unsupported claims, and prompt injection. Returns a trust score and detailed governance analysis.",
      inputSchema: {
        input: z.string().describe("What the user asked"),
        output: z.string().describe("What the AI responded"),
        context: z.string().optional().describe("Source document or reference context"),
        domain: z
          .enum(["legal", "financial", "healthcare"])
          .optional()
          .describe("Industry domain for domain-specific checks"),
      },
    },
    async ({ input, output, context, domain }, extra) => {
      const orgId = (extra as any)._orgId as string | undefined;
      const resolvedDomain = domain || "legal";
      const ctx = context || "";

      // Knowledge base retrieval if org context is available
      let kbContext = "";
      let knowledgeBaseUsed = false;
      if (orgId) {
        try {
          const config = await prisma.configuration.findFirst({ where: { orgId } });
          if (config?.knowledgeBaseEnabled) {
            const indexedKbCount = await prisma.knowledgeBase.count({
              where: { orgId, status: "indexed" },
            });
            if (indexedKbCount > 0) {
              const kbMatches = await searchKnowledgeBase(
                orgId, output,
                config.kbTopK ?? 5,
                config.kbMinRelevance ?? 0.75,
              );
              if (kbMatches.length > 0) {
                knowledgeBaseUsed = true;
                kbContext = kbMatches.map((m: ChunkMatch) => m.content).join("\n\n");
              }
            }
          }
        } catch {
          // KB lookup failed, continue without it
        }
      }

      // Run all governance checks
      const checksResults: Record<string, any> = {};

      checksResults.entailment = entailment_check(
        output, ctx, knowledgeBaseUsed ? kbContext : undefined,
      );
      checksResults.semantic_entropy = await semantic_entropy_check(input, output);
      checksResults.implicit_preference = await implicit_preference_check(
        output, resolvedDomain, ctx,
      );
      const claimsResult = await claim_extraction_check(output, ctx);
      checksResults.claim_extraction = {
        score: claimsResult.score,
        flags: claimsResult.flags,
        detail: claimsResult.detail,
      };

      // Weighted trust score
      let weightedSum = 0;
      let totalWeight = 0;
      for (const [check, result] of Object.entries(checksResults)) {
        const w = WEIGHTS[check] ?? 0.25;
        weightedSum += result.score * w;
        totalWeight += w;
      }
      const trustScore = Math.round((weightedSum / Math.max(totalWeight, 0.01)) * 100);

      // Status
      let status: "PASS" | "FLAG" | "BLOCK";
      if (trustScore >= 85) status = "PASS";
      else if (trustScore >= 40) status = "FLAG";
      else status = "BLOCK";

      const allFlags = Object.values(checksResults).flatMap((r: any) => r.flags);

      // Recommendations
      const recommendations: string[] = [];
      if (allFlags.includes("entailment_contradiction")) {
        recommendations.push("Review AI output against source documents -- contradictions detected.");
      }
      if (allFlags.includes("low_entailment")) {
        recommendations.push("AI output has weak grounding in the source context.");
      }
      if (allFlags.includes("high_uncertainty")) {
        recommendations.push("AI response shows low confidence. Consider a more specific prompt.");
      }
      if (allFlags.includes("strong_bias")) {
        recommendations.push("Response contains strong directional language. Review for bias.");
      }
      if (allFlags.includes("unverified_claims")) {
        recommendations.push("Some factual claims could not be verified against source context.");
      }

      // Generate audit ID and persist if org context is available
      const timestamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 8);
      const hash = crypto.randomBytes(4).toString("hex");
      const auditId = `aud_${timestamp}_${hash}`;

      if (orgId) {
        try {
          await prisma.verification.create({
            data: {
              orgId,
              auditId,
              domain: resolvedDomain,
              userInput: input,
              aiOutput: output,
              sourceContext: ctx || null,
              trustScore,
              status,
              checksResults: checksResults as any,
              flags: allFlags as any,
              humanReviewRequired: status === "FLAG",
            },
          });
        } catch {
          // Persist failed, continue
        }
      }

      // Format as text block for MCP
      const lines = [
        `TRUST SCORE: ${trustScore}/100 [${status}]`,
        `Audit ID: ${auditId}`,
        `Knowledge Base Used: ${knowledgeBaseUsed}`,
        "",
        "--- CHECKS ---",
      ];

      for (const [name, result] of Object.entries(checksResults)) {
        const r = result as any;
        lines.push(`${name}: score=${r.score?.toFixed?.(3) ?? r.score} flags=[${r.flags.join(", ")}]`);
        lines.push(`  ${r.detail}`);
      }

      if (allFlags.length > 0) {
        lines.push("", "--- FLAGS ---");
        allFlags.forEach((f: string) => lines.push(`- ${f}`));
      }

      if (recommendations.length > 0) {
        lines.push("", "--- RECOMMENDATIONS ---");
        recommendations.forEach((r) => lines.push(`- ${r}`));
      }

      return {
        content: [{ type: "text" as const, text: lines.join("\n") }],
      };
    },
  );

  // --- Tool 2: meerkat_shield ---
  server.registerTool(
    "meerkat_shield",
    {
      description: "Scan user input for prompt injection attacks before processing.",
      inputSchema: {
        input: z.string().describe("Raw user input to scan for prompt injection"),
        sensitivity: z
          .enum(["low", "medium", "high"])
          .optional()
          .describe("Detection sensitivity level (default: medium)"),
      },
    },
    async ({ input, sensitivity }) => {
      const sens: Sensitivity = sensitivity || "medium";
      const result = scan(input, sens);

      const lines = [
        `SAFE: ${result.safe}`,
        `Threat Level: ${result.threat_level}`,
        `Action: ${result.action}`,
      ];

      if (result.attack_type) {
        lines.push(`Attack Type: ${result.attack_type}`);
      }
      lines.push(`Detail: ${result.detail}`);

      if (result.sanitized_input) {
        lines.push("", "--- SANITIZED INPUT ---", result.sanitized_input);
      }

      return {
        content: [{ type: "text" as const, text: lines.join("\n") }],
      };
    },
  );

  // --- Tool 3: meerkat_audit ---
  server.registerTool(
    "meerkat_audit",
    {
      description: "Retrieve the governance audit trail for a previous verification.",
      inputSchema: {
        audit_id: z.string().describe("The audit ID from a previous verification (e.g. aud_20260208_abcd1234)"),
      },
    },
    async ({ audit_id }) => {
      const record = await prisma.verification.findUnique({
        where: { auditId: audit_id },
      });

      if (!record) {
        return {
          content: [{ type: "text" as const, text: `Audit record not found: ${audit_id}` }],
          isError: true,
        };
      }

      const lines = [
        `AUDIT: ${record.auditId}`,
        `Timestamp: ${record.createdAt.toISOString()}`,
        `Org: ${record.orgId}`,
        `Domain: ${record.domain}`,
        `Agent: ${record.agentName || "N/A"}`,
        `Model: ${record.modelUsed || "N/A"}`,
        "",
        `Trust Score: ${record.trustScore}/100 [${record.status}]`,
        `Human Review Required: ${record.humanReviewRequired}`,
        "",
        "--- USER INPUT ---",
        record.userInput,
        "",
        "--- AI OUTPUT ---",
        record.aiOutput,
      ];

      if (record.sourceContext) {
        lines.push("", "--- SOURCE CONTEXT ---", record.sourceContext);
      }

      const checks = record.checksResults as Record<string, any> | null;
      if (checks) {
        lines.push("", "--- CHECKS ---");
        for (const [name, result] of Object.entries(checks)) {
          lines.push(`${name}: score=${result.score?.toFixed?.(3) ?? result.score} flags=[${(result.flags || []).join(", ")}]`);
          if (result.detail) lines.push(`  ${result.detail}`);
        }
      }

      const flags = record.flags as string[] | null;
      if (flags && flags.length > 0) {
        lines.push("", "--- FLAGS ---");
        flags.forEach((f: string) => lines.push(`- ${f}`));
      }

      if (record.reviewedBy) {
        lines.push(
          "", "--- REVIEW ---",
          `Reviewed By: ${record.reviewedBy}`,
          `Action: ${record.reviewAction}`,
          `Note: ${record.reviewNote || "N/A"}`,
          `Reviewed At: ${record.reviewedAt?.toISOString() || "N/A"}`,
        );
      }

      return {
        content: [{ type: "text" as const, text: lines.join("\n") }],
      };
    },
  );

  return server;
}
