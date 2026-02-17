# Meerkat API -- Day 1 Audit Report
## Repository Health Check: What Works, What Doesn't, What's Missing

**Date:** February 17, 2026
**Repo:** github.com/7789996399/Meerkat-API (main branch, commit 0a2d2e4)

---

## EXECUTIVE SUMMARY

The repo has real, substantial code -- not stubs. But the core verification pipeline (governance-checks.ts) is running on **heuristic fallbacks**, not real ML models. The Python microservices have real model code (DeBERTa, spaCy, DistilBERT) but the Node.js API that orchestrates them uses word-overlap and keyword-counting as fallbacks, and those fallbacks are what runs when the microservices aren't up. The numerical verification module (Check 5) does not exist in the repo yet.

**Bottom line:** The architecture is sound. The plumbing is built. But the engine is running on placeholders. This week we replace placeholders with real engines and test with real data.

---

## SERVICE INVENTORY

| Service | Directory | Port | Status |
|---------|-----------|------|--------|
| Node.js API (Express + Prisma) | src/ | 3000 | Code complete. Not deployed. |
| Python FastAPI gateway | api/ | 8000 | Code complete. Demo routes. |
| Semantic Entropy | meerkat-semantic-entropy/ | 8001 | Real DeBERTa + Ollama. Needs Ollama running. |
| Claim Extractor | meerkat-claim-extractor/ | 8002 | Real spaCy. Entailment via DeBERTa on :8001. |
| Implicit Preference | meerkat-implicit-preference/ | 8003 | Real DistilBERT sentiment. Direction scoring. Counterfactual is a stub. |
| Numerical Verification | **DOES NOT EXIST** | 8004 | Spec in ADDENDUM-V2. No code yet. |
| PostgreSQL + pgvector | docker-compose | 5432 | Config exists. Never tested with full schema. |
| Redis | docker-compose | 6379 | Config exists. Used for job queue. |

---

## CRITICAL FINDINGS

### 1. governance-checks.ts is heuristic-only for entailment

The `entailment_check()` function in `src/services/governance-checks.ts` does NOT call any microservice. It runs a word-overlap heuristic locally:

```
const overlapRatio = overlap / Math.max(outputWords.size, 1);
let score = Math.min(overlapRatio * 2.5, 1.0) + rand(-0.15, 0.15);
```

This is the function that was tested against MedHallu and performed poorly. It counts how many words in the AI output also appear in the source context. This would give a high score to "The patient has cancer" if the source mentions "patient" and "cancer" anywhere, even if the source says the patient does NOT have cancer.

**Fix:** Wire this to call the claim-extractor microservice's DeBERTa entailment endpoint, like semantic_entropy_check and implicit_preference_check already do.

### 2. Semantic entropy uses mock completions

`semantic_entropy_check()` in governance-checks.ts calls the real microservice BUT sends it `generateMockCompletions()` -- randomly shuffled words from the original output, not real LLM completions. The microservice itself is properly designed to call Ollama for real completions, but the Node API bypasses that by pre-generating fake ones.

**Fix:** Let the semantic entropy microservice generate its own completions via Ollama (which it's already coded to do). Remove the mock completion generation from governance-checks.ts.

### 3. Numerical verification module is missing entirely

The spec in MEERKAT-PROJECT-STATUS-ADDENDUM-V2.md describes the full architecture: extractor.py, comparator.py, normalizer.py, domain_rules.py. None of this exists in the repo. Port 8004 is unassigned.

**Fix:** Build it. This is Day 2 of our plan.

### 4. Trust score weights are outdated

verify.ts uses the OLD weights:
```
entailment: 0.40, semantic_entropy: 0.25, implicit_preference: 0.20, claim_extraction: 0.15
```

The ADDENDUM-V2 specifies the NEW weights (5 checks):
```
entailment: 0.30, numerical_verify: 0.20, semantic_entropy: 0.20, implicit_preference: 0.15, claim_extraction: 0.15
```

### 5. No .env file -- service URLs not configured

The .env.example only has 3 variables. The governance-checks.ts reads from:
- `MEERKAT_SEMANTIC_ENTROPY_URL` (empty string default)
- `MEERKAT_IMPLICIT_PREFERENCE_URL` (empty string default)  
- `MEERKAT_CLAIM_EXTRACTOR_URL` (empty string default)

When these are empty, every check falls back to heuristics. The docker-compose.yml sets `ENTROPY_SERVICE_URL`, `CLAIMS_SERVICE_URL`, `PREFERENCE_SERVICE_URL` -- but governance-checks.ts reads DIFFERENT env var names. **The env vars don't match.**

### 6. Database schema needs numerical_verify fields

The Verification model in schema.prisma stores checksResults as Json, so it will accept the new check. But the Configuration model's requiredChecks and the ALL_CHECKS array in verify.ts don't include "numerical_verify".

### 7. No automated tests exist

Zero test files in the entire repo. No test framework configured (no jest, no vitest, no mocha in package.json).

---

## WHAT ACTUALLY WORKS RIGHT NOW

1. **Docker containers build** -- Dockerfiles for all services are present and syntactically correct
2. **Prisma schema is complete** -- migrations exist, seed data exists
3. **Express routes are complete** -- verify, shield, audit, configure, dashboard, billing, auth, knowledge-base, health
4. **Python microservice code is real** -- DeBERTa loaded in entailment_client.py, spaCy en_core_web_trf in extractor.py, DistilBERT in sentiment.py
5. **MCP server works** -- both SSE and stdio transports
6. **Stripe billing code is complete** -- checkout, portal, usage tracking, webhook handler
7. **Knowledge base pipeline is complete** -- upload, chunk, embed, semantic search

---

## PRIORITY FIX ORDER FOR THIS WEEK

| Priority | Task | Blocks |
|----------|------|--------|
| P0 | Fix env var mismatch so Node API actually calls Python microservices | Everything |
| P1 | Build numerical verification module (meerkat-numerical-verify) | Pipeline completeness |
| P2 | Wire entailment_check to use real DeBERTa (not word overlap) | Detection accuracy |
| P3 | Remove mock completions from semantic entropy flow | Detection accuracy |
| P4 | Update weights and ALL_CHECKS in verify.ts for 5-check pipeline | Correct scoring |
| P5 | Integration test with real clinical data (MIMIC-III / your examples) | Validation |
| P6 | Deploy to Azure | Production readiness |
| P7 | Connect frontend to live API | Demo readiness |

---

## ENV VAR MISMATCH DETAIL

docker-compose.yml sets:
```
ENTROPY_SERVICE_URL: http://meerkat-entropy:8001
CLAIMS_SERVICE_URL: http://meerkat-claims:8002
PREFERENCE_SERVICE_URL: http://meerkat-preference:8003
```

governance-checks.ts reads:
```
process.env.MEERKAT_SEMANTIC_ENTROPY_URL
process.env.MEERKAT_IMPLICIT_PREFERENCE_URL
process.env.MEERKAT_CLAIM_EXTRACTOR_URL
```

These are completely different names. The microservices will be running but the Node API won't know they exist.

---

## NEXT STEP

Fix the env var mismatch (P0), then build the numerical verification module (P1). Both can be done today.
