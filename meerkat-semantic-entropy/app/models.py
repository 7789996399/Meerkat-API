from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    question: str = Field(description="The original user input / prompt")
    reference_answer: str = Field(description="The AI output being evaluated")
    sampled_completions: list[str] = Field(
        min_length=2,
        description="N sampled responses from the model at temperature > 0",
    )
    entailment_url: str = Field(
        description="URL of the DeBERTa entailment service (e.g. http://localhost:8001/predict)"
    )


class ClusterInfo(BaseModel):
    cluster_id: int
    size: int
    representative: str = Field(description="Shortest completion in the cluster")
    members: list[int] = Field(description="Indices of completions in this cluster")


class AnalyzeResponse(BaseModel):
    semantic_entropy: float = Field(
        ge=0.0, le=1.0,
        description="Normalized entropy: 0.0 = certain, 1.0 = maximum uncertainty",
    )
    num_clusters: int
    num_completions: int
    clusters: list[ClusterInfo]
    interpretation: str
    reference_answer_cluster: int = Field(
        description="Cluster index the reference answer belongs to, or -1 if no match"
    )
    reference_in_majority: bool = Field(
        description="Whether the reference answer is in the largest cluster"
    )
    entailment_calls: int = Field(description="Total DeBERTa calls made")
    inference_time_ms: float = Field(description="Total wall-clock time for entailment calls")
