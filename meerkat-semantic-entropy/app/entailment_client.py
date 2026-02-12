"""
Local bidirectional entailment using DeBERTa-large-MNLI.
Following Farquhar et al. (Nature, 2024).

Replaces the previous HTTP-based client -- the model now runs inside
this microservice so there is no external dependency for entailment.
"""

import logging

from transformers import pipeline

logger = logging.getLogger(__name__)

_nli_pipeline = None


def load_model():
    """Pre-load the NLI model. Call at startup to avoid cold-start latency."""
    global _nli_pipeline
    if _nli_pipeline is None:
        logger.info("Loading microsoft/deberta-large-mnli ...")
        _nli_pipeline = pipeline(
            "text-classification",
            model="microsoft/deberta-large-mnli",
            device=-1,  # CPU
        )
        logger.info("DeBERTa-large-MNLI loaded")
    return _nli_pipeline


def check_entailment(premise: str, hypothesis: str) -> str:
    """
    Check NLI relation between premise and hypothesis.
    Returns 'ENTAILMENT', 'NEUTRAL', or 'CONTRADICTION'.
    """
    nli = load_model()
    try:
        result = nli(
            f"{premise} [SEP] {hypothesis}",
            truncation=True,
            max_length=512,
        )
        return result[0]["label"]
    except Exception as e:
        logger.error("Entailment check failed: %s", e)
        return "NEUTRAL"


def bidirectional_entailment(text_a: str, text_b: str) -> bool:
    """
    True if A entails B AND B entails A (semantic equivalence).
    This is the core criterion from Farquhar et al. for clustering.
    """
    return (
        check_entailment(text_a, text_b) == "ENTAILMENT"
        and check_entailment(text_b, text_a) == "ENTAILMENT"
    )
