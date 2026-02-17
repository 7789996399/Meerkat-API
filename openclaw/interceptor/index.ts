/**
 * Meerkat Interceptor for OpenClaw
 *
 * Wraps OpenClaw's tool execution pipeline with dual-gate governance:
 * - Ingress: Shield incoming content before LLM processes it
 * - Egress: Verify outgoing actions before they execute
 *
 * Usage:
 *   import { MeerkatInterceptor } from './interceptor';
 *   const meerkat = new MeerkatInterceptor({ apiKey: process.env.MEERKAT_API_KEY });
 *
 *   // Shield incoming content
 *   const shieldResult = await meerkat.shield(emailContent);
 *   if (!shieldResult.safe) { ... }
 *
 *   // Verify before executing
 *   const verifyResult = await meerkat.verify({
 *     input: "User asked: send email to boss",
 *     output: "Composing email with subject: Q1 Results...",
 *     context: "Original user instruction and source data",
 *   });
 *   if (verifyResult.status === "BLOCK") { ... }
 */

export interface MeerkatConfig {
  apiKey: string;
  baseUrl?: string;
  timeoutMs?: number;
  retryCount?: number;
  /** Minimum trust score to auto-approve actions (default: 70) */
  autoApproveThreshold?: number;
  /** Trust score below which actions are blocked (default: 40) */
  blockThreshold?: number;
  /** Domain hint for verification (healthcare, legal, financial, general) */
  domain?: string;
}

export interface ShieldResult {
  safe: boolean;
  threat_level: "NONE" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  attack_type: string | null;
  detail: string;
  action: "ALLOW" | "FLAG" | "BLOCK";
  audit_id?: string;
}

export interface VerifyResult {
  trust_score: number;
  status: "PASS" | "FLAG" | "BLOCK";
  checks: Record<string, { score: number; flags: string[]; detail: string }>;
  flags: string[];
  recommendations: string[];
  audit_id: string;
}

// Actions that require egress verification by default
const HIGH_IMPACT_ACTIONS = new Set([
  // Communication
  "send_email", "send_message", "reply_email", "forward_email",
  "post_slack", "post_discord", "send_sms", "send_whatsapp",
  // Execution
  "execute_command", "run_shell", "run_script", "exec",
  // File system
  "write_file", "delete_file", "modify_file", "move_file",
  // Public
  "post_tweet", "post_social", "publish_blog", "create_issue",
  "comment_pr", "submit_form",
  // Financial
  "make_purchase", "send_payment", "transfer_funds",
  // Access
  "share_file", "grant_access", "modify_permissions",
  // Calendar / Tasks
  "create_event", "modify_event", "delete_event",
  "create_task", "complete_task",
  // Code
  "run_code", "install_package", "deploy",
]);

// Content sources that require ingress shielding by default
const UNTRUSTED_SOURCES = new Set([
  "email", "email_attachment", "web_page", "web_search",
  "document", "forwarded_message", "skill_install",
  "calendar_invite", "shared_file", "webhook",
  "unknown_sender", "public_channel",
]);

export class MeerkatInterceptor {
  private apiKey: string;
  private baseUrl: string;
  private timeoutMs: number;
  private retryCount: number;
  private autoApproveThreshold: number;
  private blockThreshold: number;
  private domain: string;

  constructor(config: MeerkatConfig) {
    this.apiKey = config.apiKey;
    this.baseUrl = config.baseUrl || "https://api.meerkat.ai";
    this.timeoutMs = config.timeoutMs || 5000;
    this.retryCount = config.retryCount || 2;
    this.autoApproveThreshold = config.autoApproveThreshold || 70;
    this.blockThreshold = config.blockThreshold || 40;
    this.domain = config.domain || "general";
  }

  // ── Ingress Shield ─────────────────────────────────────────────

  /**
   * Shield incoming content before the LLM processes it.
   * Call this on emails, web pages, documents, forwarded messages, etc.
   */
  async shield(
    content: string,
    options?: {
      source?: string;
      sensitivity?: "low" | "medium" | "high";
    },
  ): Promise<ShieldResult> {
    const sensitivity = options?.sensitivity || "high";

    try {
      const result = await this._post("/v1/shield", {
        input: content,
        sensitivity,
        domain: this.domain,
        metadata: {
          source: options?.source || "unknown",
          platform: "openclaw",
        },
      });

      return result as ShieldResult;
    } catch (err: any) {
      // On failure, return a conservative result
      console.error("[meerkat] Shield check failed:", err.message);
      return {
        safe: false,
        threat_level: "MEDIUM",
        attack_type: null,
        detail: `Meerkat shield unavailable: ${err.message}. Treat content as untrusted.`,
        action: "FLAG",
      };
    }
  }

  /**
   * Check if content from a given source should be shielded.
   */
  shouldShield(source: string): boolean {
    return UNTRUSTED_SOURCES.has(source.toLowerCase());
  }

  // ── Egress Verify ──────────────────────────────────────────────

  /**
   * Verify an action before execution.
   * Call this before sending emails, running commands, posting, etc.
   */
  async verify(params: {
    /** What the user originally asked for */
    input: string;
    /** What the agent is about to do (the action/output) */
    output: string;
    /** Source data the action is based on (if any) */
    context?: string;
    /** Specific domain for this check */
    domain?: string;
    /** Which checks to run (defaults to all) */
    checks?: string[];
  }): Promise<VerifyResult> {
    try {
      const result = await this._post("/v1/verify", {
        input: params.input,
        output: params.output,
        context: params.context || "",
        domain: params.domain || this.domain,
        checks: params.checks || [
          "entailment",
          "numerical_verify",
          "semantic_entropy",
          "implicit_preference",
          "claim_extraction",
        ],
      });

      return result as VerifyResult;
    } catch (err: any) {
      console.error("[meerkat] Verify check failed:", err.message);
      // On failure, return a FLAG result requiring user confirmation
      return {
        trust_score: 0,
        status: "FLAG",
        checks: {},
        flags: ["meerkat_unavailable"],
        recommendations: [
          `Meerkat verification unavailable: ${err.message}. ` +
          `Please confirm this action manually.`,
        ],
        audit_id: "unavailable",
      };
    }
  }

  /**
   * Check if a tool/action name requires egress verification.
   */
  requiresVerification(actionName: string): boolean {
    // Normalize: "exec.run_shell" -> "run_shell"
    const normalized = actionName.split(".").pop()?.toLowerCase() || "";
    return HIGH_IMPACT_ACTIONS.has(normalized);
  }

  /**
   * Determine the action based on trust score.
   */
  evaluateResult(result: VerifyResult): "execute" | "confirm" | "block" {
    if (result.trust_score < this.blockThreshold || result.status === "BLOCK") {
      return "block";
    }
    if (result.trust_score < this.autoApproveThreshold || result.status === "FLAG") {
      return "confirm";
    }
    return "execute";
  }

  // ── Audit ──────────────────────────────────────────────────────

  /**
   * Retrieve an audit record.
   */
  async getAudit(auditId: string): Promise<Record<string, unknown>> {
    return this._get(`/v1/audit/${auditId}`);
  }

  // ── Convenience: Full Intercept ────────────────────────────────

  /**
   * Full intercept flow for a tool call.
   * Returns { allowed, result, message } for the agent to act on.
   */
  async interceptToolCall(params: {
    toolName: string;
    userIntent: string;
    actionDescription: string;
    sourceContext?: string;
  }): Promise<{
    allowed: boolean;
    needsConfirmation: boolean;
    message: string;
    auditId?: string;
    trustScore?: number;
  }> {
    // Check if this action needs verification
    if (!this.requiresVerification(params.toolName)) {
      return { allowed: true, needsConfirmation: false, message: "Low-impact action, no verification needed." };
    }

    // Run verification
    const result = await this.verify({
      input: params.userIntent,
      output: params.actionDescription,
      context: params.sourceContext,
    });

    const decision = this.evaluateResult(result);

    if (decision === "block") {
      return {
        allowed: false,
        needsConfirmation: false,
        message: `Meerkat BLOCKED this action (trust score: ${result.trust_score}). ` +
          `Reasons: ${result.recommendations.join(" ")}`,
        auditId: result.audit_id,
        trustScore: result.trust_score,
      };
    }

    if (decision === "confirm") {
      return {
        allowed: false,
        needsConfirmation: true,
        message: `Meerkat flagged this action for review (trust score: ${result.trust_score}). ` +
          `Flags: ${result.flags.join(", ")}. ${result.recommendations.join(" ")}`,
        auditId: result.audit_id,
        trustScore: result.trust_score,
      };
    }

    return {
      allowed: true,
      needsConfirmation: false,
      message: `Verified (trust score: ${result.trust_score}).`,
      auditId: result.audit_id,
      trustScore: result.trust_score,
    };
  }

  // ── Internal ───────────────────────────────────────────────────

  private async _post(path: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= this.retryCount; attempt++) {
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), this.timeoutMs);

        const resp = await fetch(`${this.baseUrl}${path}`, {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${this.apiKey}`,
            "Content-Type": "application/json",
            "X-Meerkat-Platform": "openclaw",
          },
          body: JSON.stringify(body),
          signal: controller.signal,
        });

        clearTimeout(timeout);

        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
        }

        return (await resp.json()) as Record<string, unknown>;
      } catch (err: any) {
        lastError = err;
        if (attempt < this.retryCount) {
          // Exponential backoff: 200ms, 400ms
          await new Promise(r => setTimeout(r, 200 * (attempt + 1)));
        }
      }
    }

    throw lastError || new Error("Meerkat API request failed");
  }

  private async _get(path: string): Promise<Record<string, unknown>> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);

    const resp = await fetch(`${this.baseUrl}${path}`, {
      headers: {
        "Authorization": `Bearer ${this.apiKey}`,
        "X-Meerkat-Platform": "openclaw",
      },
      signal: controller.signal,
    });

    clearTimeout(timeout);

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
    }

    return (await resp.json()) as Record<string, unknown>;
  }
}
