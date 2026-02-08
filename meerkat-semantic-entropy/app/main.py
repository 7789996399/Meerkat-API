"""
Meerkat Semantic Entropy Service

Implements the semantic entropy method from Farquhar et al. (2024, Nature)
for detecting confabulation / hallucination in LLM outputs.

The method:
1. Takes N sampled completions for the same prompt
2. Clusters them by bidirectional entailment (semantic equivalence)
3. Computes Shannon entropy over the cluster distribution
4. High entropy = model is uncertain / confabulating
"""

import logging

from fastapi import FastAPI, HTTPException

from .entailment_client import batch_entailment_checks
from .entropy import compute_semantic_entropy, interpret_entropy
from .models import AnalyzeRequest, AnalyzeResponse
from .union_find import UnionFind

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Meerkat Semantic Entropy",
    description="Detects LLM confabulation via semantic entropy (Farquhar et al. 2024)",
    version="1.0.0",
)

ENTAILMENT_THRESHOLD = 0.5


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "meerkat-semantic-entropy", "version": "1.0.0"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    completions = req.sampled_completions
    n = len(completions)

    if n < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 sampled completions")

    logger.info(
        "Analyzing %d completions + reference answer (question: %.60s...)",
        n, req.question,
    )

    # --- Build all pairwise entailment check pairs ---
    # For each pair (i, j) where i < j, we need both directions:
    #   forward:  premise=completions[i], hypothesis=completions[j]
    #   backward: premise=completions[j], hypothesis=completions[i]
    pairs: list[tuple[int, int, str, str]] = []
    for i in range(n):
        for j in range(i + 1, n):
            pairs.append((i, j, completions[i], completions[j]))  # forward
            pairs.append((j, i, completions[j], completions[i]))  # backward

    logger.info("Dispatching %d entailment calls for %d completion pairs", len(pairs), n * (n - 1) // 2)

    # --- Run entailment checks ---
    entailment_scores, total_calls, elapsed_ms = await batch_entailment_checks(
        req.entailment_url, pairs,
    )

    # --- Bidirectional entailment clustering ---
    uf = UnionFind(n)

    for i in range(n):
        for j in range(i + 1, n):
            fwd = entailment_scores.get((i, j), 0.0)
            bwd = entailment_scores.get((j, i), 0.0)
            # Bidirectional: BOTH directions must show entailment
            if fwd > ENTAILMENT_THRESHOLD and bwd > ENTAILMENT_THRESHOLD:
                uf.union(i, j)

    cluster_groups = uf.clusters()

    # --- Compute entropy ---
    raw_entropy, normalized_entropy, cluster_infos = compute_semantic_entropy(
        cluster_groups, completions, n,
    )

    interpretation = interpret_entropy(normalized_entropy)

    logger.info(
        "Result: SE=%.3f (normalized=%.3f), %d clusters, interpretation=%s",
        raw_entropy, normalized_entropy, len(cluster_infos), interpretation,
    )

    # --- Determine which cluster the reference answer belongs to ---
    # Check the reference against all completions using entailment
    ref_pairs: list[tuple[int, int, str, str]] = []
    for i in range(n):
        ref_pairs.append((-1, i, req.reference_answer, completions[i]))  # ref -> completion
        ref_pairs.append((i, -1, completions[i], req.reference_answer))  # completion -> ref

    ref_scores, ref_calls, ref_elapsed = await batch_entailment_checks(
        req.entailment_url, ref_pairs,
    )
    total_calls += ref_calls
    elapsed_ms += ref_elapsed

    # Find which completion the reference is bidirectionally entailed with
    reference_cluster = -1
    for i in range(n):
        fwd = ref_scores.get((-1, i), 0.0)
        bwd = ref_scores.get((i, -1), 0.0)
        if fwd > ENTAILMENT_THRESHOLD and bwd > ENTAILMENT_THRESHOLD:
            # Reference matches completion i -- find its cluster
            root = uf.find(i)
            for ci in cluster_infos:
                if i in ci.members:
                    reference_cluster = ci.cluster_id
                    break
            break

    # Is the reference in the majority (largest) cluster?
    largest_cluster = max(cluster_infos, key=lambda c: c.size)
    reference_in_majority = reference_cluster == largest_cluster.cluster_id and reference_cluster != -1

    return AnalyzeResponse(
        semantic_entropy=round(normalized_entropy, 4),
        num_clusters=len(cluster_infos),
        num_completions=n,
        clusters=cluster_infos,
        interpretation=interpretation,
        reference_answer_cluster=reference_cluster,
        reference_in_majority=reference_in_majority,
        entailment_calls=total_calls,
        inference_time_ms=round(elapsed_ms, 1),
    )
