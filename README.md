<p align="center">
  <img src="https://img.shields.io/badge/status-alpha-orange?style=for-the-badge" alt="Status: Alpha"/>
  <img src="https://img.shields.io/badge/python-3.11+-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+"/>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker"/>
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="License: MIT"/>
</p>

<h1 align="center">Meerkat API</h1>
<h3 align="center">The Governance Layer for the AI Agent Era</h3>

<p align="center">
  <strong>One API. Any AI model. Every regulated industry.</strong>
</p>

<p align="center">
  As AI agents take over business logic -- reviewing contracts, analyzing<br/>
  financials, writing clinical notes -- the question is not whether to use them.<br/>
  It is who watches the agents.<br/><br/>
  Meerkat is the trust infrastructure that sits between AI agents and the<br/>
  systems they operate on. Every request scanned. Every response verified.<br/>
  Every decision audited.
</p>

---

## The Problem

Microsoft CEO Satya Nadella declared **"SaaS is dead"** -- business logic is moving out of software applications and into AI agents. The per-seat dashboard is being replaced by autonomous agents that talk directly to systems via APIs.

This is already happening. Anthropic launched legal, financial, and healthcare plugins for Cowork -- with **160K+ installs for legal alone**. These AI agents are reviewing contracts overnight, analyzing portfolios at scale, and writing clinical notes in real time. They are not assistants waiting for instructions. They are autonomous workers executing business logic.

But ask yourself:

- **Who verifies the agent's output?** A hallucinated contract clause could cost millions.
- **Who catches the bias?** A skewed financial recommendation could trigger regulatory action.
- **Who creates the audit trail?** Regulators do not accept "the AI said so."

The AI providers secure the plumbing -- authentication, rate limits, model access. But nobody governs the agents' actual decisions.

**In the old world, humans checked the work. In the agent era, you need infrastructure that checks the agents.**

That infrastructure is Meerkat.

Every prompt. Every response. Every claim. Scored, logged, and auditable.

---

## How It Works

```
+-----------+     +-----------------+     +--------------+     +-----------------+     +----------+
|           |     |                 |     |              |     |                 |     |          |
| AI Agent  |---->|  Meerkat Shield |---->|   AI Model   |---->|  Meerkat Verify |---->| Verified |
| Request   |     |  (scan input)   |     |  (Claude /   |     | (check output)  |     | Response |
|           |     |                 |     |  GPT / etc.) |     |                 |     |          |
+-----------+     +-----------------+     +--------------+     +-----------------+     +----------+
                        |                                            |
                        v                                            v
                 Prompt injection?                          Governance Score
                 Jailbreak attempt?                         +-- Entailment pass/fail
                 Policy violation?                          +-- Confidence level
                                                            +-- Bias detected?
                                                            +-- Claims verified?
                                                            |
                                                            v
                                                   +-----------------+
                                                   |   Audit Trail   |
                                                   |  (immutable)    |
                                                   +-----------------+
```

---

## Live Demo

Meerkat ships with a fully interactive frontend -- login page + governance dashboard.

```
+-----------------+      +------------------+      +-----------------------------+
|                 |      |                  |      |                             |
|  Login Page     |----->|  Microsoft SSO   |----->|  Governance Dashboard       |
|  (login.html)   |      |  (Azure AD)      |      |  (React app -- 5 tabs)      |
|                 |      |                  |      |                             |
+-----------------+      +------------------+      +-----------------------------+
```

The **login page** (`frontend/login.html`) is the front door -- a polished dark-themed SSO page with the full MEERKAT logo and Microsoft sign-in. In demo mode, it redirects straight to the dashboard.

The **dashboard** (`frontend/dashboard.html`) is an interactive React app that serves as both documentation and live demo, with 5 tabs:

| Tab | What It Shows |
|-----|---------------|
| **The Big Idea** | The agent-era thesis -- why autonomous AI needs governance infrastructure |
| **How It Works** | Interactive 6-step flow from agent request to verified response |
| **API Endpoints** | Full request/response examples for all 5 endpoints |
| **Integrations** | MCP, API proxy, AWS, and FHIR integration paths |
| **Business Model** | Consumption-based pricing and revenue projections |

> **Try it locally:**
> ```bash
> # Start the API (serves frontend automatically)
> uvicorn api.main:app --port 8000
> # Visit http://localhost:8000/login
> ```

---

## Core API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/shield` | **Prompt injection detection** -- Pre-flight scan of agent input for jailbreaks, prompt attacks, and policy violations |
| `POST` | `/v1/verify` | **Real-time output verification** -- Entailment checking, semantic entropy, bias detection, and claim extraction on AI responses |
| `GET` | `/v1/audit/{id}` | **Compliance audit trail** -- Immutable, timestamped record of every governance decision for regulatory review |
| `POST` | `/v1/configure` | **Domain and org configuration** -- Set industry-specific rules, thresholds, and compliance policies per organization |
| `GET` | `/v1/dashboard` | **Governance metrics** -- Aggregated view of shield blocks, verification scores, flagged responses, and system health |

---

## MCP Integration

Connect Meerkat to any Anthropic Cowork plugin with one config block:

```json
{
  "mcp_servers": {
    "meerkat-governance": {
      "command": "python",
      "args": ["path/to/meerkat_mcp_server.py"],
      "env": {
        "MEERKAT_API_URL": "http://localhost:8000",
        "MEERKAT_API_KEY": "mk_demo_test123"
      }
    }
  }
}
```

This gives the agent access to four governance tools: `meerkat_shield` (pre-flight input scan), `meerkat_verify` (post-flight output verification), `meerkat_audit` (compliance trail), and `meerkat_configure` (org rules). See [mcp/README.md](mcp/README.md) for full setup instructions and examples.

---

## Integration Paths

#### MCP Server -- Cowork plugin integration (see above)
```bash
# Add the config block above, then use your plugin as normal.
# Claude automatically shields input and verifies output.
```

#### API Proxy -- Change 1 URL to route agent traffic through Meerkat
```python
# Before
client = Anthropic(base_url="https://api.anthropic.com")

# After -- all agent traffic now governed
client = Anthropic(base_url="https://your-instance.meerkat.ai/proxy")
```

#### AWS Middleware -- One-click CloudFormation deploy
```bash
aws cloudformation deploy --template meerkat-stack.yaml --stack-name meerkat-gov
```

#### FHIR Bridge -- Healthcare EMR integration
```yaml
# meerkat.config.yaml
domain: healthcare
fhir_endpoint: https://ehr.hospital.org/fhir/R4
governance_level: strict
```

---

## Governance Checks

Every AI agent response is evaluated across four dimensions:

| Check | What It Does | Why It Matters |
|-------|-------------|----------------|
| **DeBERTa Entailment** | Compares the agent's answer against source documents using NLI | Catches hallucinations -- does the response actually follow from the evidence? |
| **Semantic Entropy** | Measures model uncertainty across multiple sampled completions | Flags low-confidence answers before they reach downstream systems |
| **Implicit Preference** | Detects hidden directional bias in language and recommendations | Ensures the agent is not steering users toward undisclosed preferences |
| **Claim Extraction** | Identifies factual assertions and checks verifiability | Every claim is tagged -- verified, unverified, or contradicted |

---

## Quick Start

#### Install
```bash
pip install -r requirements.txt
```

#### Or run with Docker
```bash
docker compose up
```

#### Verify an AI agent response in 5 lines
```python
import requests

result = requests.post("http://localhost:8000/v1/verify", json={
    "input": "Review this NDA for risks.",
    "output": "The contract includes a 90-day termination clause.",
    "context": "Section 12.1: Either party may terminate with 30 days written notice.",
    "domain": "legal"
}).json()

print(result["trust_score"])   # 32 -- BLOCK (hallucination detected)
print(result["status"])        # "BLOCK"
```

---

## Pricing

Consumption-based pricing aligned with the agent era -- you pay for governance work done, not seats occupied.

| Tier | Price | Model | Best For |
|------|-------|-------|----------|
| **Starter** | $0.002 per verification | Pay-per-use, no commitment | Solo practitioners, small firms testing the waters |
| **Professional** | $499/mo per agent monitored | Flat rate per AI agent under governance, unlimited verifications | Mid-size firms, hospital departments, financial advisory teams |
| **Enterprise** | Custom fleet pricing | Per-agent-fleet pricing for organizations running multiple agents across domains | Hospital networks, large law firms, banks, insurance companies |

Starter includes: entailment checking, semantic entropy, basic audit trail, 1 domain.
Professional adds: all 4 governance checks, prompt injection shield, dashboard, priority support.
Enterprise adds: on-premise deploy, custom domain configs, SOC 2 / HIPAA / FINRA compliance, SLA guarantee.

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

## Project Status

```
Phase 1  ========================  DONE -- Demo API with governance engine
Phase 2  ........................  Real DeBERTa entailment integration
Phase 3  ========================  DONE -- MCP server for Cowork plugins
Phase 4  ........................  Production deployment on AWS
```

| Phase | Milestone | Status |
|-------|-----------|--------|
| **1** | Demo API with governance engine (4 checks, weighted scoring) | **Done** |
| **2** | Real DeBERTa entailment + semantic entropy models | Planned |
| **3** | MCP server for Anthropic Cowork plugins | **Done** |
| **4** | Production deployment on AWS with full audit persistence | Planned |

---

<p align="center">
  <strong>Built by Jean and CL -- Vancouver, BC</strong><br/>
  <em>Always watching. Always verifying. Always trustworthy.</em>
</p>
