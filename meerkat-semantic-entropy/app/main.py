"""
Meerkat Semantic Entropy Service

Full pipeline following Farquhar et al. (Nature, 2024):
1. Generate N completions via local Ollama (temperature=1.0)
2. Cluster by bidirectional entailment (DeBERTa-large-MNLI, loaded locally)
3. Compute Shannon entropy over the cluster distribution
4. Check whether the original AI output aligns with the majority cluster

High entropy  = model is uncertain / likely confabulating
Low entropy   = model is confident / answers converge
"""

import asyncio
import logging
import os
import time

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .entailment_client import bidirectional_entailment, load_model
from .entropy import compute_semantic_entropy, interpret_entropy
from .models import AnalyzeRequest, AnalyzeResponse
from .union_find import UnionFind

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

app = FastAPI(
    title="Meerkat Semantic Entropy",
    description="Detects LLM confabulation via semantic entropy (Farquhar et al. 2024)",
    version="2.0.0",
)


@app.on_event("startup")
async def startup():
    """Pre-load DeBERTa model so first request isn't slow."""
    logger.info("Pre-loading entailment model...")
    await asyncio.to_thread(load_model)
    logger.info("Entailment model ready")


# ── Health ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "meerkat-semantic-entropy",
        "version": "2.0.0",
        "ollama_url": OLLAMA_BASE_URL,
        "ollama_model": OLLAMA_MODEL,
    }


# ── NLI Predict (used by claim-extractor and entailment checks) ───

class PredictRequest(BaseModel):
    premise: str
    hypothesis: str

class PredictResponse(BaseModel):
    entailment: float
    contradiction: float
    neutral: float
    label: str

@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    """
    Run NLI inference on a premise-hypothesis pair.
    Returns probabilities for entailment, contradiction, neutral.
    
    This is the endpoint that the claim-extractor microservice
    calls to verify individual claims against source context.
    """
    from .entailment_client import load_model
    nli = load_model()
    
    try:
        # DeBERTa-large-MNLI returns labels + scores
        # We need to get all three class probabilities
        results = await asyncio.to_thread(
            nli,
            f"{req.premise} [SEP] {req.hypothesis}",
            truncation=True,
            max_length=512,
            top_k=None,  # Return all labels with scores
        )
        
        # results is a list of dicts: [{"label": "ENTAILMENT", "score": 0.9}, ...]
        scores = {"ENTAILMENT": 0.0, "CONTRADICTION": 0.0, "NEUTRAL": 0.0}
        top_label = "NEUTRAL"
        top_score = 0.0
        
        for r in results:
            label = r["label"].upper()
            if label in scores:
                scores[label] = round(r["score"], 4)
                if r["score"] > top_score:
                    top_score = r["score"]
                    top_label = label
        
        return PredictResponse(
            entailment=scores["ENTAILMENT"],
            contradiction=scores["CONTRADICTION"],
            neutral=scores["NEUTRAL"],
            label=top_label,
        )
    except Exception as e:
        logger.error("NLI predict failed: %s", e)
        return PredictResponse(
            entailment=0.33, contradiction=0.33, neutral=0.34, label="NEUTRAL"
        )


# ── Ollama generation ──────────────────────────────────────────────

async def _generate_completions(
    question: str,
    source_context: str | None,
    n: int,
) -> list[str]:
    """Generate n completions from Ollama at temperature=1.0."""
    if source_context:
        prompt = (
            f"Based on the following context, answer the question.\n\n"
            f"Context: {source_context}\n\n"
            f"Question: {question}\n\n"
            f"Provide a direct, concise answer."
        )
    else:
        prompt = (
            f"Answer the following question directly and concisely.\n\n"
            f"Question: {question}"
        )

    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 1.0},
    }

    completions: list[str] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        tasks = [client.post(url, json=payload) for _ in range(n)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    for i, resp in enumerate(responses):
        if isinstance(resp, Exception):
            logger.error("Ollama generation %d failed: %s", i, resp)
            continue
        if resp.status_code != 200:
            logger.error("Ollama generation %d returned %d: %s", i, resp.status_code, resp.text)
            continue
        data = resp.json()
        content = data.get("message", {}).get("content", "").strip()
        if content:
            completions.append(content)

    return completions


# ── Entailment clustering (CPU-bound, runs in thread) ─────────────

def _cluster_completions(completions: list[str]) -> tuple[UnionFind, dict[int, list[int]]]:
    """Cluster completions using bidirectional entailment + union-find."""
    n = len(completions)
    uf = UnionFind(n)

    for i in range(n):
        for j in range(i + 1, n):
            if bidirectional_entailment(completions[i], completions[j]):
                uf.union(i, j)

    return uf, uf.clusters()


def _find_ai_output_cluster(
    ai_output: str,
    completions: list[str],
    uf: UnionFind,
    cluster_infos: list,
) -> tuple[int, bool]:
    """Check which cluster the original AI output belongs to."""
    for i, comp in enumerate(completions):
        if bidirectional_entailment(ai_output, comp):
            # Found a match -- return its cluster
            for ci in cluster_infos:
                if i in ci.members:
                    largest = max(cluster_infos, key=lambda c: c.size)
                    return ci.cluster_id, ci.cluster_id == largest.cluster_id
            break

    return -1, False


# ── Main endpoint ─────────────────────────────────────────────────

@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    start = time.monotonic()

    # Step 1: Generate completions via Ollama
    logger.info(
        "Generating %d completions via Ollama (%s) for question: %.80s...",
        req.num_completions, OLLAMA_MODEL, req.question,
    )
    completions = await _generate_completions(
        req.question, req.source_context, req.num_completions,
    )

    if len(completions) < 2:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Ollama returned only {len(completions)} completion(s) (need >= 2). "
                f"Is Ollama running at {OLLAMA_BASE_URL} with model {OLLAMA_MODEL}?"
            ),
        )

    logger.info("Got %d completions, clustering by entailment...", len(completions))

    # Step 2: Cluster by bidirectional entailment (CPU-bound, offload to thread)
    uf, cluster_groups = await asyncio.to_thread(_cluster_completions, completions)

    # Step 3: Compute Shannon entropy over clusters
    raw_entropy, normalized_entropy, cluster_infos = compute_semantic_entropy(
        cluster_groups, completions, len(completions),
    )
    interpretation = interpret_entropy(normalized_entropy)

    # Step 4: Check which cluster the original AI output belongs to
    ai_cluster, in_majority = await asyncio.to_thread(
        _find_ai_output_cluster, req.ai_output, completions, uf, cluster_infos,
    )

    elapsed_ms = (time.monotonic() - start) * 1000

    logger.info(
        "Result: SE=%.3f (norm=%.3f), %d clusters from %d completions, "
        "ai_output_cluster=%d, interpretation=%s, %.0fms",
        raw_entropy, normalized_entropy, len(cluster_infos),
        len(completions), ai_cluster, interpretation, elapsed_ms,
    )

    return AnalyzeResponse(
        semantic_entropy=round(normalized_entropy, 4),
        raw_entropy=round(raw_entropy, 4),
        num_clusters=len(cluster_infos),
        num_completions=len(completions),
        clusters=cluster_infos,
        interpretation=interpretation,
        ai_output_cluster=ai_cluster,
        ai_output_in_majority=in_majority,
        completions=completions,
        inference_time_ms=round(elapsed_ms, 1),
    )
