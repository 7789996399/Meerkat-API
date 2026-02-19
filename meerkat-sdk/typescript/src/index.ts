/**
 * Meerkat AI — TypeScript/Node.js SDK
 *
 * Lightweight client for the Meerkat Governance API. Zero dependencies
 * beyond native fetch (Node 18+).
 *
 *     npm install @meerkat-ai/sdk
 *
 * Usage:
 *
 *     import { Meerkat } from "@meerkat-ai/sdk";
 *
 *     const mk = new Meerkat("mk_live_...", { domain: "healthcare" });
 *
 *     // Shield user input
 *     const shield = await mk.shield("Summarize the patient note");
 *     if (!shield.safe) {
 *       console.log("Blocked:", shield.threats);
 *     }
 *
 *     // Verify LLM output
 *     const result = await mk.verify({
 *       output: llmResponse,
 *       context: patientRecord,
 *       input: "Summarize the patient note",
 *     });
 *     console.log(`Trust: ${result.trust_score}  Status: ${result.status}`);
 *
 *     // Retrieve audit trail
 *     const audit = await mk.audit(result.audit_id);
 */

// ── Types ────────────────────────────────────────────────────────────────

export interface ShieldResult {
  safe: boolean;
  threat_level: string;
  audit_id: string;
  session_id: string;
  threats?: Array<{
    type: string;
    description: string;
    severity: string;
    patterns_matched?: string[];
  }>;
  sanitized_input?: string;
  remediation?: Record<string, unknown>;
}

export interface VerifyResult {
  trust_score: number;
  status: "PASS" | "FLAG" | "BLOCK";
  checks: Record<string, { score: number; flags: string[]; detail: string }>;
  audit_id: string;
  session_id: string;
  attempt: number;
  verification_mode: string;
  recommendations: string[];
  remediation?: {
    message: string;
    agent_instruction: string;
    corrections: Array<{
      type: string;
      check: string;
      found: string;
      expected?: string;
      severity: string;
      source_reference?: string;
      subtype?: "error" | "discrepancy";
      requires_clinical_review?: boolean;
      rationale?: string;
    }>;
    retry_allowed: boolean;
    max_retries: number;
    suggested_action: string;
  };
}

export interface AuditResult {
  audit_id: string;
  trust_score: number;
  status: string;
  domain: string;
  timestamp: string;
  checks: Record<string, unknown>;
  remediation?: Record<string, unknown>;
  session?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ShieldOptions {
  sensitivity?: "low" | "medium" | "high";
  session_id?: string;
}

export interface VerifyOptions {
  output: string;
  context: string;
  input?: string;
  domain?: string;
  session_id?: string;
  checks?: string[];
  config_id?: string;
  agent_name?: string;
  model?: string;
}

export interface MeerkatOptions {
  domain?: string;
  baseUrl?: string;
  timeout?: number;
}

// ── Errors ───────────────────────────────────────────────────────────────

export class MeerkatError extends Error {
  statusCode?: number;
  body?: unknown;

  constructor(message: string, statusCode?: number, body?: unknown) {
    super(message);
    this.name = "MeerkatError";
    this.statusCode = statusCode;
    this.body = body;
  }
}

export class MeerkatBlockError extends MeerkatError {
  result: VerifyResult;

  constructor(result: VerifyResult) {
    super(`Verification BLOCK (trust_score=${result.trust_score})`);
    this.name = "MeerkatBlockError";
    this.result = result;
  }
}

// ── Client ───────────────────────────────────────────────────────────────

const DEFAULT_BASE_URL = "https://api.meerkatplatform.com";
const DEFAULT_TIMEOUT = 120_000;

export class Meerkat {
  private apiKey: string;
  private domain: string;
  private baseUrl: string;
  private timeout: number;

  /**
   * Create a new Meerkat client.
   *
   * @param apiKey - Your Meerkat API key (mk_live_...).
   * @param options - Configuration options.
   */
  constructor(apiKey: string, options: MeerkatOptions = {}) {
    this.apiKey = apiKey;
    this.domain = options.domain ?? "general";
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.timeout = options.timeout ?? DEFAULT_TIMEOUT;
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    try {
      const resp = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${this.apiKey}`,
          "Content-Type": "application/json",
        },
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });

      if (!resp.ok) {
        let errorBody: unknown;
        try {
          errorBody = await resp.json();
        } catch {
          errorBody = await resp.text();
        }
        throw new MeerkatError(
          `API error ${resp.status}: ${JSON.stringify(errorBody)}`,
          resp.status,
          errorBody,
        );
      }

      return (await resp.json()) as T;
    } finally {
      clearTimeout(timer);
    }
  }

  // ── Shield ──────────────────────────────────────────────────────────

  /**
   * Scan input for prompt injection, data exfiltration, and other attacks.
   *
   * @param input - The text to scan.
   * @param options - Shield options (sensitivity, session_id).
   */
  async shield(input: string, options: ShieldOptions = {}): Promise<ShieldResult> {
    const payload: Record<string, unknown> = {
      input,
      domain: this.domain,
      sensitivity: options.sensitivity ?? "medium",
    };
    if (options.session_id) payload.session_id = options.session_id;

    return this.request<ShieldResult>("POST", "/v1/shield", payload);
  }

  // ── Verify ──────────────────────────────────────────────────────────

  /**
   * Verify AI output against source context.
   *
   * @param options - Verify options (output, context, input, etc.).
   */
  async verify(options: VerifyOptions): Promise<VerifyResult> {
    const payload: Record<string, unknown> = {
      input: options.input ?? "Verify this output",
      output: options.output,
      context: options.context,
      domain: options.domain ?? this.domain,
    };
    if (options.session_id) payload.session_id = options.session_id;
    if (options.checks) payload.checks = options.checks;
    if (options.config_id) payload.config_id = options.config_id;
    if (options.agent_name) payload.agent_name = options.agent_name;
    if (options.model) payload.model = options.model;

    return this.request<VerifyResult>("POST", "/v1/verify", payload);
  }

  // ── Audit ───────────────────────────────────────────────────────────

  /**
   * Retrieve the full audit record for a verification.
   *
   * @param auditId - The audit ID from shield() or verify().
   * @param includeSession - Include full session history.
   */
  async audit(auditId: string, includeSession = false): Promise<AuditResult> {
    const path = `/v1/audit/${auditId}${includeSession ? "?include=session" : ""}`;
    return this.request<AuditResult>("GET", path);
  }
}

export default Meerkat;
