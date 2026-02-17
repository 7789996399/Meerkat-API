"""
Claim verification via DeBERTa entailment service.

For each claim, sends (premise=source_context, hypothesis=claim) to the
entailment service and classifies:
  - entailment > 0.7: VERIFIED
  - contradiction > 0.5: CONTRADICTED
  - otherwise: UNVERIFIED

Clinical improvements:
  - Chunks source context to fit DeBERTa's 512-token limit
  - Expands clinical abbreviations for better NLI inference
  - Selects the most relevant chunk per claim
"""

import asyncio
import logging

import aiohttp

from .clinical_preprocessing import (
    expand_abbreviations,
    chunk_context,
    find_relevant_chunk,
)

logger = logging.getLogger(__name__)


async def verify_claims(
    claims: list[dict],
    source_context: str,
    entailment_url: str,
) -> list[dict]:
    """
    Verify each claim against the source context using entailment.

    Mutates each claim dict in-place, adding:
      - status: "verified" | "contradicted" | "unverified"
      - entailment_score: float

    Returns the same list.
    """
    if not source_context.strip() or not entailment_url:
        for claim in claims:
            claim["status"] = "unverified"
            claim["entailment_score"] = 0.0
        return claims

    # Preprocess: expand abbreviations for better NLI
    expanded_context = expand_abbreviations(source_context)

    # Chunk context for DeBERTa 512-token limit
    chunks = chunk_context(expanded_context, max_tokens=380, overlap_tokens=60)
    logger.info("Source context chunked into %d pieces for entailment", len(chunks))

    # Run entailment checks concurrently in batches
    batch_size = 10
    for i in range(0, len(claims), batch_size):
        batch = claims[i : i + batch_size]
        await asyncio.gather(
            *[_verify_single(claim, chunks, entailment_url) for claim in batch]
        )

    return claims


async def _verify_single(
    claim: dict,
    context_chunks: list[str],
    entailment_url: str,
) -> None:
    """Verify a single claim via the entailment service."""
    try:
        # Expand abbreviations in the claim too
        claim_text = expand_abbreviations(claim["text"])

        # Find the most relevant context chunk for this claim
        relevant_chunk = find_relevant_chunk(context_chunks, claim_text)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                entailment_url,
                json={
                    "premise": relevant_chunk,
                    "hypothesis": claim_text,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    claim["status"] = "unverified"
                    claim["entailment_score"] = 0.0
                    return

                data = await resp.json()
                entailment = data.get("entailment", 0.0)
                contradiction = data.get("contradiction", 0.0)

                claim["entailment_score"] = round(entailment, 4)

                if entailment > 0.7:
                    claim["status"] = "verified"
                elif contradiction > 0.5:
                    claim["status"] = "contradicted"
                else:
                    claim["status"] = "unverified"

    except Exception as e:
        logger.warning("Entailment check failed for claim: %s", e)
        claim["status"] = "unverified"
        claim["entailment_score"] = 0.0
