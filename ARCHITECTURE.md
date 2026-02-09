# Architecture

Technical specification for the Meerkat governance platform. Covers the deployed TRUST healthcare pipeline and the multi-domain Meerkat API.

---

## 1. System Overview

Meerkat is a verification middleware that intercepts AI-generated outputs and evaluates them against ground truth sources before delivery. The system is deployed in two forms:

**TRUST Healthcare Platform** -- currently live on Azure, purpose-built for clinical AI governance. Connects to Cerner via FHIR APIs, runs semantic entropy analysis, and surfaces results in a PowerChart-style physician dashboard.

**Meerkat API** -- the multi-domain expansion. A Node.js/TypeScript API with pluggable governance checks, backed by Python microservices for ML-intensive tasks. Supports legal, financial, and healthcare domains.

### TRUST Healthcare Pipeline

```
                                    CERNER SANDBOX
                                    (FHIR R4 API)
                                         |
                                    Patient Records
                                    Conditions, Meds,
                                    Allergies, Vitals
                                         |
                                         v
+----------------+              +------------------+
|                |              |                  |
|  AI Scribe     |    output    |  Step 1:         |
|  (GPT-4o /     | ----------> |  EHR-First       |
|   Claude)      |              |  Verification    |
|                |              |                  |
+----------------+              +--------+---------+
                                         |
                            +------------+------------+
                            |                         |
                     VERIFIED (~80%)           UNVERIFIED (~20%)
                     Low risk, skip SE         Proceed to Step 2
                            |                         |
                            |                         v
                            |            +---------------------+
                            |            |                     |
                            |            |  Step 2:            |
                            |            |  Faithfulness Check  |
                            |            |  (Claim-level NLI)   |
                            |            |                     |
                            |            +----------+----------+
                            |                       |
                            |              CONTRADICTED?
                            |              /         \
                            |           No            Yes
                            |            |             |
                            |            v             v
                            |     +------------+  +------------------+
                            |     | Step 3:    |  | CONFIDENT        |
                            |     | Semantic   |  | HALLUCINATOR     |
                            |     | Entropy    |  | (low SE + wrong) |
                            |     +------+-----+  | --> CRITICAL     |
                            |            |         +------------------+
                            |            v
                            |     Entropy Score
                            |     Low = confident
                            |     High = uncertain
                            |            |
                            +------+-----+
                                   |
                                   v
                        +--------------------+
                        |                    |
                        |  Step 4:           |
                        |  Physician         |
                        |  Dashboard         |
                        |  (PowerChart UI)   |
                        |                    |
                        |  Trust overlay     |
                        |  Tiered review     |
                        |  Time savings      |
                        |                    |
                        +--------------------+
```

### Meerkat API Pipeline

```
Client / AI Agent
        |
   API Request
   (input, output, context, domain)
        |
        v
+-------+--------+
| Authentication  |  API key (Bearer / x-meerkat-key)
| Rate Limiting   |  or JWT session cookie (MSAL)
+-------+--------+
        |
        v
+-------+----------------------------------------+
|           Governance Checks (parallel)          |
|                                                 |
|  +-------------+  +-----------------+           |
|  | Entailment  |  | Semantic        |           |
|  | (DeBERTa    |  | Entropy         |           |
|  |  NLI)       |  | (Farquhar)      |           |
|  +-------------+  +-----------------+           |
|                                                 |
|  +-------------+  +-----------------+           |
|  | Implicit    |  | Claim           |           |
|  | Preference  |  | Extraction      |           |
|  | (bias)      |  | (spaCy + NLI)   |           |
|  +-------------+  +-----------------+           |
|                                                 |
+-------------------------------------------------+
        |
  Weighted score
  (entailment 40%, entropy 25%, preference 20%, claims 15%)
        |
        v
+------------------+
| Trust Score 0-100 |
| PASS / FLAG / BLOCK |
| Audit ID         |
+------------------+
        |
        v
  PostgreSQL (audit trail)
  pgvector (knowledge base)
```

---

## 2. Verification Pipeline

### Layer 1: Ground Truth Verification

**TRUST (healthcare):** Connects to Cerner Sandbox via FHIR R4 REST API. Retrieves patient data (Condition, MedicationRequest, AllergyIntolerance, DocumentReference) and compares AI-generated claims against EMR records.

**Meerkat API (multi-domain):** Uses the entailment check. Takes the AI output and the source context provided by the caller. Runs natural language inference to determine if the output is entailed by, neutral to, or contradicts the source.

- Model: DeBERTa-v3 (NLI fine-tuned)
- Input: (premise=source context, hypothesis=AI claim)
- Output: entailment/contradiction/neutral probabilities
- Flags: `entailment_contradiction` if contradiction > 0.5, `low_entailment` if entailment < 0.5
- Score: 0.0-1.0, weighted at 40% of composite

When the microservices are not available, the Node.js API falls back to a heuristic entailment check based on token overlap between output and context.

### Layer 2: Semantic Entropy

Implements Farquhar et al. (2024) to measure model confidence:

1. **Sample N completions** (default N=5) from the AI model at temperature > 0. Each sample answers the same prompt independently.

2. **Pairwise bidirectional entailment check.** For each pair of responses (A, B), check whether A entails B AND B entails A using DeBERTa-large-MNLI. If both directions hold, the responses are semantically equivalent (they say the same thing in different words).

3. **Cluster into semantic equivalence classes** using union-find. If response 1 is equivalent to response 2, and response 2 is equivalent to response 3, then all three are in the same cluster. This is transitive closure over bidirectional entailment.

4. **Compute Shannon entropy** over the cluster distribution:

   ```
   SE = -sum(p_i * log2(p_i))  for each cluster i
   where p_i = (number of responses in cluster i) / N
   ```

5. **Normalize to 0-1** by dividing by log2(N). A score of 0 means all responses fell into a single cluster (the model is certain). A score of 1 means every response is in its own cluster (maximum uncertainty).

- Flags: `high_uncertainty` if normalized SE > 0.6, `moderate_uncertainty` if > 0.3
- Score: inverted (1 - normalized_SE) so higher = better
- Weight: 25% of composite

**Implementation:** `meerkat-semantic-entropy/` microservice (FastAPI + Python). The TRUST platform has a parallel implementation in `ml-service/app/semantic_entropy.py` that uses the Hugging Face Inference API for entailment.

### Layer 3: Claim Extraction and Verification

Three-step pipeline implemented in `meerkat-claim-extractor/`:

1. **Claim extraction** using spaCy `en_core_web_trf` (transformer-based NER). Extracts factual assertions from the AI output by identifying sentences containing named entities, quantities, dates, and other verifiable content.

2. **Claim verification** via DeBERTa entailment. Each extracted claim is checked against the source context using NLI. Claims are classified as:
   - Verified: entailment score > 0.7
   - Contradicted: contradiction score > 0.5
   - Unverified: neither threshold met

3. **Entity cross-reference** for hallucination detection. Named entities (people, organizations, locations) mentioned in the AI output are checked against entities in the source context. Entities that appear in the output but not in the source are flagged as potentially hallucinated.

- Flags: `unverified_claims`, `majority_unverified`
- Score: proportion of verified claims
- Weight: 15% of composite

### Layer 4: Implicit Preference Detection

Detects hidden directional bias in AI recommendations. Implemented in `meerkat-implicit-preference/`:

- **Sentiment analysis:** DistilBERT fine-tuned on SST-2. Measures overall sentiment polarity of the response. Strongly positive or negative sentiment in contexts that should be neutral triggers a flag.

- **Domain-specific keyword scoring:** Analyzes the response for directional language patterns specific to each domain (legal: plaintiff/defendant bias, financial: buy/sell bias, healthcare: treatment preference).

- Combined scoring: sentiment (30%), keyword direction (40%), domain context (30%).

- Flags: `strong_bias` if score < 0.4, `mild_preference` if score < 0.7
- Weight: 20% of composite
- Status: in development

---

## 3. Data Flow

### Verification Request

```
1. Client sends POST /v1/verify
   {
     input:    "What does Section 12 say about termination?",
     output:   "The contract allows termination with 90 days notice.",
     context:  "Section 12.1: Either party may terminate with 30 days written notice.",
     domain:   "legal",
     agent_name: "contract-reviewer"
   }

2. Authentication middleware validates API key or JWT session cookie.
   Sets org context (orgId, plan, domain).

3. Verification limit check (Starter plan: 1000/month).

4. Load org configuration (thresholds, required checks, knowledge base settings).

5. If knowledge base is enabled, run semantic search against org's indexed
   documents via pgvector. Append matching chunks to the verification context.

6. Run governance checks (parallel where possible):
   - entailment_check(output, context)          --> score, flags
   - semantic_entropy_check(input, output)      --> score, flags
   - implicit_preference_check(output, domain)  --> score, flags
   - claim_extraction_check(output, context)    --> score, flags, claims

7. Compute weighted trust score (0-100).
   Apply org thresholds:
     >= auto_approve_threshold (default 85) --> PASS
     >= auto_block_threshold (default 40)   --> FLAG (human review)
     < auto_block_threshold                 --> BLOCK

8. Persist verification record to PostgreSQL:
   - audit_id (unique, format: aud_YYYYMMDD_hexhash)
   - Full check results, flags, trust score, status
   - Input/output text, source context
   - Agent name, model used, domain

9. Increment org verification counter.

10. Return response:
    {
      trust_score: 32,
      status: "BLOCK",
      checks: { entailment: {...}, semantic_entropy: {...}, ... },
      audit_id: "aud_20260208_a1b2c3d4",
      recommendations: ["Review AI output against source -- contradictions detected."]
    }
```

### TRUST Healthcare Data Flow

```
1. AI Scribe generates clinical note from patient encounter.

2. TRUST backend receives the note via API.

3. EHR-first verification:
   a. Extract claims from the AI note (medications, diagnoses, vitals, procedures).
   b. Query Cerner FHIR API for patient records:
      GET /Patient/{id}
      GET /Condition?patient={id}
      GET /MedicationRequest?patient={id}
      GET /AllergyIntolerance?patient={id}
   c. Compare each claim against FHIR data.
   d. ~80% of claims verify directly against EMR. These are marked LOW risk.

4. Remaining ~20% unverified claims proceed to ML service:
   a. Semantic entropy analysis (5 samples, bidirectional entailment clustering).
   b. Cross-reference with hallucination detection matrix:

      +------------------+------------------+-------------------+
      |                  | EHR: VERIFIED    | EHR: CONTRADICTS  |
      +------------------+------------------+-------------------+
      | High Entropy     | REVIEW NEEDED    | LIKELY ERROR      |
      | (uncertain)      | (medium risk)    | (high risk)       |
      +------------------+------------------+-------------------+
      | Low Entropy      | LIKELY CORRECT   | CONFIDENT         |
      | (confident)      | (low risk)       | HALLUCINATOR      |
      |                  |                  | (critical risk)   |
      +------------------+------------------+-------------------+

5. Results surface in PowerChart dashboard:
   - Per-claim verification status (verified / contradicted / unverified)
   - Risk level badges (LOW / MEDIUM / HIGH / CRITICAL)
   - Recommended review tier (Brief / Standard / Detailed)
   - Time saved vs. manual chart review
```

---

## 4. Infrastructure

### Currently Deployed (TRUST Healthcare)

| Resource | Type | Purpose |
|----------|------|---------|
| `trust-api-phc` | Azure App Service (P1V2) | FastAPI backend |
| `trust-ml-service` | Azure App Service (P1V2) | ML microservice (entropy, hallucination) |
| `meerkat-smoke-wzrd` | Azure App Service (P1V2) | BC Wildfire governance agent |
| `jean.raubenheimer_asp_5377` | App Service Plan | Shared plan, 1 vCPU, 3.5GB RAM |
| `trust-postgres-1764041748` | PostgreSQL Flexible Server | Database: `trust_governance` |
| `trust-dashboard-swa` | Static Web App | React frontend |
| `trust-prod-kv` | Key Vault | API keys, DB credentials, tokens |

Region: Canada Central. CI/CD via GitHub Actions with path-filtered deploys. No ARM/Bicep/Terraform templates exist; deployments use Azure CLI and GitHub Actions publish profiles.

<!-- NOTE: Infrastructure-as-Code is planned but not yet implemented.
     Current deployments are configured via Azure Portal and GitHub Actions. -->

### Meerkat API (Development)

The Node.js API runs locally against a PostgreSQL instance with pgvector. The three Python microservices each run as standalone FastAPI servers. Docker support exists for the Python demo API and microservices (`Dockerfile` per service, `docker-compose.yml` at root).

Production deployment target: Azure App Service or Azure Container Apps. Not yet deployed.

### Database Schema (Meerkat API)

PostgreSQL with pgvector extension. Key models:

- **Organization** -- multi-tenant org with plan (starter/professional/enterprise), domain, Stripe billing fields
- **User** -- Azure AD users with `microsoft_oid`, linked to org
- **ApiKey** -- SHA-256 hashed keys with prefix, status, last-used tracking
- **Configuration** -- per-org governance rules (thresholds, required checks, knowledge base settings)
- **Verification** -- audit trail for every verification (trust score, status, full check results, flags)
- **ThreatLog** -- prompt injection / jailbreak attempts
- **KnowledgeBase / Document / Chunk** -- RAG system with `vector(1536)` embeddings for semantic search

---

## 5. Security and Compliance

### Authentication

**API key auth:** Keys use the format `mk_{env}_{random}` (e.g., `mk_live_a1b2c3...`). Keys are SHA-256 hashed before storage. Raw keys are never persisted. Transmitted via `Authorization: Bearer` header or `x-meerkat-key` header.

**Microsoft SSO:** Azure AD authentication via MSAL `ConfidentialClientApplication`. OAuth2 authorization code flow. JWT session tokens stored in httpOnly, secure, sameSite=strict cookies. 8-hour session expiry.

**Dual auth middleware:** Each request is authenticated via API key first, then JWT cookie. API key auth is intended for programmatic access (AI agents, CI/CD). JWT auth is intended for browser-based users (dashboard, admin).

### FHIR API Authentication

The TRUST platform currently uses the Cerner Open Sandbox, which provides unauthenticated read access to synthetic patient data. Production FHIR integration will require:

- OAuth2 SMART on FHIR authorization
- Client credentials flow for backend services
- Scoped access tokens per patient/resource type
- Token refresh and session management

### Data Handling

| Data Type | Stored | Detail |
|-----------|--------|--------|
| AI outputs | Yes | Stored in verification records for audit trail |
| Source context | Yes | Stored alongside verification for reproducibility |
| User inputs | Yes | Stored in verification records |
| Trust scores | Yes | Stored with full check breakdown |
| API keys | Yes | SHA-256 hash only, raw key never persisted |
| Patient data (FHIR) | No | Retrieved at verification time, processed in memory, not persisted |
| Knowledge base docs | Yes | Stored as chunked text with vector embeddings |

### HIPAA Considerations

The TRUST healthcare deployment handles synthetic patient data (Cerner Sandbox). For production clinical deployment:

- Patient data from FHIR APIs is processed in memory and not persisted in Meerkat's database
- Verification records store the AI output and trust scores but can be configured to exclude raw clinical text
- All data at rest encrypted (Azure PostgreSQL TDE, Key Vault for secrets)
- All data in transit over TLS
- Access logging via Azure AD and API key audit trails
- Audit records are append-only with configurable retention
- BAA (Business Associate Agreement) required with Azure for production HIPAA workloads

### Rate Limiting

Per-plan rate limiting enforced at the middleware layer:

| Plan | Requests/minute |
|------|----------------|
| Starter | 60 |
| Professional | 300 |
| Enterprise | 1000 |

Starter plan also enforces a monthly verification cap (1000 verifications/month). Exceeding the cap returns HTTP 429.

---

Meerkat Governance Platform -- Architecture v3.0, February 2026
