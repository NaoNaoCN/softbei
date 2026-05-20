"""
backend/evaluation/__init__.py
RAG 效果评估与量化系统。
"""

from backend.evaluation.models import (
    RetrievalEvalRecord,
    GenerationEvalRecord,
    RAGEvalReport,
)
from backend.evaluation.metrics import (
    precision_at_k,
    recall_at_k,
    mrr,
    ndcg_at_k,
    hit_rate,
    hallucination_rate,
    score_distribution,
)
from backend.evaluation.judge import RAGJudge
from backend.evaluation.collector import RAGEvalCollector, collector
from backend.evaluation.reporter import RAGReporter, write_eval_result, write_report

__all__ = [
    # models
    "RetrievalEvalRecord",
    "GenerationEvalRecord",
    "RAGEvalReport",
    # metrics
    "precision_at_k",
    "recall_at_k",
    "mrr",
    "ndcg_at_k",
    "hit_rate",
    "hallucination_rate",
    "score_distribution",
    # judge
    "RAGJudge",
    # collector
    "RAGEvalCollector",
    "collector",
    # reporter
    "RAGReporter",
    "write_eval_result",
    "write_report",
]
