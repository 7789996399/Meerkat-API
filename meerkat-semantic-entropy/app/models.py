from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    question: str = Field(description="The original user prompt / question")
    ai_output: str = Field(description="The AI-generated output to verify")
    source_context: str | None = Field(
        default=None,
        description="Optional ground-truth or source material for grounding the re-generations",
    )
    num_completions: int = Field(
        default=10, ge=2, le=20,
        description="Number of completions to sample (default 10)",
    )


class ClusterInfo(BaseModel):
    cluster_id: int
    size: int
    representative: str = Field(description="Shortest completion in the cluster")
    members: list[int] = Field(description="Indices of completions in this cluster")


class AnalyzeResponse(BaseModel):
    semantic_entropy: float = Field(
        ge=0.0, le=1.0,
        description="Normalized Shannon entropy: 0.0 = certain, 1.0 = maximum uncertainty",
    )
    raw_entropy: float
    num_clusters: int
    num_completions: int
    clusters: list[ClusterInfo]
    interpretation: str
    ai_output_cluster: int = Field(
        description="Cluster the original AI output belongs to, or -1 if no match",
    )
    ai_output_in_majority: bool = Field(
        description="Whether the AI output is in the largest semantic cluster",
    )
    completions: list[str] = Field(
        description="The sampled completions used for entropy calculation",
    )
    inference_time_ms: float
