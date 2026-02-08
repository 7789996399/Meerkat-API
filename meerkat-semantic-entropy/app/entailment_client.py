import asyncio
import logging
import time

import aiohttp

logger = logging.getLogger(__name__)

BATCH_SIZE = 20  # max concurrent entailment requests


async def check_entailment(
    session: aiohttp.ClientSession,
    entailment_url: str,
    premise: str,
    hypothesis: str,
) -> float:
    """Call the DeBERTa entailment service and return the entailment score."""
    payload = {"premise": premise, "hypothesis": hypothesis}
    async with session.post(entailment_url, json=payload) as resp:
        resp.raise_for_status()
        data = await resp.json()
        # The entailment service returns {"entailment": float, "contradiction": float, "neutral": float}
        return float(data["entailment"])


async def batch_entailment_checks(
    entailment_url: str,
    pairs: list[tuple[int, int, str, str]],
) -> tuple[dict[tuple[int, int], float], int, float]:
    """
    Run entailment checks for all (i, j, premise, hypothesis) pairs.
    Returns (results_dict, total_calls, elapsed_ms).
    results_dict maps (i, j) -> entailment_score.
    """
    results: dict[tuple[int, int], float] = {}
    total_calls = len(pairs)
    start = time.monotonic()

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=120),
    ) as session:
        # Process in batches to avoid overwhelming the entailment service
        for batch_start in range(0, len(pairs), BATCH_SIZE):
            batch = pairs[batch_start : batch_start + BATCH_SIZE]
            tasks = []
            for i, j, premise, hypothesis in batch:
                tasks.append(_check_one(session, entailment_url, i, j, premise, hypothesis))
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in batch_results:
                if isinstance(result, Exception):
                    logger.error("Entailment call failed: %s", result)
                else:
                    key, score = result
                    results[key] = score

    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info(
        "Entailment batch complete: %d calls in %.1f ms (%.1f ms/call)",
        total_calls, elapsed_ms, elapsed_ms / max(total_calls, 1),
    )
    return results, total_calls, elapsed_ms


async def _check_one(
    session: aiohttp.ClientSession,
    url: str,
    i: int,
    j: int,
    premise: str,
    hypothesis: str,
) -> tuple[tuple[int, int], float]:
    score = await check_entailment(session, url, premise, hypothesis)
    return (i, j), score
