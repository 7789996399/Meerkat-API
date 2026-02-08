# Architecture

> Technical deep-dive into the Meerkat Governance API — for developers, contributors, and technical reviewers.

---

## 1. System Overview

Meerkat API is a **stateless verification middleware** that sits between client applications and AI models. It intercepts requests and responses, applies governance checks, and produces auditable trust scores.

**Core design principles:**

| Principle | Detail |
|-----------|--------|
| **Stateless** | No session state between requests. Each verification is self-contained. Audit logs are the only persistent artifact. |
| **Model-agnostic** | Works with Claude, GPT, Gemini, Llama, Mistral, or any model that accepts text in / text out. Meerkat never touches model weights. |
| **Domain-configurable** | Governance rules, thresholds, and check suites are configured per domain (legal, financial, healthcare) and per organization. |
| **Low-latency** | Target: **<400ms added latency** on top of the underlying model call. The prompt injection shield adds ~50ms. Full verification adds ~200-400ms using ONNX-optimized inference. |
| **Audit-first** | Every governance decision produces an immutable audit record before the response is returned. The audit trail is not optional. |

---

## 2. Architecture Diagram

```
                    ┌──────────────────────┐
                    │   Client App /       │
                    │   Cowork Plugin /    │
                    │   API Consumer       │
                    └──────────┬───────────┘
                               │
                          HTTP Request
                               │
                               ▼
                ┌──────────────────────────────┐
                │       MEERKAT INGRESS         │
                │       (Pre-flight)            │
                │                               │
                │  ┌─────────────────────────┐  │
                │  │  Authentication         │  │  ← Bearer token validation
                │  │  Rate Limiting          │  │  ← Per-org request quotas
                │  │  Input Sanitization     │  │  ← XSS / injection cleanup
                │  └────────────┬────────────┘  │
                │               │               │
                │  ┌────────────▼────────────┐  │
                │  │  /v1/shield             │  │  ← Prompt injection scan
                │  │  Prompt Injection       │  │  ← Jailbreak detection
                │  │  Detection              │  │  ← Policy violation check
                │  └────────────┬────────────┘  │
                │               │               │
                │         PASS ─┤─ BLOCK ──────────── 403 + audit log
                │               │               │
                └───────────────┼───────────────┘
                                │
                           Sanitized
                            Request
                                │
                                ▼
                ┌──────────────────────────────┐
                │         AI MODEL              │
                │                               │
                │   Claude / GPT / Gemini /     │  ← Meerkat forwards request
                │   Llama / Any provider        │  ← Model processes normally
                │                               │  ← Meerkat receives response
                └───────────────┬───────────────┘
                                │
                          Raw AI Response
                                │
                                ▼
                ┌──────────────────────────────┐
                │       MEERKAT EGRESS          │
                │       (Verification)          │
                │                               │
                │  ┌─────────────────────────┐  │
                │  │  /v1/verify             │  │
                │  │                         │  │
                │  │  ┌───────────────────┐  │  │
                │  │  │ DeBERTa Entailment│  │  │  ← Claims match source?
                │  │  ├───────────────────┤  │  │
                │  │  │ Semantic Entropy  │  │  │  ← Model confident?
                │  │  ├───────────────────┤  │  │
                │  │  │ Implicit Pref.    │  │  │  ← Hidden bias?
                │  │  ├───────────────────┤  │  │
                │  │  │ Claim Extraction  │  │  │  ← Facts verifiable?
                │  │  └───────────────────┘  │  │
                │  └────────────┬────────────┘  │
                │               │               │
                └───────────────┼───────────────┘
                                │
                                ▼
                ┌──────────────────────────────┐
                │     GOVERNANCE SCORE          │
                │                               │
                │  Trust Score: 0-100            │
                │  Status: PASS / FLAG / BLOCK   │
                │  Flags: [specific issues]      │
                │  Recommendations: [actions]    │
                │                               │
                │  ┌─────────────────────────┐  │
                │  │  Audit Trail (logged)   │  │  ← Immutable record
                │  │  audit_id: aud_xxx      │  │  ← Timestamp + full trace
                │  └─────────────────────────┘  │
                └───────────────┬───────────────┘
                                │
                       Verified Response
                     + Governance Overlay
                                │
                                ▼
                    ┌──────────────────────┐
                    │   Client App /       │
                    │   End User           │
                    └──────────────────────┘
```

**Decision flow for governance scores:**

```
Trust Score ≥ auto_approve_threshold (default 85)  →  PASS   (auto-approved)
Trust Score ≥ auto_block_threshold (default 40)     →  FLAG   (human review required)
Trust Score < auto_block_threshold                  →  BLOCK  (response withheld)
```

---

## 3. Governance Engine Detail

### a) DeBERTa Entailment — `entailment.py`

**What:** Natural Language Inference (NLI) model that determines whether the AI's output is logically supported by the source documents. This is the primary hallucination detector.

**How it works:**

```
Input:
  premise  = source document passage (e.g., contract text)
  hypothesis = AI's claim (e.g., "Clause 3.2 contains a non-compete")

DeBERTa NLI Model
       │
       ▼
Output:
  entailment:    0.92  ← claim IS supported by the source
  contradiction: 0.05  ← claim CONTRADICTS the source
  neutral:       0.03  ← claim is neither supported nor contradicted
```

**Scoring:**
- Each AI output is split into individual claims (see Claim Extraction below)
- Each claim is evaluated against the most relevant source passage
- Final entailment score = weighted average across all claims
- Contradictions trigger immediate flags regardless of overall score

**Demo mode:** Simulated with keyword overlap scoring between output and source context, plus randomized variance. Returns realistic-looking scores without running the actual model.

**Production mode:** `microsoft/deberta-v3-large` fine-tuned on domain-specific NLI data (legal precedent pairs, clinical note/record pairs). Exported to ONNX for CPU inference at ~50ms per claim pair.

```python
# Core entailment check (simplified)
async def check_entailment(claim: str, source: str) -> EntailmentResult:
    inputs = tokenizer(source, claim, return_tensors="np", truncation=True)
    logits = onnx_session.run(None, dict(inputs))[0]
    scores = softmax(logits[0])
    return EntailmentResult(
        entailment=float(scores[0]),
        contradiction=float(scores[1]),
        neutral=float(scores[2]),
        flags=["entailment_contradiction"] if scores[1] > 0.5 else []
    )
```

---

### b) Semantic Entropy — `entropy.py`

**What:** Measures how confident the AI model is in its answer. High entropy = the model would give different answers if asked again = low confidence = unreliable.

**How it works:**

```
Step 1: Request N completions (default N=5) for the same prompt
        with temperature > 0

Step 2: Embed each completion using sentence-transformers

Step 3: Cluster completions by semantic similarity
        (not lexical — "the clause is void" ≈ "this section is invalid")

Step 4: Entropy = distribution spread across clusters
        ┌─────────────────────────────────────────────┐
        │ Low entropy (good):    ████████████          │
        │ All 5 responses say roughly the same thing   │
        │                                              │
        │ High entropy (bad):    ██ ██ █ ███ ██        │
        │ Responses diverge — model is uncertain       │
        └─────────────────────────────────────────────┘
```

**Scoring:**
- Entropy score 0.0-1.0 (lower is better)
- Threshold configurable per domain (legal defaults to 0.3, healthcare to 0.2)
- Scores above threshold trigger `moderate_uncertainty` or `high_uncertainty` flags

**Demo mode:** Simulated entropy calculated from response length, keyword density, and domain heuristics. Longer, more hedging responses ("may", "could", "possibly") produce higher simulated entropy.

**Production mode:** Makes N parallel API calls to the underlying model, embeds with `all-MiniLM-L6-v2`, clusters with agglomerative clustering at cosine distance threshold 0.3, computes discrete entropy over cluster distribution.

```python
async def check_entropy(prompt: str, model_config: ModelConfig, n: int = 5) -> EntropyResult:
    # Sample N completions
    completions = await asyncio.gather(*[
        call_model(prompt, model_config, temperature=0.7) for _ in range(n)
    ])

    # Embed and cluster
    embeddings = encoder.encode(completions)
    clusters = cluster_by_similarity(embeddings, threshold=0.3)

    # Compute entropy over cluster distribution
    distribution = [len(c) / n for c in clusters]
    entropy = -sum(p * math.log2(p) for p in distribution if p > 0)
    normalized = entropy / math.log2(n)  # normalize to 0-1

    return EntropyResult(
        score=normalized,
        num_clusters=len(clusters),
        flags=["high_uncertainty"] if normalized > 0.6 else
              ["moderate_uncertainty"] if normalized > 0.3 else []
    )
```

---

### c) Implicit Preference — `preference.py`

**What:** Detects hidden directional bias in AI recommendations. Does the model favor one side of a negotiation? Does it consistently recommend one treatment over another without clinical basis?

**How it works:**

```
Step 1: Take the original prompt and construct a "mirror" prompt
        that frames the same question from the opposite perspective

        Original:  "Should the tenant accept this lease clause?"
        Mirror:    "Should the landlord insist on this lease clause?"

Step 2: Send both to the AI model

Step 3: Compare response embeddings using cosine similarity

Step 4: High divergence = the model's answer depends heavily on
        framing = implicit preference detected

        ┌──────────────────────────────────────────┐
        │ Similarity > 0.85  →  No bias detected   │
        │ Similarity 0.6-0.85 → Mild preference     │
        │ Similarity < 0.6   →  Strong bias flagged │
        └──────────────────────────────────────────┘
```

**Scoring:**
- Preference score 0.0-1.0 (higher is better — high means balanced)
- Domain-specific mirror prompt templates (legal: tenant/landlord, financial: buy/sell, healthcare: treatment A/B)

**Demo mode:** Simulated bias score based on sentiment polarity analysis of the response. Strongly positive or negative sentiment in recommendations produces lower scores.

**Production mode:** Automated dual-prompt generation using domain templates, parallel model calls, `all-MiniLM-L6-v2` embedding, cosine similarity comparison.

```python
async def check_preference(
    prompt: str, output: str, domain: str, model_config: ModelConfig
) -> PreferenceResult:
    mirror = generate_mirror_prompt(prompt, domain)

    original_response, mirror_response = await asyncio.gather(
        call_model(prompt, model_config, temperature=0.0),
        call_model(mirror, model_config, temperature=0.0)
    )

    emb_orig = encoder.encode([original_response])
    emb_mirror = encoder.encode([mirror_response])
    similarity = cosine_similarity(emb_orig, emb_mirror)[0][0]

    return PreferenceResult(
        score=float(similarity),
        flags=["strong_bias"] if similarity < 0.6 else
              ["mild_preference"] if similarity < 0.85 else []
    )
```

---

### d) Claim Extraction — `claims.py`

**What:** Extracts specific factual assertions from the AI's output and classifies each as verified, unverified, or contradicted against the source context.

**How it works:**

```
AI Output: "The NDA includes a 2-year non-compete clause covering
            all of North America, with a $50,000 penalty for breach."

Extracted Claims:
  ┌────┬──────────────────────────────────────┬──────────────┐
  │ #  │ Claim                                │ Status       │
  ├────┼──────────────────────────────────────┼──────────────┤
  │ 1  │ NDA includes a non-compete clause    │ VERIFIED      │
  │ 2  │ Non-compete duration is 2 years      │ VERIFIED      │
  │ 3  │ Coverage is all of North America     │ CONTRADICTED  │
  │ 4  │ Penalty for breach is $50,000        │ UNVERIFIED    │
  └────┴──────────────────────────────────────┴──────────────┘

  Source says: "...non-compete limited to British Columbia..."
  → Claim 3 contradicts the source document
  → Claim 4 has no corresponding source passage
```

**Scoring:**
- Returns total claims, verified count, unverified count, contradicted count
- Any contradicted claim triggers `claim_contradiction` flag
- Unverified claims trigger `unverified_claim` flag if count exceeds threshold

**Demo mode:** Regex-based claim extraction targeting patterns like numbers, durations, named entities, and monetary values. Mock verification using keyword search against source context.

**Production mode:** Fine-tuned claim extraction model (based on T5-small) for structured claim parsing, followed by per-claim entailment verification against source using the DeBERTa engine from check (a).

```python
async def extract_and_verify(
    output: str, context: str
) -> ClaimsResult:
    claims = claim_extractor.extract(output)  # list of claim strings
    results = []

    for claim in claims:
        entailment = await check_entailment(claim, context)
        if entailment.contradiction > 0.5:
            status = "contradicted"
        elif entailment.entailment > 0.7:
            status = "verified"
        else:
            status = "unverified"
        results.append(ClaimResult(text=claim, status=status))

    contradicted = sum(1 for r in results if r.status == "contradicted")
    unverified = sum(1 for r in results if r.status == "unverified")

    return ClaimsResult(
        claims=len(results),
        verified=len(results) - contradicted - unverified,
        unverified=unverified,
        contradicted=contradicted,
        details=results,
        flags=(["claim_contradiction"] if contradicted > 0 else []) +
              (["unverified_claim"] if unverified > 2 else [])
    )
```

---

## 4. Data Models

All request/response schemas use Pydantic v2 with strict validation.

### VerifyRequest / VerifyResponse

```python
class VerifyRequest(BaseModel):
    input: str                                    # What the user asked
    output: str                                   # What the AI responded
    context: str | None = None                    # Source document for entailment
    checks: list[GovernanceCheck] = [             # Which checks to run
        "entailment", "semantic_entropy",
        "implicit_preference", "claim_extraction"
    ]
    domain: Domain                                # "legal" | "financial" | "healthcare"
    config_id: str | None = None                  # Org-specific config override
    model: str | None = None                      # Model that generated the output
    metadata: dict | None = None                  # Passthrough metadata

class VerifyResponse(BaseModel):
    trust_score: int                              # 0-100 composite score
    status: Literal["PASS", "FLAG", "BLOCK"]      # Governance decision
    checks: dict[str, CheckResult]                # Per-check results
    audit_id: str                                 # Unique audit trail reference
    recommendations: list[str]                    # Human-readable action items
    latency_ms: int                               # Total verification time
```

### ShieldRequest / ShieldResponse

```python
class ShieldRequest(BaseModel):
    input: str                                    # Raw user input to scan
    domain: Domain                                # Domain context
    sensitivity: Literal["low", "medium", "high"] = "medium"

class ShieldResponse(BaseModel):
    safe: bool                                    # Pass/fail
    threat_level: Literal["NONE", "LOW", "MEDIUM", "HIGH"]
    attack_type: str | None = None                # "direct_injection", "jailbreak", etc.
    detail: str                                   # Human-readable explanation
    action: Literal["ALLOW", "SANITIZE", "BLOCK"]
    sanitized_input: str | None = None            # Cleaned version (if SANITIZE)
```

### AuditRecord

```python
class AuditRecord(BaseModel):
    audit_id: str                                 # aud_{timestamp}_{hash}
    timestamp: datetime                           # UTC
    request_hash: str                             # SHA-256 of input (no raw text stored)
    user: str | None = None                       # Authenticated user ID
    domain: Domain
    model_used: str | None = None
    plugin: str | None = None                     # Cowork plugin identifier
    trust_score: int
    status: Literal["PASS", "FLAG", "BLOCK"]
    checks_run: list[str]
    check_results: dict[str, CheckResult]         # Full check details
    flags_raised: int
    recommendations: list[str]
    human_review_required: bool
    latency_ms: int
    config_id: str | None = None                  # Which config was active
```

### GovernanceConfig

```python
class GovernanceConfig(BaseModel):
    org_id: str
    domain: Domain
    config: ConfigRules

class ConfigRules(BaseModel):
    auto_approve_threshold: int = 85              # Score >= this → auto PASS
    auto_block_threshold: int = 40                # Score < this → auto BLOCK
    required_checks: list[GovernanceCheck]         # Must run on every request
    optional_checks: list[GovernanceCheck] = []    # Run if requested
    domain_rules: dict = {}                       # Domain-specific overrides
    alerts: AlertConfig | None = None             # Notification preferences
```

### DashboardMetrics

```python
class DashboardMetrics(BaseModel):
    period: str                                   # "2026-01-31 to 2026-02-07"
    total_verifications: int
    avg_trust_score: float
    auto_approved: int
    flagged_for_review: int
    auto_blocked: int
    injection_attempts_blocked: int
    top_flags: list[FlagCount]                    # Sorted by frequency
    compliance_score: float                       # % of requests that passed
    trend: Literal["improving", "stable", "declining"]
```

---

## 5. MCP Integration

Meerkat implements the **Model Context Protocol (MCP)** server specification, allowing any Anthropic Cowork plugin to add governance with zero code changes.

### How it works

```
┌──────────────────────────────────────────────────────┐
│  Cowork Plugin (e.g., Legal Review)                  │
│                                                       │
│  mcp_servers config:                                 │
│  {                                                    │
│    "meerkat-governance": {                            │
│      "url": "https://api.meerkat.ai/mcp",            │
│      "api_key": "mk_live_xxx",                       │
│      "mode": "intercept"                              │
│    }                                                  │
│  }                                                    │
│                                                       │
│  Plugin calls: /review-contract                       │
│       │                                               │
│       ▼                                               │
│  MCP routes through Meerkat before/after AI call      │
└──────────────────────────────────────────────────────┘
```

### Two operating modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| **Intercept** | Meerkat sits in the request/response path. Low-scoring responses are flagged or blocked before reaching the user. | Production — regulated environments where governance is mandatory |
| **Advisory** | Meerkat runs in parallel. The user gets the AI response immediately, plus a governance overlay with scores and warnings. Nothing is blocked. | Testing, evaluation, low-risk domains where governance is informational |

### MCP server capabilities exposed

```python
MCP_TOOLS = [
    {
        "name": "meerkat_verify",
        "description": "Verify an AI response against source documents",
        "input_schema": VerifyRequest.model_json_schema()
    },
    {
        "name": "meerkat_shield",
        "description": "Scan user input for prompt injection attacks",
        "input_schema": ShieldRequest.model_json_schema()
    },
    {
        "name": "meerkat_audit",
        "description": "Retrieve audit trail for a past verification",
        "input_schema": {"type": "object", "properties": {"audit_id": {"type": "string"}}}
    }
]
```

---

## 6. Demo vs. Production

Transparency on what's real and what's simulated:

| Component | Demo (Phase 1) | Production (Phase 2+) |
|-----------|---------------|----------------------|
| **API endpoints** | Fully functional FastAPI server | Same — no changes needed |
| **Authentication** | Static API keys | Azure AD / JWT with RBAC |
| **Rate limiting** | In-memory counter | Redis-backed sliding window |
| **Prompt injection shield** | Keyword pattern matching + regex | Fine-tuned classifier (distilbert) |
| **DeBERTa entailment** | Keyword overlap scoring + randomized variance | `deberta-v3-large` ONNX inference |
| **Semantic entropy** | Heuristic based on response length + hedge words | Multi-sample API calls + embedding clustering |
| **Implicit preference** | Sentiment polarity approximation | Dual-prompt + cosine similarity |
| **Claim extraction** | Regex pattern matching (numbers, entities, dates) | Fine-tuned T5-small extraction model |
| **Claim verification** | Keyword search against source context | Per-claim DeBERTa entailment |
| **Trust score** | Weighted average of simulated check scores | Weighted average of real check scores |
| **Audit trail** | In-memory dict (lost on restart) | DynamoDB / PostgreSQL with encryption |
| **Dashboard data** | Seeded sample data | Live aggregation from audit store |
| **MCP server** | Full MCP protocol server (FastMCP + httpx) | Same -- production-ready |
| **Latency** | ~50ms (no real inference) | ~200-400ms (ONNX inference) |

**The API contract is identical between demo and production.** A client integrated against the demo API will work without changes when pointed at production. Only the quality of governance scores improves.

---

## 7. Tier 2 -- Metacognitive Engine

The governance checks in Section 3 (entailment, entropy, preference, claims) form **Tier 1** -- fast, deterministic or semi-deterministic checks that catch obvious problems. Think of Tier 1 as the security camera.

Tier 2 is the detective who reviews the footage.

### Two-tier architecture

| Tier | Role | Speed | What it catches |
|------|------|-------|-----------------|
| **Tier 1** | Deterministic checks | ~50-400ms | Wrong numbers, contradicted facts, hedged language, overt bias |
| **Tier 2** | Metacognitive reasoning | ~500-1000ms | Plausible-but-wrong reasoning, subtle bias, domain-specific red flags |

Tier 1 produces a **signal vector** -- four scores plus extracted claims. Tier 2 takes this signal vector as input, along with the original claim, source context, and domain, and evaluates whether the combination of signals indicates a real problem or a false alarm.

```
Tier 1: Parallel Verification
  Entailment --> [score]
  Entropy    --> [score]    --> Combined signal vector
  Preference --> [score]
  Claims     --> [score]
                  |
                  v
Tier 2: Meta-Classifier (Fine-tuned LLM)
  Input: claim + context + domain + Tier 1 signals
  Output: risk_score, classification, reasoning, attention_cues
                  |
                  v
Conformal Prediction Calibration
  Converts risk_score into calibrated prediction sets
  Guarantees: "90% of flagged items contain actual errors"
  Mathematical coverage contracts, not heuristics
                  |
                  v
  AUTO-APPROVE (target 95%)  |  HUMAN REVIEW (target 5%)
```

### Why a meta-classifier, not just weighted averages

The current Tier 1 scoring uses static weights (entailment 40%, entropy 25%, preference 20%, claims 15%). This works for obvious cases but fails when:

- Entailment scores high but the reasoning chain is flawed
- Entropy is low (the model sounds confident) but the confidence is misplaced
- A claim is technically accurate but misleading in context
- Domain-specific patterns make a generic red flag actually benign

The meta-classifier **learns** these patterns from labeled data. It sees thousands of examples where Tier 1 scored X but the actual verdict was Y, and learns the decision boundary that static weights cannot capture.

### Conformal prediction calibration

Traditional classifiers output a point estimate: "this is 82% likely to be correct." Conformal prediction converts this into a **prediction set** with mathematical coverage guarantees:

- "With 90% confidence, this response is in the set {PASS}" -- auto-approve
- "With 90% confidence, this response is in the set {PASS, FLAG}" -- human review needed
- "With 90% confidence, this response is in the set {BLOCK}" -- auto-block

The key property: **the 90% guarantee holds regardless of the underlying data distribution.** This is not a heuristic -- it is a mathematical contract. If Meerkat says "90% of flagged items contain actual errors," that statement is provably true over any future data.

### Domain adaptation via LoRA

The meta-classifier uses a single base model (**Llama 3 8B**) with domain-specific **LoRA adapters** (Low-Rank Adaptation). Each adapter is a small set of weights (~50MB) that specializes the base model for a specific domain without modifying the base weights.

**Healthcare meta-classifier:**
- Trained on: clinical notes, EHR data, medication interaction patterns
- Learns: "Metformin in medication list + diabetes NOT in problem list = documentation gap, not hallucination"
- Training data: clinical encounters + synthetic hallucination injection

**Legal meta-classifier:**
- Trained on: contract reviews, clause analysis, jurisdictional reasoning
- Learns: "Non-compete flagged but standard in this jurisdiction = low risk" vs. "Non-compete contradicts governing law = high risk"

**Financial meta-classifier:**
- Trained on: investment analyses, risk assessments, regulatory filings
- Learns: "Revenue projection differs from SEC filing = high risk" vs. "Rounding difference in quarterly summary = low risk"

**Key insight:** Same base model. Same architecture. Different LoRA adapters per domain. Train once per domain, deploy everywhere in that domain. The adapters are the proprietary IP -- small enough to distribute, powerful enough to differentiate.

---

## 8. Federated Learning Network

### The problem with static governance

AI agents are getting smarter. GPT-5, Claude 4, and their successors will produce fewer obvious errors (wrong numbers, contradicted facts) and more subtle ones (plausible but flawed reasoning, technically correct but misleading conclusions). Static governance checks -- even good ones -- will fall behind.

Any governance system that does not learn is a depreciating asset.

### The solution: fleet-wide learning without data sharing

Every Meerkat deployment generates governance signals: what was flagged, what humans overrode, what was missed, what new attack patterns appeared. Federated learning aggregates **patterns** (model weight updates) across the entire Meerkat fleet **without sharing raw data**.

```
  Hospital A        Law Firm B        Bank C
  (Toronto)         (Vancouver)       (Calgary)
      |                 |                |
      v                 v                v
  Local Meerkat     Local Meerkat    Local Meerkat
  + Domain LoRA     + Domain LoRA    + Domain LoRA
      |                 |                |
      +--------+--------+--------+------+
               |
               v
      Federated Aggregation Server
      (weights only, never raw data)
               |
               v
      Updated Global Model Weights
               |
      +--------+--------+--------+------+
      |                 |                |
      v                 v                v
  Hospital A        Law Firm B        Bank C
  (smarter)         (smarter)         (smarter)
```

How it works:

1. A hospital in Toronto catches a new hallucination pattern in clinical notes
2. The local Meerkat instance records the pattern as a training signal
3. Federated learning encodes this pattern into **weight updates** (not raw data)
4. Weight updates are aggregated on the central server with updates from all other deployments
5. Updated global weights are pushed to every Meerkat instance
6. The law firm in Vancouver now catches the same **class** of reasoning error -- even though the domain is different

The fleet gets smarter together. Every new deployment makes every existing deployment more accurate.

### Technical details

| Parameter | Value |
|-----------|-------|
| **Aggregation method** | Federated Averaging (FedAvg) or FedProx for heterogeneous data distributions |
| **Communication** | Encrypted weight deltas only -- raw data never leaves the client's network |
| **Update cadence** | Daily signal collection, weekly model weight aggregation |
| **Privacy** | Differential privacy applied to weight updates (epsilon-delta guarantees) |
| **Rollback** | Model versioning with automated rollback if accuracy degrades post-update |
| **Cross-domain learning** | Reasoning patterns transfer across domains -- "confident but wrong" patterns are universal |

### Why this is the moat

- **Network effect:** Every customer makes the product better for every other customer
- **Data advantage:** Competitors would need equivalent fleet diversity to match accuracy
- **Compounding:** The system improves weekly. A competitor starting today is not 6 months behind -- they are permanently behind a moving target
- **Privacy-preserving:** Clients in regulated industries (healthcare, finance, legal) can participate without exposing sensitive data

---

## 9. Self-Governance

Meerkat uses its own API to govern any internal AI agents. This serves three purposes:

1. **Proof of trust** -- We use what we sell. If Meerkat governance is not good enough for our own AI operations, it is not good enough for customers.

2. **Continuous testing** -- Production traffic validates the governance engine 24/7. Every internal AI call is a live test of the system under real conditions.

3. **Transparency** -- Our own governance scores are visible. Customers can inspect how Meerkat governs itself.

### Who watches the watchmen

This is the first question any serious buyer asks. The answer is layered:

| Layer | Defense | Why it works |
|-------|---------|--------------|
| **Tier 1 checks** | Deterministic measurement instruments, not generative AI | An entailment score is a calculation, not an opinion. It cannot hallucinate. |
| **Tier 2 meta-classifier** | Validated against benchmark datasets with known ground truth | Sensitivity and specificity measured on held-out test sets. Published metrics. |
| **Conformal prediction** | Mathematical coverage guarantees | The 90% coverage contract is provably correct -- it is a theorem, not a claim. |
| **Human review layer** | Edge cases routed to domain experts | The 5% human review target ensures humans stay in the loop for ambiguous cases. |
| **Published metrics** | Sensitivity, specificity, AUROC, calibration curves | Open measurement. If governance accuracy degrades, the numbers show it. |
| **Fleet validation** | Federated network provides continuous cross-validation | Hundreds of deployments validating the same model weights across diverse domains. |

The fundamental insight: governance infrastructure does not need to be perfect. It needs to be **measurably better than the alternative** (which today is nothing). And it needs to **prove** that it is better, with numbers, not claims.

---

## 10. Training Signal Collection

The current demo API already collects the data needed for future federated learning. Every `/v1/verify` call generates a **training signal**:

```json
{
  "input_hash": "sha256_a1b2c3...",
  "domain": "legal",
  "tier1_scores": {
    "entailment": 0.92,
    "entropy": 0.15,
    "preference": 0.88,
    "claims_verified": 6,
    "claims_unverified": 1
  },
  "tier1_trust_score": 87,
  "tier2_risk_score": null,
  "human_override": null,
  "final_verdict": "PASS",
  "timestamp": "2026-02-07T14:30:00Z"
}
```

| Field | Purpose |
|-------|---------|
| `input_hash` | Privacy-preserving identifier. SHA-256 hash, not raw text. Allows deduplication without exposing content. |
| `tier1_scores` | The full Tier 1 signal vector. This becomes the feature set for Tier 2 training. |
| `tier1_trust_score` | The current weighted-average score. Useful for measuring how Tier 2 improves over Tier 1 baselines. |
| `tier2_risk_score` | Null until Tier 2 is deployed. Once active, captures the meta-classifier's output for further training. |
| `human_override` | Filled when a human reviewer changes the automated verdict. These are the highest-value training examples -- they represent cases where the system was wrong. |
| `final_verdict` | The verdict that was actually delivered (after any human override). Ground truth for training. |

These signals accumulate. When Tier 2 is deployed, this historical data becomes the training set -- the system can be bootstrapped from real governance decisions, not synthetic data alone. When federated learning is deployed, these signals feed the aggregation pipeline.

**Current storage:** In-memory dict (demo mode -- lost on restart).
**Production storage:** PostgreSQL or DynamoDB with encryption at rest. Retention policy per org.

---

## 11. Roadmap

```
Phase 1  ========================  DONE
Phase 2  ===.......................  IN PROGRESS
Phase 3  ........................   Planned
Phase 4  ........................   Planned
```

### Phase 1: Demo API (current)

- Tier 1 governance checks (deterministic/simulated)
- 5 REST endpoints: shield, verify, audit, configure, dashboard
- MCP server for Anthropic Cowork plugin integration
- Interactive frontend (login + governance dashboard)
- Training signal collection begins (in-memory)

**Status: Complete.**

### Phase 2: Production Tier 1

- Real DeBERTa entailment via ONNX-optimized inference
- Real semantic entropy via multi-sample API calls + embedding clustering
- Real claim extraction via NER-based models (T5-small fine-tuned)
- Production database (PostgreSQL / DynamoDB) for audit trail and training signals
- Azure App Service deployment with CI/CD
- Authentication via Azure AD / JWT with RBAC

**Status: In progress.**

### Phase 3: Tier 2 Meta-Classifier

- Fine-tune Llama 3 8B per domain (legal, financial, healthcare)
- LoRA adapters as domain-specific IP
- Conformal prediction calibration for coverage guarantees
- Target: 95% auto-verification rate, 95% sensitivity on true positives
- Human review workflow for the remaining 5%

**Status: Planned. Dependent on Phase 2 training signal volume.**

### Phase 4: Federated Learning Network

- Fleet-wide weight aggregation (FedAvg / FedProx)
- Cross-domain pattern transfer
- Differential privacy for weight updates
- Continuous model improvement cycle (weekly updates)
- The moat: every new deployment makes every other deployment smarter

**Status: Planned. Dependent on Phase 3 model deployment and multi-tenant fleet.**

---

## 12. Deployment Options

### Local — Docker Compose (demos & development)

```yaml
# docker-compose.yml
services:
  meerkat-api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - MEERKAT_MODE=demo
      - MEERKAT_DOMAIN=legal
      - LOG_LEVEL=debug
    volumes:
      - ./configs:/app/configs
```

```bash
docker compose up -d
# API available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

### AWS — Production Stack

```
┌─────────────────────────────────────────────────────┐
│  AWS Account (client's or Meerkat-managed)           │
│                                                      │
│  ┌──────────────┐    ┌─────────────┐                │
│  │ API Gateway   │───▶│  Lambda     │                │
│  │ (REST API)    │    │  (FastAPI)  │                │
│  └──────────────┘    └──────┬──────┘                │
│                             │                        │
│               ┌─────────────┼─────────────┐         │
│               │             │             │          │
│        ┌──────▼──────┐ ┌────▼────┐ ┌──────▼──────┐  │
│        │  DynamoDB    │ │  S3     │ │ CloudWatch  │  │
│        │ (audit logs) │ │(configs)│ │ (metrics)   │  │
│        └─────────────┘ └─────────┘ └─────────────┘  │
│                                                      │
│        ┌─────────────┐                               │
│        │ SageMaker    │  ← DeBERTa ONNX endpoint     │
│        │ (inference)  │  ← sentence-transformers      │
│        └─────────────┘                               │
└─────────────────────────────────────────────────────┘
```

Deployed via CloudFormation:
```bash
aws cloudformation deploy \
  --template meerkat-production-stack.yaml \
  --stack-name meerkat-governance \
  --parameter-overrides \
    MeerkatApiKey=mk_live_xxx \
    Domain=legal \
    AuditRetentionDays=2555 \
    EnableSageMaker=true
```

### On-Premise — Enterprise

For clients that require data sovereignty (healthcare networks, banks, government):

- Docker images delivered to client's container registry
- Helm chart for Kubernetes deployment
- All inference runs on client hardware — no data leaves their network
- Meerkat provides the software license + support; client provides infrastructure
- Audit logs stored in client's database (PostgreSQL or equivalent)

---

## 13. Security

### Authentication

```
Authorization: Bearer mk_live_{org_id}_{random_32}
                      │        │         │
                      │        │         └─ Cryptographically random
                      │        └─ Tied to a specific organization
                      └─ Environment prefix (mk_live_ or mk_test_)
```

- API keys are hashed (SHA-256) before storage — raw keys are never persisted
- Keys scoped to specific domains and check suites
- Key rotation supported without downtime (grace period for old keys)

### Rate Limiting

| Tier | Requests/min | Burst |
|------|-------------|-------|
| Starter | 60 | 10 |
| Professional | 600 | 50 |
| Enterprise | Custom | Custom |

Rate limiting is per API key, enforced at the ingress layer. Exceeded limits return `429 Too Many Requests` with `Retry-After` header.

### Data Handling

| Data | Stored? | Detail |
|------|---------|--------|
| Source documents | **No** | Never persisted. Processed in memory, discarded after verification. |
| AI model outputs | **No** | Same — in memory only. |
| User inputs | **No** | Only a SHA-256 hash is stored in the audit record. |
| Governance scores | **Yes** | Stored in the audit trail with full check results. |
| API keys | **Yes** | Hashed only — raw keys never stored. |
| Org configurations | **Yes** | Encrypted at rest (AES-256). |

### Audit Log Security

- Audit records are **append-only** — no update or delete operations exposed
- Encrypted at rest (AES-256-GCM)
- Encrypted in transit (TLS 1.3)
- Retention period configurable per org (default: 7 years for regulated industries)
- Export available in JSON and CSV for regulatory submissions

### Network

- All endpoints HTTPS-only (HTTP redirects to HTTPS)
- CORS restricted to configured origins
- No external network calls except to the configured AI model API
- Health endpoint (`/health`) is the only unauthenticated route

---

<p align="center">
  <strong>Meerkat Governance API</strong><br/>
  <em>Architecture v2.0 — February 2026</em>
</p>
