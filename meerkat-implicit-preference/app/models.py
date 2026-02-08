from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    output: str
    domain: str = "general"
    context: str = ""


class SentimentDetail(BaseModel):
    label: str
    positive_score: float
    negative_score: float


class DirectionDetail(BaseModel):
    direction: str
    party_a: str
    party_b: str
    party_a_score: float
    party_b_score: float
    keywords_found: list[str]


class CounterfactualDetail(BaseModel):
    note: str


class AnalysisDetails(BaseModel):
    sentiment: SentimentDetail
    direction: DirectionDetail
    counterfactual: CounterfactualDetail


class AnalyzeResponse(BaseModel):
    score: float
    bias_detected: bool
    direction: str
    party_a: str
    party_b: str
    details: AnalysisDetails
    flags: list[str]
