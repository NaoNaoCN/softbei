"""
backend/evaluation/models.py
评估数据模型：检索快照、生成快照、评估报告。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class RetrievalEvalRecord(BaseModel):
    """单次检索的评估快照。"""

    query: str = ""
    kp_name: str = ""
    user_id: str = ""
    session_id: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    embedding_latency_ms: float = 0.0
    db_query_latency_ms: float = 0.0
    n_candidates: int = 0
    n_results: int = 0
    scores: list[float] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    doc_ids: list[str] = Field(default_factory=list)
    chunk_texts: list[str] = Field(default_factory=list)


class GenerationEvalRecord(BaseModel):
    """单次生成的评估快照。"""

    session_id: str = ""
    user_id: str = ""
    agent_type: str = ""
    kp_name: str = ""
    query: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # 自动采集字段
    draft_length: int = 0
    generation_latency_ms: float = 0.0
    has_rag_context: bool = False
    n_retrieved: int = 0
    safety_passed: bool = True
    safety_issues_count: int = 0

    # 关联的检索快照
    retrieval_record: Optional[RetrievalEvalRecord] = None

    # LLM-as-Judge 评估结果（异步填充）
    faithfulness_score: Optional[float] = None
    hallucination_rate_val: Optional[float] = Field(default=None, alias="hallucination_rate")
    concept_coverage: Optional[float] = None
    completeness_score: Optional[float] = None

    # 评估详细信息
    relevance_labels: list[int] = Field(default_factory=list)   # Judge 1: 0/1/2
    faithfulness_statements: list[dict] = Field(default_factory=list)  # Judge 2
    completeness_aspects: list[dict] = Field(default_factory=list)     # Judge 3

    model_config = ConfigDict(populate_by_name=True)


class RAGEvalReport(BaseModel):
    """周期性评估报告。"""

    period_start: datetime
    period_end: datetime
    total_queries: int = 0

    # 检索质量汇总
    precision_at_5: float = 0.0
    recall_at_5: float = 0.0
    mrr_val: float = Field(default=0.0, alias="mrr")
    ndcg_at_5: float = 0.0
    hit_rate_val: float = Field(default=0.0, alias="hit_rate")
    score_p50: float = 0.0

    # 生成质量汇总
    avg_faithfulness: float = 0.0
    avg_hallucination_rate: float = 0.0
    avg_concept_coverage: float = 0.0

    # 系统效率
    p50_retrieval_latency_ms: float = 0.0
    p95_retrieval_latency_ms: float = 0.0
    p50_generation_latency_ms: float = 0.0

    # 变化趋势（与上期对比）
    delta_vs_previous: dict[str, float] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)
