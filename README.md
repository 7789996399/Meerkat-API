<p align="center">
  <img src="https://img.shields.io/badge/status-alpha-orange?style=for-the-badge" alt="Status: Alpha"/>
  <img src="https://img.shields.io/badge/python-3.11+-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+"/>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker"/>
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="License: MIT"/>
</p>

<h1 align="center">Meerkat API</h1>
<h3 align="center">AI Governance as a Service</h3>

<p align="center">
  <strong>One API. Any AI model. Every regulated industry.</strong>
</p>

<p align="center">
  Think of Meerkat as <b>airport security for AI</b>.<br/>
  Every request and every response passes through a checkpoint —<br/>
  scanned for hallucinations, bias, prompt attacks, and compliance violations —<br/>
  before anything reaches the end user.
</p>

---

## The Problem

Anthropic just launched legal, financial, and healthcare plugins for Cowork — with **160K+ installs for legal alone**. These AI agents are already reviewing contracts, analyzing financials, and writing clinical notes in production.

But ask yourself:

- **Who verifies the AI's output?** A hallucinated contract clause could cost millions.
- **Who catches the bias?** A skewed financial recommendation could trigger regulatory action.
- **Who creates the audit trail?** Regulators don't accept "the AI said so."

The AI providers secure the plumbing — authentication, rate limits, model access.

**Meerkat governs the _use_.**

Every prompt. Every response. Every claim. Scored, logged, and auditable.

---

## How It Works

```
┌──────────┐     ┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌──────────┐
│          │     │                 │     │              │     │                 │     │          │
│   User   │────▶│  Meerkat Shield │────▶│   AI Model   │────▶│  Meerkat Verify │────▶│   User   │
│ Request  │     │  (scan input)   │     │  (Claude /   │     │ (check output)  │     │ Response │
│          │     │                 │     │  GPT / etc.) │     │                 │     │          │
└──────────┘     └─────────────────┘     └──────────────┘     └─────────────────┘     └──────────┘
                        │                                            │
                        ▼                                            ▼
                 Prompt injection?                          Governance Score
                 Jailbreak attempt?                         ├─ Entailment pass/fail
                 Policy violation?                          ├─ Confidence level
                                                            ├─ Bias detected?
                                                            ├─ Claims verified?
                                                            │
                                                            ▼
                                                   ┌─────────────────┐
                                                   │   Audit Trail   │
                                                   │  (immutable)    │
                                                   └─────────────────┘
```

---

## Live Demo

**Meerkat ships with a fully interactive frontend — login page + governance dashboard.**

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────────────────┐
│                 │      │                  │      │                             │
│  Login Page     │─────▶│  Microsoft SSO   │─────▶│  Governance Dashboard       │
│  (login.html)   │      │  (Azure AD)      │      │  (React app — 5 tabs)       │
│                 │      │                  │      │                             │
└─────────────────┘      └──────────────────┘      └─────────────────────────────┘
```

The **login page** (`frontend/login.html`) is the front door — a polished dark-themed SSO page with the full MEERKAT logo and Microsoft sign-in. In demo mode, it redirects straight to the dashboard.

The **dashboard** (`frontend/dashboard/`) is an interactive React app that serves as both documentation and live demo, with 5 tabs:

| Tab | What It Shows |
|-----|---------------|
| **The Big Idea** | The airport security analogy — why governance matters |
| **How It Works** | Interactive 6-step flow from user request to verified response |
| **API Endpoints** | Full request/response examples for all 5 endpoints |
| **Integrations** | MCP, API proxy, AWS, and FHIR integration paths |
| **Business Model** | Pricing tiers and revenue projections |

<p align="center">
  <em>[ Screenshot placeholder — login.html → dashboard flow ]</em>
</p>

> **Try it locally:**
> ```bash
> # Serve the login page
> cd frontend && python -m http.server 3000
> # Visit http://localhost:3000/login.html
> ```

---

## Core API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/shield` | **Prompt injection detection** — Pre-flight scan of user input for jailbreaks, prompt attacks, and policy violations |
| `POST` | `/v1/verify` | **Real-time output verification** — Entailment checking, semantic entropy, bias detection, and claim extraction on AI responses |
| `GET` | `/v1/audit/{id}` | **Compliance audit trail** — Immutable, timestamped record of every governance decision for regulatory review |
| `POST` | `/v1/configure` | **Domain & org configuration** — Set industry-specific rules, thresholds, and compliance policies per organization |
| `GET` | `/v1/dashboard` | **Governance metrics** — Live view of shield blocks, verification scores, flagged responses, and system health |

---

## Integration Paths

#### MCP Server — 1 config line for any Anthropic Cowork plugin
```json
{
  "mcpServers": {
    "meerkat": { "url": "https://your-instance.meerkat.ai/mcp" }
  }
}
```

#### API Proxy — Change 1 URL to route through Meerkat
```python
# Before
client = Anthropic(base_url="https://api.anthropic.com")

# After — all traffic now governed
client = Anthropic(base_url="https://your-instance.meerkat.ai/proxy")
```

#### AWS Middleware — One-click CloudFormation deploy
```bash
aws cloudformation deploy --template meerkat-stack.yaml --stack-name meerkat-gov
```

#### FHIR Bridge — Healthcare EMR integration
```yaml
# meerkat.config.yaml
domain: healthcare
fhir_endpoint: https://ehr.hospital.org/fhir/R4
governance_level: strict
```

---

## Governance Checks

What makes Meerkat unique — every AI response is evaluated across four dimensions:

| Check | What It Does | Why It Matters |
|-------|-------------|----------------|
| **DeBERTa Entailment** | Compares the AI's answer against source documents using NLI | Catches hallucinations — does the response actually follow from the evidence? |
| **Semantic Entropy** | Measures model uncertainty across multiple sampled completions | Flags low-confidence answers before they reach end users |
| **Implicit Preference** | Detects hidden directional bias in language and recommendations | Ensures the AI isn't steering users toward undisclosed preferences |
| **Claim Extraction** | Identifies factual assertions and checks verifiability | Every claim is tagged — verified, unverified, or contradicted |

---

## Quick Start

#### Install
```bash
pip install meerkat-gov
```

#### Or run with Docker
```bash
docker run -p 8000:8000 meerkatai/governance:latest
```

#### Verify an AI response in 5 lines
```python
import requests

result = requests.post("http://localhost:8000/v1/verify", json={
    "model_output": "The contract includes a 90-day termination clause.",
    "source_document": "Section 12.1: Either party may terminate with 30 days written notice.",
    "domain": "legal"
}).json()

print(result["governance_score"])   # 0.23 — LOW (hallucination detected)
print(result["flags"])              # ["entailment_contradiction", "claim_mismatch"]
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | **FastAPI** with async request handling |
| Data Validation | **Pydantic v2** for strict schema enforcement |
| Entailment Engine | **DeBERTa-v3** via ONNX Runtime (fast inference, no GPU required) |
| Containerization | **Docker** with multi-stage builds |
| AI Integration | **MCP Protocol** for native Anthropic plugin support |
| Deployment | **Azure App Service** / **AWS CloudFormation** |

---

## Project Status: Alpha — Demo Available

```
Phase 1  ███████████████████░░░░░░  NOW — Demo API with simulated governance
Phase 2  ░░░░░░░░░░░░░░░░░░░░░░░░  Real DeBERTa entailment integration
Phase 3  ░░░░░░░░░░░░░░░░░░░░░░░░  MCP server for Anthropic plugins
Phase 4  ░░░░░░░░░░░░░░░░░░░░░░░░  Production deployment on AWS
```

| Phase | Milestone | Status |
|-------|-----------|--------|
| **1** | Demo API with simulated governance scores | **In Progress** |
| **2** | Real DeBERTa entailment + semantic entropy | Planned |
| **3** | MCP server for Anthropic Cowork plugins | Planned |
| **4** | Production deployment on AWS with full audit | Planned |

---

<p align="center">
  <strong>Built by Jean & CL — Vancouver, BC</strong><br/>
  <em>Always watching. Always verifying. Always trustworthy.</em>
</p>
