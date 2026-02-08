import { useState } from "react";

const CYAN = "#22d3ee";
const DARK = "#0a0f1a";
const CARD = "#111827";
const BORDER = "#1e293b";
const AMBER = "#f59e0b";
const GREEN = "#10b981";
const RED = "#ef4444";
const PURPLE = "#a78bfa";
const PINK = "#f472b6";
const TEXT = "#f1f5f9";
const MUTED = "#94a3b8";
const DIM = "#64748b";

// ─── The Big Idea (Grandmother explanation) ───
const BIG_IDEA = {
  title: "The Big Idea",
  icon: "💡",
  content: [
    {
      heading: "Think of it like airport security",
      text: `Right now, Anthropic's legal plugin is like a really smart lawyer who works in an open office — anyone can walk up, hand them a document, and get advice back. No security checkpoint, no ID check, no record of what was reviewed.

Meerkat API is the airport security system. Every document and every AI response passes through our checkpoint. We scan for problems (hallucinations, bias, prompt attacks), stamp a "governance passport" on everything, and keep a complete audit trail.

The beautiful part? The lawyer doesn't even notice we're there. They keep doing their job. We just make sure everything is safe and trustworthy.`
    },
    {
      heading: "What 'automated integration' means",
      text: `Instead of each hospital, law firm, or bank having to build their own governance system from scratch, they just add ONE line of configuration to point their AI plugin through the Meerkat API. 

It's like how every website uses HTTPS for security — you don't build your own encryption. You plug into an existing system. Meerkat API is "governance-as-a-service" for AI agents.`
    }
  ]
};

// ─── Architecture Flow ───
const FLOW_STEPS = [
  { id: 1, label: "User Request", desc: "Lawyer asks: 'Review this NDA'", icon: "👤", color: MUTED, detail: "A user in Anthropic's Cowork legal plugin types /review-contract and uploads a document. This request would normally go straight to Claude." },
  { id: 2, label: "Meerkat Ingress", desc: "Request intercepted & scanned", icon: "🛡️", color: RED, detail: "The Meerkat API intercepts the request BEFORE it reaches Claude. It checks for prompt injection attacks, validates the user's permissions, rate-limits requests, and logs everything. Think of it as the bouncer at the door." },
  { id: 3, label: "AI Processing", desc: "Claude / GPT / Gemini does its work", icon: "🤖", color: PURPLE, detail: "The sanitized request is forwarded to the AI model (Claude, GPT, Gemini — Meerkat is model-agnostic). The model does its thing: reviews the contract, flags clauses, generates recommendations." },
  { id: 4, label: "Meerkat Egress", desc: "Response verified & scored", icon: "🔍", color: AMBER, detail: "This is where the magic happens. Before the AI's response reaches the user, Meerkat runs it through: (1) DeBERTa Entailment — does the AI's conclusion match the actual document text? (2) Semantic Entropy — how confident/uncertain is the model? (3) Implicit Preference — is the AI showing hidden bias? (4) Claim Extraction — are specific factual claims verifiable?" },
  { id: 5, label: "Governance Score", desc: "Trust score + audit trail created", icon: "✅", color: GREEN, detail: "Every response gets a Meerkat Trust Score (0-100). High scores pass through. Low scores get flagged with specific warnings like 'Clause 7.2 analysis may be unreliable — semantic entropy exceeded threshold.' Everything is logged for compliance audits." },
  { id: 6, label: "User Response", desc: "Verified answer delivered", icon: "📋", color: CYAN, detail: "The user receives the AI's contract review PLUS a trust overlay showing which parts are reliable, which need human review, and an overall governance score. The lawyer sees a clean, enhanced interface — not a wall of technical jargon." },
];

// ─── API Endpoints ───
const API_ENDPOINTS = [
  {
    method: "POST",
    path: "/v1/verify",
    name: "Real-time Verification",
    desc: "The core endpoint. Send any AI input/output pair and get back a trust score with detailed analysis. This is the one-liner that any plugin calls.",
    example: `// This is ALL a plugin needs to integrate
const response = await fetch(
  "https://api.meerkat.ai/v1/verify",
  {
    method: "POST",
    headers: {
      "Authorization": "Bearer mk_live_abc123",
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      // What the user asked
      input: "Review this NDA for risks",
      // What the AI responded
      output: "Clause 3.2 contains a non-compete...",
      // The source document (for entailment checking)
      context: "[full NDA text here]",
      // Which governance checks to run
      checks: ["entailment", "semantic_entropy", 
               "implicit_preference", "claim_extraction"],
      // Domain-specific config
      domain: "legal",
      // Your org's risk tolerance
      config_id: "cfg_lawfirm_standard"
    })
  }
);

// Response:
{
  "trust_score": 87,
  "status": "PASS",
  "checks": {
    "entailment": {
      "score": 0.92,
      "flags": [],
      "detail": "All claims grounded in source"
    },
    "semantic_entropy": {
      "score": 0.15,
      "flags": ["moderate_uncertainty"],
      "detail": "Clause 3.2 analysis shows some uncertainty"
    },
    "implicit_preference": {
      "score": 0.88,
      "flags": [],
      "detail": "No significant bias detected"
    },
    "claim_extraction": {
      "claims": 7,
      "verified": 6,
      "unverified": 1,
      "flags": ["claim_4_needs_review"]
    }
  },
  "audit_id": "aud_20260207_nda_review_001",
  "recommendations": [
    "Clause 3.2 analysis has moderate uncertainty - recommend human review"
  ]
}`,
    color: GREEN,
  },
  {
    method: "POST",
    path: "/v1/shield",
    name: "Prompt Injection Shield",
    desc: "Pre-flight check. Scan user input BEFORE it reaches the AI model. Catches direct injection, indirect injection, and jailbreak attempts.",
    example: `const shieldCheck = await fetch(
  "https://api.meerkat.ai/v1/shield",
  {
    method: "POST",
    headers: {
      "Authorization": "Bearer mk_live_abc123",
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      input: "Ignore previous instructions and...",
      domain: "legal",
      sensitivity: "high"
    })
  }
);

// Response:
{
  "safe": false,
  "threat_level": "HIGH",
  "attack_type": "direct_injection",
  "detail": "Input contains instruction override pattern",
  "action": "BLOCK",
  "sanitized_input": null
}`,
    color: RED,
  },
  {
    method: "GET",
    path: "/v1/audit/{audit_id}",
    name: "Audit Trail",
    desc: "Retrieve the full governance record for any past verification. Perfect for compliance reviews, regulator requests, and internal audits.",
    example: `const audit = await fetch(
  "https://api.meerkat.ai/v1/audit/aud_20260207_nda_review_001",
  {
    headers: {
      "Authorization": "Bearer mk_live_abc123"
    }
  }
);

// Response:
{
  "audit_id": "aud_20260207_nda_review_001",
  "timestamp": "2026-02-07T10:30:00Z",
  "user": "attorney_j.smith",
  "domain": "legal",
  "model_used": "claude-sonnet-4-5",
  "plugin": "anthropic-legal-cowork",
  "trust_score": 87,
  "checks_run": ["entailment", "semantic_entropy",
                  "implicit_preference", "claim_extraction"],
  "flags_raised": 1,
  "human_review_required": true,
  "full_trace": "...[complete verification log]..."
}`,
    color: AMBER,
  },
  {
    method: "POST",
    path: "/v1/configure",
    name: "Domain Configuration",
    desc: "Set up your org's risk tolerances, governance policies, and domain-specific rules. Do this once, then every /verify call uses your config automatically.",
    example: `const config = await fetch(
  "https://api.meerkat.ai/v1/configure",
  {
    method: "POST",
    headers: {
      "Authorization": "Bearer mk_live_abc123",
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      org_id: "org_lawfirm_abc",
      domain: "legal",
      config: {
        // Minimum trust score to auto-approve
        auto_approve_threshold: 85,
        // Below this = auto-block
        auto_block_threshold: 40,
        // Between thresholds = flag for human review
        
        // Which checks are mandatory
        required_checks: [
          "entailment", "semantic_entropy"
        ],
        // Optional checks
        optional_checks: [
          "implicit_preference", "claim_extraction"
        ],
        // Domain-specific rules
        legal_rules: {
          jurisdiction: "BC_Canada",
          contract_types: ["NDA", "MSA", "SaaS"],
          risk_categories: ["IP", "non-compete", 
                           "liability", "termination"],
          playbook_id: "pb_standard_commercial"
        },
        // Notification preferences
        alerts: {
          low_score_notify: ["compliance@firm.com"],
          injection_notify: ["security@firm.com"],
          weekly_digest: ["partners@firm.com"]
        }
      }
    })
  }
);

// Response:
{
  "config_id": "cfg_lawfirm_standard",
  "status": "active",
  "domain": "legal",
  "created": "2026-02-07T10:00:00Z"
}`,
    color: PURPLE,
  },
  {
    method: "GET",
    path: "/v1/dashboard",
    name: "Governance Dashboard Data",
    desc: "Powers the real-time governance dashboard. Returns aggregated trust scores, flag trends, and compliance metrics for your org.",
    example: `const dashboard = await fetch(
  "https://api.meerkat.ai/v1/dashboard?period=7d",
  {
    headers: {
      "Authorization": "Bearer mk_live_abc123"
    }
  }
);

// Response:
{
  "period": "2026-01-31 to 2026-02-07",
  "total_verifications": 1247,
  "avg_trust_score": 84.3,
  "auto_approved": 1089,
  "flagged_for_review": 142,
  "auto_blocked": 16,
  "injection_attempts_blocked": 3,
  "top_flags": [
    { "type": "semantic_entropy", "count": 89 },
    { "type": "unverified_claim", "count": 47 },
    { "type": "implicit_bias", "count": 6 }
  ],
  "compliance_score": 97.2,
  "trend": "improving"
}`,
    color: PINK,
  },
];

// ─── Integration Examples ───
const INTEGRATIONS = [
  {
    name: "Anthropic Legal Plugin",
    icon: "⚖️",
    how: "MCP Server",
    effort: "~2 hours",
    desc: "Add Meerkat as an MCP server in the Cowork plugin config. Every /review-contract and /triage-nda command automatically routes through Meerkat's /verify endpoint. Zero code changes to the plugin itself.",
    code: `// In your Cowork plugin's mcp_servers config:
{
  "mcp_servers": {
    "meerkat-governance": {
      "url": "https://api.meerkat.ai/mcp",
      "api_key": "mk_live_abc123",
      "config_id": "cfg_lawfirm_standard",
      "mode": "intercept"  // auto-check all outputs
    }
  }
}`
  },
  {
    name: "Anthropic API (Direct)",
    icon: "🔌",
    how: "Proxy / Wrapper",
    effort: "~30 minutes",
    desc: "Point your Anthropic API calls through Meerkat's proxy endpoint. Meerkat forwards to Anthropic, gets the response, verifies it, and returns the verified result. One URL change.",
    code: `// BEFORE (direct to Anthropic):
const response = await fetch(
  "https://api.anthropic.com/v1/messages",
  { ... }
);

// AFTER (through Meerkat proxy):
const response = await fetch(
  "https://proxy.meerkat.ai/anthropic/v1/messages",
  {
    headers: {
      "x-meerkat-key": "mk_live_abc123",
      "x-anthropic-api-key": "sk-ant-...",
      "x-meerkat-checks": "entailment,entropy",
    },
    // everything else stays identical
    ...
  }
);
// Response includes original + meerkat governance overlay`
  },
  {
    name: "Meerkat Financial (AWS)",
    icon: "🏦",
    how: "AWS Middleware",
    effort: "Deploy stack",
    desc: "Your existing 6-layer architecture. Meerkat Financial deploys as a CloudFormation stack in the client's AWS account. All AI traffic routes through your API Gateway → Lambda → Meerkat verification layers.",
    code: `# Deploy Meerkat Financial in client's AWS:
aws cloudformation deploy \\
  --template meerkat-financial-stack.yaml \\
  --stack-name meerkat-governance \\
  --parameter-overrides \\
    MeerkatApiKey=mk_live_abc123 \\
    Domain=financial \\
    Region=ca-central-1

# Result: API Gateway endpoint that wraps
# any AI model with governance checks
# https://abc123.execute-api.ca-central-1.amazonaws.com/v1/`
  },
  {
    name: "Healthcare (Cerner/Epic)",
    icon: "🏥",
    how: "FHIR + HL7 Bridge",
    effort: "TRUST integration",
    desc: "The original TRUST use case. Meerkat connects to Cerner's sandbox EMR via FHIR APIs, intercepts AI Scribe outputs, and verifies them against patient records using DeBERTa entailment.",
    code: `// TRUST Healthcare Integration:
const verified = await fetch(
  "https://api.meerkat.ai/v1/verify",
  {
    method: "POST",
    body: JSON.stringify({
      input: "[AI Scribe transcript]",
      output: "[Generated clinical note]",
      context: "[FHIR patient record bundle]",
      checks: ["entailment", "semantic_entropy",
               "implicit_preference"],
      domain: "healthcare",
      config_id: "cfg_trust_cardiac"
    })
  }
);`
  },
];

// ─── Business Model ───
const PRICING_TIERS = [
  {
    name: "Starter",
    price: "$0.002",
    unit: "per verification",
    features: ["Entailment checking", "Semantic entropy", "Basic audit trail", "1 domain", "Email support"],
    color: MUTED,
    best: "Solo practitioners, small firms testing the waters"
  },
  {
    name: "Professional",
    price: "$499",
    unit: "per month",
    features: ["All 4 governance checks", "Unlimited verifications", "Full audit trail + export", "3 domains", "Dashboard access", "Prompt injection shield", "Priority support"],
    color: CYAN,
    best: "Mid-size firms, hospital departments, financial advisory"
  },
  {
    name: "Enterprise",
    price: "Custom",
    unit: "per-bed / per-seat",
    features: ["Everything in Professional", "On-premise / private cloud deploy", "Custom domain configs", "Unlimited domains", "SOC 2 / HIPAA / FINRA compliance", "SLA guarantee", "Dedicated support", "Sentinel monitoring agent"],
    color: AMBER,
    best: "Hospital networks, large law firms, banks, insurance"
  },
];

// ─── Styles ───
const styles = {
  container: { fontFamily: "'IBM Plex Sans', 'Segoe UI', sans-serif", background: DARK, color: TEXT, minHeight: "100vh", padding: "0" },
  header: { background: `linear-gradient(135deg, ${DARK} 0%, #0f172a 50%, #1a1a2e 100%)`, padding: "48px 32px 32px", borderBottom: `1px solid ${BORDER}`, textAlign: "center" },
  headerTitle: { fontSize: "36px", fontWeight: 800, letterSpacing: "-1px", margin: 0, background: `linear-gradient(135deg, ${CYAN}, ${AMBER})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" },
  headerSub: { fontSize: "16px", color: MUTED, marginTop: "8px", fontWeight: 400 },
  nav: { display: "flex", gap: "4px", padding: "16px 24px", background: CARD, borderBottom: `1px solid ${BORDER}`, flexWrap: "wrap", justifyContent: "center" },
  navBtn: (active) => ({ padding: "10px 18px", borderRadius: "8px", border: `1px solid ${active ? CYAN : BORDER}`, background: active ? `${CYAN}15` : "transparent", color: active ? CYAN : MUTED, cursor: "pointer", fontSize: "13px", fontWeight: active ? 700 : 500, transition: "all 0.2s", whiteSpace: "nowrap" }),
  content: { maxWidth: "960px", margin: "0 auto", padding: "32px 24px" },
  card: { background: CARD, border: `1px solid ${BORDER}`, borderRadius: "12px", padding: "24px", marginBottom: "20px" },
  cardTitle: { fontSize: "18px", fontWeight: 700, marginBottom: "12px", display: "flex", alignItems: "center", gap: "10px" },
  tag: (color) => ({ display: "inline-block", padding: "3px 10px", borderRadius: "6px", fontSize: "11px", fontWeight: 700, background: `${color}20`, color, letterSpacing: "0.5px" }),
  codeBlock: { background: "#0d1117", border: `1px solid ${BORDER}`, borderRadius: "8px", padding: "16px", fontSize: "12px", fontFamily: "'JetBrains Mono', 'Fira Code', monospace", overflowX: "auto", lineHeight: 1.6, color: "#e6edf3", whiteSpace: "pre-wrap", wordBreak: "break-word" },
  flowStep: (color, isActive) => ({ background: isActive ? `${color}10` : CARD, border: `1px solid ${isActive ? color : BORDER}`, borderRadius: "12px", padding: "20px", cursor: "pointer", transition: "all 0.2s", marginBottom: "12px" }),
  stepNumber: (color) => ({ width: "36px", height: "36px", borderRadius: "50%", background: `${color}20`, color, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: "14px", flexShrink: 0 }),
  arrow: { textAlign: "center", color: DIM, fontSize: "20px", margin: "4px 0" },
  pricingCard: (color) => ({ background: CARD, border: `1px solid ${color}40`, borderRadius: "12px", padding: "24px", flex: "1", minWidth: "250px" }),
};

const TABS = [
  { id: "idea", label: "💡 The Big Idea", },
  { id: "flow", label: "🔄 How It Works" },
  { id: "api", label: "📡 API Endpoints" },
  { id: "integrate", label: "🔌 Integrations" },
  { id: "pricing", label: "💰 Business Model" },
];

export default function MeerkatAPI() {
  const [tab, setTab] = useState("idea");
  const [activeStep, setActiveStep] = useState(null);
  const [activeEndpoint, setActiveEndpoint] = useState(0);
  const [activeInteg, setActiveInteg] = useState(0);

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <div style={{ fontSize: "48px", marginBottom: "8px" }}>🔭</div>
        <h1 style={styles.headerTitle}>Meerkat Governance API</h1>
        <p style={styles.headerSub}>Automated AI Governance Integration for Legal, Financial & Healthcare AI Agents</p>
        <p style={{ fontSize: "12px", color: DIM, marginTop: "12px" }}>One API. Any AI model. Every regulated industry.</p>
      </div>

      {/* Nav */}
      <div style={styles.nav}>
        {TABS.map(t => (
          <button key={t.id} style={styles.navBtn(tab === t.id)} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={styles.content}>

        {/* ═══ TAB: BIG IDEA ═══ */}
        {tab === "idea" && (
          <div>
            <div style={{ ...styles.card, borderColor: `${CYAN}30` }}>
              <div style={styles.cardTitle}>
                <span style={{ fontSize: "28px" }}>{BIG_IDEA.icon}</span>
                <span>{BIG_IDEA.title}</span>
              </div>
              {BIG_IDEA.content.map((section, i) => (
                <div key={i} style={{ marginBottom: i < BIG_IDEA.content.length - 1 ? "24px" : 0 }}>
                  <h3 style={{ color: CYAN, fontSize: "15px", fontWeight: 700, marginBottom: "8px" }}>{section.heading}</h3>
                  <p style={{ color: MUTED, fontSize: "14px", lineHeight: 1.8, whiteSpace: "pre-line", margin: 0 }}>{section.text}</p>
                </div>
              ))}
            </div>

            {/* The Key Insight Box */}
            <div style={{ ...styles.card, borderColor: `${AMBER}40`, background: `${AMBER}08` }}>
              <div style={styles.cardTitle}>
                <span style={{ fontSize: "20px" }}>🎯</span>
                <span style={{ color: AMBER }}>The Key Insight for Investors</span>
              </div>
              <p style={{ color: MUTED, fontSize: "14px", lineHeight: 1.8, margin: 0 }}>
                Anthropic builds the <span style={{ color: CYAN, fontWeight: 700 }}>brain</span>. 
                Domain plugins add <span style={{ color: PURPLE, fontWeight: 700 }}>skills</span>. 
                But regulated industries need <span style={{ color: AMBER, fontWeight: 700 }}>supervision</span>.
              </p>
              <div style={{ marginTop: "16px", display: "flex", flexWrap: "wrap", gap: "8px" }}>
                {["Legal plugin → Who verifies contract analysis?", "Financial plugin → Who catches biased recommendations?", "Healthcare AI → Who ensures clinical accuracy?"].map((q, i) => (
                  <div key={i} style={{ background: `${AMBER}10`, border: `1px solid ${AMBER}25`, borderRadius: "8px", padding: "10px 14px", fontSize: "13px", color: AMBER, flex: "1", minWidth: "240px" }}>
                    {q}
                  </div>
                ))}
              </div>
              <p style={{ color: TEXT, fontSize: "15px", fontWeight: 700, marginTop: "16px", marginBottom: 0 }}>
                Answer: Meerkat. The governance API layer that every regulated AI deployment needs.
              </p>
            </div>

            {/* Simple Diagram */}
            <div style={{ ...styles.card, textAlign: "center" }}>
              <div style={styles.cardTitle}><span>📐</span><span>Architecture in One Picture</span></div>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "8px", marginTop: "16px" }}>
                {[
                  { label: "User", sub: "(Lawyer / Analyst / Doctor)", color: MUTED, bg: `${MUTED}15` },
                  null,
                  { label: "🛡️ MEERKAT API", sub: "Shield + Verify + Audit", color: CYAN, bg: `${CYAN}15`, big: true },
                  null,
                  { label: "AI Model", sub: "(Claude / GPT / Gemini + Plugin)", color: PURPLE, bg: `${PURPLE}15` },
                ].map((item, i) =>
                  item === null ? (
                    <div key={i} style={{ color: DIM, fontSize: "20px" }}>↕</div>
                  ) : (
                    <div key={i} style={{ background: item.bg, border: `1px solid ${item.color}40`, borderRadius: "10px", padding: item.big ? "20px 40px" : "12px 32px", minWidth: "280px" }}>
                      <div style={{ color: item.color, fontWeight: 800, fontSize: item.big ? "18px" : "15px" }}>{item.label}</div>
                      <div style={{ color: DIM, fontSize: "12px", marginTop: "4px" }}>{item.sub}</div>
                    </div>
                  )
                )}
              </div>
              <p style={{ color: DIM, fontSize: "12px", marginTop: "16px", marginBottom: 0 }}>Meerkat sits between the user and the AI — inspecting everything in both directions</p>
            </div>
          </div>
        )}

        {/* ═══ TAB: FLOW ═══ */}
        {tab === "flow" && (
          <div>
            <p style={{ color: MUTED, fontSize: "14px", marginBottom: "24px" }}>
              Click any step to see what happens at each stage. Follow the flow from top to bottom — this is the journey of every AI request through Meerkat.
            </p>
            {FLOW_STEPS.map((step, i) => (
              <div key={step.id}>
                <div
                  style={styles.flowStep(step.color, activeStep === step.id)}
                  onClick={() => setActiveStep(activeStep === step.id ? null : step.id)}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
                    <div style={styles.stepNumber(step.color)}>{step.id}</div>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
                        <span style={{ fontSize: "18px" }}>{step.icon}</span>
                        <span style={{ fontWeight: 700, fontSize: "15px" }}>{step.label}</span>
                        {(step.id === 2 || step.id === 4 || step.id === 5) && (
                          <span style={styles.tag(step.color)}>MEERKAT</span>
                        )}
                      </div>
                      <div style={{ color: MUTED, fontSize: "13px" }}>{step.desc}</div>
                    </div>
                    <span style={{ color: DIM, fontSize: "20px" }}>{activeStep === step.id ? "−" : "+"}</span>
                  </div>
                  {activeStep === step.id && (
                    <div style={{ marginTop: "16px", paddingTop: "16px", borderTop: `1px solid ${BORDER}`, color: MUTED, fontSize: "13px", lineHeight: 1.8 }}>
                      {step.detail}
                    </div>
                  )}
                </div>
                {i < FLOW_STEPS.length - 1 && <div style={styles.arrow}>↓</div>}
              </div>
            ))}

            <div style={{ ...styles.card, marginTop: "24px", borderColor: `${GREEN}30` }}>
              <div style={styles.cardTitle}><span>⏱️</span><span>Performance</span></div>
              <p style={{ color: MUTED, fontSize: "13px", margin: 0, lineHeight: 1.8 }}>
                Total added latency: <span style={{ color: GREEN, fontWeight: 700 }}>~200-400ms</span> per request.
                That's barely noticeable when a contract review already takes 5-15 seconds.
                The DeBERTa entailment check runs on ONNX-optimized Azure ML endpoints for speed.
                Prompt injection shield adds only ~50ms since it's a lightweight classifier.
              </p>
            </div>
          </div>
        )}

        {/* ═══ TAB: API ENDPOINTS ═══ */}
        {tab === "api" && (
          <div>
            <p style={{ color: MUTED, fontSize: "14px", marginBottom: "24px" }}>
              These are the 5 core endpoints of the Meerkat API. Click each one to see the full request/response example. A developer can integrate in under 30 minutes.
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginBottom: "24px" }}>
              {API_ENDPOINTS.map((ep, i) => (
                <button
                  key={i}
                  onClick={() => setActiveEndpoint(i)}
                  style={{
                    ...styles.navBtn(activeEndpoint === i),
                    borderColor: activeEndpoint === i ? ep.color : BORDER,
                    color: activeEndpoint === i ? ep.color : MUTED,
                    background: activeEndpoint === i ? `${ep.color}12` : "transparent",
                  }}
                >
                  <span style={styles.tag(ep.color)}>{ep.method}</span>{" "}
                  {ep.name}
                </button>
              ))}
            </div>

            {(() => {
              const ep = API_ENDPOINTS[activeEndpoint];
              return (
                <div style={{ ...styles.card, borderColor: `${ep.color}30` }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" }}>
                    <span style={styles.tag(ep.color)}>{ep.method}</span>
                    <code style={{ color: ep.color, fontSize: "15px", fontWeight: 700 }}>{ep.path}</code>
                  </div>
                  <h3 style={{ fontSize: "18px", fontWeight: 700, marginBottom: "8px" }}>{ep.name}</h3>
                  <p style={{ color: MUTED, fontSize: "13px", lineHeight: 1.7, marginBottom: "20px" }}>{ep.desc}</p>
                  <div style={styles.codeBlock}>
                    {ep.example}
                  </div>
                </div>
              );
            })()}
          </div>
        )}

        {/* ═══ TAB: INTEGRATIONS ═══ */}
        {tab === "integrate" && (
          <div>
            <p style={{ color: MUTED, fontSize: "14px", marginBottom: "24px" }}>
              The whole point of the Meerkat API is that integration is fast and painless. Here are the 4 main integration paths — from "plug and play" to "full deployment."
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginBottom: "24px" }}>
              {INTEGRATIONS.map((integ, i) => (
                <button
                  key={i}
                  onClick={() => setActiveInteg(i)}
                  style={styles.navBtn(activeInteg === i)}
                >
                  {integ.icon} {integ.name}
                </button>
              ))}
            </div>

            {(() => {
              const integ = INTEGRATIONS[activeInteg];
              return (
                <div style={styles.card}>
                  <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "12px" }}>
                    <span style={{ fontSize: "32px" }}>{integ.icon}</span>
                    <div>
                      <h3 style={{ fontSize: "18px", fontWeight: 700, margin: 0 }}>{integ.name}</h3>
                      <div style={{ display: "flex", gap: "8px", marginTop: "6px" }}>
                        <span style={styles.tag(CYAN)}>{integ.how}</span>
                        <span style={styles.tag(GREEN)}>Setup: {integ.effort}</span>
                      </div>
                    </div>
                  </div>
                  <p style={{ color: MUTED, fontSize: "13px", lineHeight: 1.8, marginBottom: "20px" }}>{integ.desc}</p>
                  <div style={styles.codeBlock}>
                    {integ.code}
                  </div>
                </div>
              );
            })()}

            {/* MCP Callout */}
            <div style={{ ...styles.card, borderColor: `${PURPLE}30`, background: `${PURPLE}08` }}>
              <div style={styles.cardTitle}><span>🔗</span><span style={{ color: PURPLE }}>Why MCP Is the Key</span></div>
              <p style={{ color: MUTED, fontSize: "13px", lineHeight: 1.8, margin: 0 }}>
                Anthropic's plugins are built on <strong style={{ color: PURPLE }}>MCP (Model Context Protocol)</strong> — their open standard for connecting AI to external systems. 
                This is a gift for Meerkat. By implementing the Meerkat API as an MCP server, any Cowork plugin (legal, financial, healthcare) can add governance with a single config line. 
                No code changes. No custom integration. Just add Meerkat as an MCP connection and every AI output gets verified automatically.
                This is the "automated integration" you're asking about — MCP makes it possible.
              </p>
            </div>
          </div>
        )}

        {/* ═══ TAB: PRICING ═══ */}
        {tab === "pricing" && (
          <div>
            <p style={{ color: MUTED, fontSize: "14px", marginBottom: "24px" }}>
              Three tiers designed to match how governance needs scale. The API-first approach means clients start small and grow.
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "16px", marginBottom: "24px" }}>
              {PRICING_TIERS.map((tier, i) => (
                <div key={i} style={styles.pricingCard(tier.color)}>
                  <div style={{ color: tier.color, fontSize: "12px", fontWeight: 700, letterSpacing: "1px", marginBottom: "8px" }}>{tier.name.toUpperCase()}</div>
                  <div style={{ display: "flex", alignItems: "baseline", gap: "4px", marginBottom: "4px" }}>
                    <span style={{ fontSize: "28px", fontWeight: 800, color: TEXT }}>{tier.price}</span>
                    <span style={{ fontSize: "13px", color: DIM }}>{tier.unit}</span>
                  </div>
                  <p style={{ fontSize: "12px", color: DIM, marginBottom: "16px", fontStyle: "italic" }}>Best for: {tier.best}</p>
                  <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                    {tier.features.map((f, j) => (
                      <li key={j} style={{ fontSize: "13px", color: MUTED, padding: "5px 0", borderBottom: `1px solid ${BORDER}`, display: "flex", alignItems: "center", gap: "8px" }}>
                        <span style={{ color: tier.color }}>✓</span> {f}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            {/* Revenue projection */}
            <div style={{ ...styles.card, borderColor: `${GREEN}30` }}>
              <div style={styles.cardTitle}><span>📊</span><span>Revenue Math</span></div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "16px", marginTop: "12px" }}>
                {[
                  { label: "Legal Plugin Users", stat: "~160K installs", sub: "Already installed (per Anthropic's page)", color: PURPLE },
                  { label: "If 1% convert to Pro", stat: "1,600 firms", sub: "× $499/mo = $9.6M ARR", color: CYAN },
                  { label: "Enterprise (Cerner)", stat: "20K-30K facilities", sub: "Per-bed model → $350K-$14M", color: AMBER },
                  { label: "Financial Services", stat: "New market", sub: "Banks, insurance, advisory", color: GREEN },
                ].map((item, i) => (
                  <div key={i} style={{ background: `${item.color}08`, border: `1px solid ${item.color}25`, borderRadius: "8px", padding: "16px" }}>
                    <div style={{ color: DIM, fontSize: "11px", fontWeight: 700, letterSpacing: "0.5px" }}>{item.label}</div>
                    <div style={{ color: item.color, fontSize: "20px", fontWeight: 800, margin: "6px 0" }}>{item.stat}</div>
                    <div style={{ color: MUTED, fontSize: "12px" }}>{item.sub}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Footer */}
        <div style={{ textAlign: "center", padding: "32px 0 16px", borderTop: `1px solid ${BORDER}`, marginTop: "32px" }}>
          <p style={{ color: DIM, fontSize: "12px", margin: 0 }}>
            🔭 Meerkat Governance API — Always watching. Always verifying. Always trustworthy.
          </p>
          <p style={{ color: DIM, fontSize: "11px", marginTop: "4px" }}>
            Meerkat Platform by Jean & CL — Vancouver, BC
          </p>
        </div>
      </div>
    </div>
  );
}
