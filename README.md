# Meerkat

AI governance for regulated industries -- real-time verification of AI agent outputs.

---

## What Meerkat Does

Meerkat sits between AI models and end users in regulated environments. It intercepts AI-generated outputs -- clinical notes, contract analysis, financial recommendations -- and verifies them against ground truth sources before they reach the user. Every output receives a trust score based on multiple independent governance checks. Every decision is logged for compliance and audit.

---

## Live Demo -- TRUST Healthcare Platform

The TRUST (Trustworthy, Reliable, Understandable, Safe, Transparent) platform is the current production deployment of Meerkat for healthcare. This is the live system deployed on Azure.

### Pipeline

**Step 1 -- Ground Truth / EMR Check**

Connects to the Cerner Sandbox via FHIR R4 APIs. Retrieves patient records (conditions, medications, allergies, vitals) as the authoritative source of truth. AI Scribe output is decomposed into individual claims, and each claim is compared against actual EMR data. The system uses an EHR-first verification strategy: claims that match EMR records are marked as verified immediately, and only unverified or contradicted claims proceed to further checks. This saves approximately 80% of downstream compute.

- FHIR endpoint: Cerner Open Sandbox (R4)
- Resources accessed: Patient, Condition, MedicationRequest, AllergyIntolerance, DocumentReference

**Step 2 -- Faithfulness Check**

<!-- NOTE: The codebase implements faithfulness checking via EHR-first claim verification
     and semantic entropy analysis (ml-service/app/hallucination.py), not the specific
     Vectara HHEM model. The approach achieves the same goal -- scoring whether AI-generated
     content is faithful to source data -- using bidirectional entailment rather than HHEM. -->

Scores whether the AI-generated clinical note is faithful to the source EMR data. Uses the hallucination detection module in the ML service, which cross-references extracted claims against FHIR-retrieved patient records. Binary classification per claim: faithful vs. hallucinated content. The system specifically targets "confident hallucinators" -- cases where the AI model is highly certain but factually wrong, which are the most dangerous in clinical settings.

**Step 3 -- Semantic Entropy (Farquhar et al. 2024)**

Implements the semantic entropy method from Farquhar et al., published in Nature (2024):

1. Samples multiple completions (N=5) from the AI model at temperature > 0
2. Clusters responses using bidirectional entailment -- two responses are semantically equivalent if A entails B AND B entails A
3. Calculates Shannon entropy over the resulting semantic clusters
4. Low entropy = model is confident and consistent across samples. High entropy = model is uncertain, possible confabulation.

Entailment classification uses DeBERTa-large-MNLI via the Hugging Face Inference API.

**Step 4 -- Physician Dashboard**

PowerChart-style frontend built for clinical workflow. Displays AI Scribe output with a trust overlay showing which sections are verified, which are flagged, and the overall trust score. Supports three review tiers:

- Brief review (15 sec): Low-risk output, confirmation only
- Standard review (2-3 min): Medium-risk, check key claims
- Detailed review (5+ min): High or critical risk, full manual verification

Includes a time-saved calculator comparing automated verification against manual chart review.

### Stack

| Component | Technology |
|-----------|-----------|
| Backend API | FastAPI (Python 3.11) on Azure App Service |
| ML Service | FastAPI (Python 3.11) on Azure App Service |
| Frontend | React 18 on Azure Static Web Apps |
| Database | Azure PostgreSQL Flexible Server |
| FHIR Integration | Cerner Open Sandbox (R4) via fhir.resources |
| Entailment Model | DeBERTa-large-MNLI via Hugging Face Inference API |
| LLM Sampling | OpenAI GPT-4o-mini, Anthropic Claude 3 Haiku |
| Secrets | Azure Key Vault |
| CI/CD | GitHub Actions (path-filtered deploys) |
| Hosting Plan | Azure App Service Plan P1V2 (Canada Central) |
| Auth | Azure AD via MSAL |

---

## Architecture Overview

Meerkat uses a multi-layer verification pipeline. Each AI output passes through independent governance checks before reaching the end user. The checks run in parallel where possible and produce a weighted composite trust score.

```
AI Agent Output
      |
      v
+------------------+     +---------------------+     +--------------------+
| Ground Truth     |     | Semantic Entropy    |     | Claim Extraction   |
| (FHIR / source)  |     | (Farquhar et al.)   |     | (NER + entailment) |
+------------------+     +---------------------+     +--------------------+
      |                         |                           |
      v                         v                           v
+------------------------------------------------------------------+
|                    Weighted Trust Score                           |
|                    Status: PASS / FLAG / BLOCK                   |
+------------------------------------------------------------------+
      |
      v
  Audit Trail (immutable)
      |
      v
  End User / Dashboard
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the complete technical specification.

---

## Governance Checks

| Check | Description |
|-------|-------------|
| Ground truth verification | Compare AI output against authoritative source data -- EMR records, contract text, regulatory filings |
| Faithfulness scoring | Detect hallucinated content that deviates from source, with emphasis on confident hallucinators |
| Semantic entropy | Measure model confidence using bidirectional entailment clustering (Farquhar et al., Nature 2024) |
| Implicit preference detection | Identify hidden directional bias in AI recommendations [in development] |

---

## Repository Structure

```
.
├── src/                                # Node.js API (Express + Prisma + TypeScript)
│   ├── server.ts                       # Express app entry point
│   ├── lib/prisma.ts                   # Prisma client singleton
│   ├── middleware/
│   │   ├── auth.ts                     # Dual auth: API key or JWT cookie (MSAL)
│   │   └── rateLimit.ts                # Per-plan rate limiting
│   ├── routes/
│   │   ├── index.ts                    # Route registry
│   │   ├── verify.ts                   # POST /v1/verify -- output verification
│   │   ├── shield.ts                   # POST /v1/shield -- prompt injection scan
│   │   ├── audit.ts                    # GET /v1/audit/:id -- audit trail
│   │   ├── configure.ts               # POST /v1/configure -- org config
│   │   ├── dashboard.ts               # GET /v1/dashboard -- metrics
│   │   ├── knowledge-base.ts          # Knowledge base CRUD + upload
│   │   ├── billing.ts                 # Stripe checkout, portal, usage
│   │   ├── billing-webhook.ts         # Stripe webhook handler
│   │   └── auth.ts                    # Microsoft SSO endpoints
│   ├── services/
│   │   ├── governance-checks.ts       # Four governance check implementations
│   │   ├── prompt-shield.ts           # Prompt injection / jailbreak detection
│   │   ├── billing.ts                 # Stripe integration + plan management
│   │   ├── auth.ts                    # MSAL + JWT session management
│   │   ├── semantic-search.ts         # pgvector similarity search
│   │   ├── chunker.ts                 # Document chunking for knowledge base
│   │   ├── embeddings.ts              # OpenAI embedding client
│   │   └── job-queue.ts               # Background job processing
│   └── mcp/
│       ├── server.ts                  # MCP server with 3 tools
│       ├── route.ts                   # SSE transport for Express
│       └── index.ts                   # Standalone stdio transport
│
├── meerkat-semantic-entropy/           # Python microservice -- Farquhar method
│   ├── app/
│   │   ├── main.py                    # FastAPI: POST /analyze
│   │   ├── entropy.py                 # Shannon entropy over semantic clusters
│   │   ├── entailment_client.py       # Bidirectional NLI via DeBERTa
│   │   └── union_find.py              # Union-find for equivalence classes
│   ├── Dockerfile
│   └── requirements.txt
│
├── meerkat-claim-extractor/            # Python microservice -- claim verification
│   ├── app/
│   │   ├── main.py                    # FastAPI: POST /extract
│   │   ├── extractor.py               # spaCy NER-based claim extraction
│   │   ├── verifier.py                # DeBERTa entailment verification
│   │   └── entities.py                # Hallucinated entity detection
│   ├── Dockerfile
│   └── requirements.txt
│
├── meerkat-implicit-preference/        # Python microservice -- bias detection
│   ├── app/
│   │   ├── main.py                    # FastAPI: POST /analyze
│   │   ├── sentiment.py               # DistilBERT SST-2 sentiment analysis
│   │   ├── direction.py               # Domain-specific keyword bias scoring
│   │   └── counterfactual.py          # Counterfactual comparison stub
│   ├── Dockerfile
│   └── requirements.txt
│
├── api/                                # Python demo API (original prototype)
│   ├── main.py                        # FastAPI app with simulated checks
│   ├── governance/                    # Heuristic-based governance checks
│   ├── models/schemas.py             # Pydantic request/response models
│   ├── routes/                        # REST endpoints
│   └── store.py                       # In-memory audit storage
│
├── frontend/                           # Demo frontend
│   ├── login.html                     # Microsoft SSO login page
│   ├── dashboard.html                 # Interactive governance dashboard
│   └── dashboard/MeerkatAPI.jsx       # React dashboard component
│
├── mcp/                                # Python MCP server (FastMCP)
│   ├── meerkat_mcp_server.py
│   └── test_mcp.py
│
├── prisma/
│   ├── schema.prisma                  # Database schema (PostgreSQL + pgvector)
│   ├── migrations/                    # Migration history
│   └── seed.ts                        # Demo data seeding
│
├── docker-compose.yml                  # Local development compose
├── Dockerfile                          # Python demo API container
├── package.json                        # Node.js dependencies
├── requirements.txt                    # Python demo dependencies
├── tsconfig.json                       # TypeScript configuration
└── mcp-client-config.sample.json       # MCP client config example
```

---

## Getting Started

### Prerequisites

- Node.js 20+
- PostgreSQL 14+ with pgvector extension
- Python 3.11+ (for microservices)

### Environment Variables

Create a `.env` file in the project root:

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/meerkat_api

# Microsoft SSO (optional -- API key auth works without this)
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_TENANT_ID=
MICROSOFT_REDIRECT_URI=http://localhost:3000/auth/microsoft/callback
JWT_SECRET=your-secret-here

# Stripe billing (optional)
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=

# Microservice URLs (optional -- falls back to heuristic checks)
MEERKAT_SEMANTIC_ENTROPY_URL=http://localhost:8001
MEERKAT_IMPLICIT_PREFERENCE_URL=http://localhost:8002
MEERKAT_CLAIM_EXTRACTOR_URL=http://localhost:8003

# Embeddings (optional -- for knowledge base)
OPENAI_API_KEY=
```

### Run Locally

```bash
# Install dependencies
npm install

# Set up database
npx prisma db push
npx prisma db seed

# Start the API
npx tsx src/server.ts
# API available at http://localhost:3000
```

### Run with Microservices

```bash
# Terminal 1: Node.js API
npx tsx src/server.ts

# Terminal 2: Semantic entropy service
cd meerkat-semantic-entropy && pip install -r requirements.txt
uvicorn app.main:app --port 8001

# Terminal 3: Claim extractor
cd meerkat-claim-extractor && pip install -r requirements.txt
python -m spacy download en_core_web_trf
uvicorn app.main:app --port 8003
```

### Verify an AI Output

```bash
curl -X POST http://localhost:3000/v1/verify \
  -H "x-meerkat-key: mk_demo_test123" \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Summarize this contract clause.",
    "output": "The contract includes a 90-day termination clause.",
    "context": "Section 12.1: Either party may terminate with 30 days written notice.",
    "domain": "legal"
  }'
```

---

## API Endpoints

### Governance

| Method | Endpoint | Description | Status |
|--------|----------|-------------|--------|
| `POST` | `/v1/verify` | Verify AI output against source context. Returns trust score, status (PASS/FLAG/BLOCK), per-check results, and audit ID. | Working |
| `POST` | `/v1/shield` | Scan input for prompt injection, jailbreak attempts, and policy violations. | Working |
| `GET` | `/v1/audit/:auditId` | Retrieve immutable audit record for a past verification. | Working |
| `POST` | `/v1/configure` | Set org-level governance rules: thresholds, required checks, domain config. | Working |
| `GET` | `/v1/dashboard` | Aggregated governance metrics: total verifications, avg trust score, flag distribution. | Working |

### Knowledge Base

| Method | Endpoint | Description | Status |
|--------|----------|-------------|--------|
| `POST` | `/v1/knowledge-base/upload` | Upload PDF, DOCX, or TXT documents. Auto-chunks and indexes for semantic search. | Working |
| `GET` | `/v1/knowledge-base` | List knowledge bases and documents for the org. | Working |
| `GET` | `/v1/knowledge-base/:documentId` | Document detail with chunk preview. | Working |

### Billing

| Method | Endpoint | Description | Status |
|--------|----------|-------------|--------|
| `POST` | `/v1/billing/checkout` | Create Stripe Checkout session for Professional plan. | Working |
| `POST` | `/v1/billing/portal` | Create Stripe Customer Portal session. | Working |
| `GET` | `/v1/billing/usage` | Current plan, verification count, billing period. | Working |
| `POST` | `/v1/billing/webhook` | Stripe webhook handler (checkout, invoice, subscription events). | Working |

### Authentication

| Method | Endpoint | Description | Status |
|--------|----------|-------------|--------|
| `GET` | `/auth/microsoft` | Redirect to Microsoft login (Azure AD). | Working |
| `GET` | `/auth/microsoft/callback` | OAuth callback, sets JWT session cookie. | Working |
| `GET` | `/auth/me` | Current user profile from session. | Working |
| `POST` | `/auth/logout` | Clear session cookie. | Working |

### MCP Server

| Transport | Endpoint | Description | Status |
|-----------|----------|-------------|--------|
| SSE | `/mcp` | MCP server with tools: `meerkat_verify`, `meerkat_shield`, `meerkat_audit` | Working |
| stdio | `npx tsx src/mcp/index.ts` | Standalone MCP server for local IDE integration | Working |

### System

| Method | Endpoint | Description | Status |
|--------|----------|-------------|--------|
| `GET` | `/v1/health` | Health check (unauthenticated). | Working |

---

## Research Foundation

- Farquhar, S., Kossen, J., Kuhn, L., & Gal, Y. (2024). Detecting hallucinations in large language models using semantic entropy. *Nature*, 630, 625--630. https://doi.org/10.1038/s41586-024-07421-0

  The semantic entropy method is implemented in `meerkat-semantic-entropy/` and in the TRUST ML service. The core insight: sampling multiple completions and clustering by bidirectional entailment reveals model uncertainty that single-response confidence scores miss.

- Hughes, A. et al. HHEM -- Hughes Hallucination Evaluation Model (Vectara). Used as a reference for faithfulness scoring methodology. The TRUST platform implements faithfulness checking via EHR-first claim verification with DeBERTa-based entailment.

- He, P., Liu, X., Gao, J., & Chen, W. (2021). DeBERTa: Decoding-enhanced BERT with disentangled attention. *ICLR 2021*. DeBERTa-v3-large-MNLI is used for natural language inference across the entailment and claim verification checks.

---

## Roadmap

**Done** -- TRUST Healthcare Platform
- Live on Azure with Cerner Sandbox FHIR integration
- Semantic entropy (Farquhar et al.) for hallucination detection
- EHR-first verification pipeline (80% compute savings)
- PowerChart-style physician dashboard with tiered review
- Validated on MedHallu benchmark

**Next** -- Meerkat API (multi-domain expansion)
- Node.js/TypeScript API with four governance checks (working, in this repo)
- MCP server integration for Anthropic Cowork plugins (working)
- Knowledge base with semantic search via pgvector (working)
- Microsoft SSO with dual auth (working)
- Self-service onboarding and org management

**Future**
- Stripe billing in production (code complete, not yet live)
- Enterprise deployment options (on-premise, dedicated infrastructure)
- Tier 2 metacognitive engine (domain-specific LoRA adapters)
- Multi-agent team governance (agent-level, handoff-level, assembly-level)

---

Built by Jean and CL -- Vancouver, BC
