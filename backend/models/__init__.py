from pydantic import BaseModel
from typing import List, Optional

class QueryRequest(BaseModel):
    query: str

class QueryResponse(BaseModel):
    answer: str
    sources: List[str]
    correction_attempts: int
    was_corrected: bool
    retrieval_score: float
    response_time_ms: float
    metadata: dict

class DocumentMetadata(BaseModel):
    source: str
    page: int
    chunk_id: str

class EvaluationResult(BaseModel):
    faithfulness: float
    answer_relevancy: float
    context_recall: float
    context_precision: float

class MetricsResponse(BaseModel):
    total_queries: int
    total_corrections: int
    correction_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    error_rate: float
    cache_hit_rate: float