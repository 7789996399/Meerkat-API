"""
Mock DeBERTa entailment service for testing.
Returns high entailment for similar texts, low for different ones.
Uses simple word-overlap heuristic.
"""

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class EntailmentRequest(BaseModel):
    premise: str
    hypothesis: str


@app.post("/predict")
async def predict(req: EntailmentRequest):
    # Simple word-overlap heuristic for testing
    p_words = set(req.premise.lower().split())
    h_words = set(req.hypothesis.lower().split())
    if not h_words:
        return {"entailment": 0.5, "contradiction": 0.2, "neutral": 0.3}
    overlap = len(p_words & h_words) / len(h_words)
    entailment = min(1.0, overlap * 1.2)
    return {
        "entailment": round(entailment, 4),
        "contradiction": round(max(0, 1 - entailment - 0.2), 4),
        "neutral": 0.2,
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
