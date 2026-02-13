"""
meerkat-claim-extractor: Extracts and verifies factual claims from AI outputs.

Three-step pipeline:
1. Claim extraction (spaCy en_core_web_trf)
2. Claim verification (DeBERTa entailment service)
3. Entity cross-reference (hallucination detection)
"""

from fastapi import FastAPI
from app.models import ExtractRequest, ExtractResponse, ClaimDetail
from app.extractor import extract_claims
from app.verifier import verify_claims
from app.entities import find_hallucinated_entities

app = FastAPI(title="meerkat-claim-extractor", version="0.1.0")


@app.post("/extract", response_model=ExtractResponse)
async def extract(req: ExtractRequest):
    # Step 1: Extract claims from AI output
    claims = extract_claims(req.ai_output)

    # Step 2: Verify claims against source context via entailment
    claims = await verify_claims(claims, req.source, req.entailment_url)

    # Step 3: Entity cross-reference for hallucination detection
    all_hallucinated = find_hallucinated_entities(req.ai_output, req.source)
    hallucinated_set = {e.lower() for e in all_hallucinated}

    # Annotate each claim with its hallucinated entities
    for claim in claims:
        claim["hallucinated_entities"] = [
            e for e in claim.get("entities", [])
            if e.lower() in hallucinated_set
        ]

    # Build response
    verified = sum(1 for c in claims if c["status"] == "verified")
    contradicted = sum(1 for c in claims if c["status"] == "contradicted")
    unverified = sum(1 for c in claims if c["status"] == "unverified")

    flags: list[str] = []
    if contradicted > 0:
        flags.append("contradicted_claims")
    if unverified > len(claims) * 0.5 and len(claims) > 0:
        flags.append("majority_unverified")
    if len(all_hallucinated) > 0:
        flags.append("hallucinated_entities")
    if len(all_hallucinated) > 3:
        flags.append("many_hallucinated_entities")
    if len(claims) == 0 and len(req.ai_output.split()) > 20:
        flags.append("no_claims_extracted")

    claim_details = [
        ClaimDetail(
            claim_id=i + 1,
            text=c["text"],
            source_sentence=c["source_sentence"],
            status=c["status"],
            entailment_score=c.get("entailment_score", 0.0),
            entities=c.get("entities", []),
            hallucinated_entities=c.get("hallucinated_entities", []),
        )
        for i, c in enumerate(claims)
    ]

    return ExtractResponse(
        total_claims=len(claims),
        verified=verified,
        contradicted=contradicted,
        unverified=unverified,
        claims=claim_details,
        hallucinated_entities=all_hallucinated,
        flags=flags,
    )


@app.get("/health")
async def health():
    return {"status": "healthy"}
