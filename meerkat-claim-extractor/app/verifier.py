"""
Claim verification via DeBERTa entailment service.

For each claim, sends (premise=source_context, hypothesis=claim) to the
entailment service and classifies:
  - entailment > 0.7: VERIFIED
  - contradiction > 0.5: CONTRADICTED
  - otherwise: UNVERIFIED
"""

import asyncio
import aiohttp


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
        # No context or no entailment service -- mark all unverified
        for claim in claims:
            claim["status"] = "unverified"
            claim["entailment_score"] = 0.0
        return claims

    # Run entailment checks concurrently in batches
    batch_size = 10
    for i in range(0, len(claims), batch_size):
        batch = claims[i : i + batch_size]
        await asyncio.gather(
            *[_verify_single(claim, source_context, entailment_url) for claim in batch]
        )

    return claims


async def _verify_single(
    claim: dict,
    source_context: str,
    entailment_url: str,
) -> None:
    """Verify a single claim via the entailment service."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                entailment_url,
                json={
                    "premise": source_context,
                    "hypothesis": claim["text"],
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

    except Exception:
        claim["status"] = "unverified"
        claim["entailment_score"] = 0.0
