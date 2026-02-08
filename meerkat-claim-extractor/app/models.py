from pydantic import BaseModel


class ExtractRequest(BaseModel):
    ai_output: str
    source_context: str = ""
    entailment_url: str = ""


class ClaimDetail(BaseModel):
    claim_id: int
    text: str
    source_sentence: str
    status: str  # "verified" | "contradicted" | "unverified"
    entailment_score: float
    entities: list[str]
    hallucinated_entities: list[str]


class ExtractResponse(BaseModel):
    total_claims: int
    verified: int
    contradicted: int
    unverified: int
    claims: list[ClaimDetail]
    hallucinated_entities: list[str]
    flags: list[str]
