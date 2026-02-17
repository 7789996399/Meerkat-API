"""
Meerkat Numerical Verification Service

Regex-based extraction and comparison of numerical values between
source context and AI output. Catches the category of hallucinations
that NLI models like DeBERTa miss: numerical distortions.

Endpoints:
  POST /verify  -- Compare numbers in AI output against source
  GET  /health  -- Health check
"""

import logging
import time

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .extractor import extract_numbers
from .comparator import match_and_compare

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Meerkat Numerical Verification",
    description="Detects numerical distortions in AI output via regex extraction and comparison",
    version="1.0.0",
)


# ── Request / Response models ──────────────────────────────────────

class VerifyRequest(BaseModel):
    ai_output: str = Field(description="The AI-generated text to verify")
    source_context: str = Field(description="The source/ground truth text")
    domain: str = Field(
        default="healthcare",
        description="Domain for tolerance rules: healthcare, pharma, legal, financial",
    )


class MatchDetail(BaseModel):
    source_value: float
    source_raw: str
    ai_value: float
    ai_raw: str
    context: str
    context_type: str
    match: bool
    deviation: float
    tolerance: float
    severity: str
    detail: str


class UngroundedNumber(BaseModel):
    value: float
    raw: str
    context: str
    context_type: str


class VerifyResponse(BaseModel):
    score: float = Field(description="0.0 (all wrong) to 1.0 (all correct)")
    status: str = Field(description="pass | fail | warning")
    numbers_found_in_source: int
    numbers_found_in_ai: int
    matches: list[MatchDetail]
    ungrounded_numbers: list[UngroundedNumber]
    critical_mismatches: int
    detail: str
    inference_time_ms: float


# ── Health ─────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "meerkat-numerical-verify",
        "version": "1.0.0",
    }


# ── Verify endpoint ───────────────────────────────────────────────

@app.post("/verify", response_model=VerifyResponse)
async def verify(req: VerifyRequest):
    start = time.monotonic()

    # Step 1: Extract numbers from both texts
    source_numbers = extract_numbers(req.source_context)
    ai_numbers = extract_numbers(req.ai_output)

    logger.info(
        "Extracted %d numbers from source, %d from AI output (domain=%s)",
        len(source_numbers), len(ai_numbers), req.domain,
    )

    # Step 2: Match and compare
    result = match_and_compare(source_numbers, ai_numbers, req.domain)

    elapsed_ms = (time.monotonic() - start) * 1000

    logger.info(
        "Result: score=%.3f, status=%s, %d matches (%d critical), %d ungrounded, %.1fms",
        result.score, result.status, len(result.matches),
        result.critical_mismatches, len(result.ungrounded), elapsed_ms,
    )

    return VerifyResponse(
        score=result.score,
        status=result.status,
        numbers_found_in_source=result.numbers_in_source,
        numbers_found_in_ai=result.numbers_in_ai,
        matches=[
            MatchDetail(
                source_value=m.source.value,
                source_raw=m.source.raw,
                ai_value=m.ai.value,
                ai_raw=m.ai.raw,
                context=m.ai.context[:80],
                context_type=m.ai.context_type,
                match=m.match,
                deviation=m.deviation,
                tolerance=m.tolerance,
                severity=m.severity,
                detail=m.detail,
            )
            for m in result.matches
        ],
        ungrounded_numbers=[
            UngroundedNumber(
                value=u.value,
                raw=u.raw,
                context=u.context[:80],
                context_type=u.context_type,
            )
            for u in result.ungrounded
        ],
        critical_mismatches=result.critical_mismatches,
        detail=result.detail,
        inference_time_ms=round(elapsed_ms, 1),
    )
