"""
tests/test_evaluation_models.py
Pydantic 数据模型的验证和序列化测试。
"""

import pytest
from datetime import datetime

from backend.evaluation.models import (
    RetrievalEvalRecord,
    GenerationEvalRecord,
    RAGEvalReport,
)


# ============================================================
# RetrievalEvalRecord
# ============================================================

class TestRetrievalEvalRecord:
    def test_default_values(self):
        rec = RetrievalEvalRecord()
        assert rec.query == ""
        assert rec.kp_name == ""
        assert rec.user_id == ""
        assert rec.session_id == ""
        assert rec.scores == []
        assert rec.chunk_ids == []
        assert rec.embedding_latency_ms == 0.0
        assert isinstance(rec.timestamp, datetime)

    def test_full_creation(self, sample_scores):
        rec = RetrievalEvalRecord(
            query="什么是SGD",
            kp_name="随机梯度下降",
            user_id="42",
            session_id="99",
            embedding_latency_ms=200.0,
            db_query_latency_ms=80.0,
            n_candidates=20,
            n_results=5,
            scores=sample_scores,
            chunk_ids=["c1", "c2", "c3", "c4", "c5"],
            doc_ids=["d1", "d1", "d2", "d2", "d3"],
            chunk_texts=["text1", "text2", "text3", "text4", "text5"],
        )
        assert rec.user_id == "42"
        assert rec.n_results == 5
        assert rec.scores == sample_scores

    def test_timestamp_is_set(self):
        rec = RetrievalEvalRecord()
        assert rec.timestamp is not None
        delta = datetime.utcnow() - rec.timestamp
        assert delta.total_seconds() < 5  # 刚创建的

    def test_custom_timestamp(self):
        past = datetime(2025, 1, 1, 12, 0, 0)
        rec = RetrievalEvalRecord(timestamp=past)
        assert rec.timestamp == past


# ============================================================
# GenerationEvalRecord
# ============================================================

class TestGenerationEvalRecord:
    def test_default_values(self):
        rec = GenerationEvalRecord()
        assert rec.agent_type == ""
        assert rec.draft_length == 0
        assert rec.safety_passed is True
        assert rec.faithfulness_score is None
        assert rec.hallucination_rate_val is None
        assert rec.relevance_labels == []

    def test_full_creation_no_judge(self):
        rec = GenerationEvalRecord(
            session_id="s1",
            user_id="u1",
            agent_type="doc_agent",
            kp_name="测试",
            draft_length=1500,
            generation_latency_ms=3000.0,
            has_rag_context=True,
            n_retrieved=5,
            safety_passed=True,
        )
        assert rec.agent_type == "doc_agent"
        assert rec.has_rag_context is True
        assert rec.faithfulness_score is None

    def test_full_creation_with_judge(self, sample_retrieval_record, sample_faithfulness_result, sample_completeness_result):
        rec = GenerationEvalRecord(
            session_id="s1",
            user_id="u1",
            agent_type="doc_agent",
            kp_name="梯度下降",
            draft_length=2000,
            generation_latency_ms=3000.0,
            safety_passed=True,
            retrieval_record=sample_retrieval_record,
            faithfulness_score=0.85,
            hallucination_rate=0.15,
            concept_coverage=0.70,
            completeness_score=0.70,
            relevance_labels=[2, 2, 1, 0, 2],
            faithfulness_statements=sample_faithfulness_result["statements"],
            completeness_aspects=sample_completeness_result["aspects"],
        )
        assert rec.faithfulness_score == 0.85
        assert rec.hallucination_rate_val == 0.15
        assert rec.completeness_score == 0.70
        assert rec.retrieval_record is sample_retrieval_record

    def test_hallucination_rate_alias(self):
        """测试 hallucination_rate → hallucination_rate_val 别名映射。"""
        rec = GenerationEvalRecord(hallucination_rate=0.25)
        assert rec.hallucination_rate_val == 0.25

    def test_model_dump_includes_fields(self, sample_generation_record):
        d = sample_generation_record.model_dump(by_alias=True)
        assert "agent_type" in d
        assert "faithfulness_score" in d
        assert "hallucination_rate" in d  # alias 在 dump(by_alias=True) 中

    def test_relevance_labels_serialization(self):
        rec = GenerationEvalRecord(relevance_labels=[2, 1, 0])
        d = rec.model_dump()
        assert d["relevance_labels"] == [2, 1, 0]


# ============================================================
# RAGEvalReport
# ============================================================

class TestRAGEvalReport:
    def test_default_values(self):
        now = datetime.utcnow()
        report = RAGEvalReport(period_start=now, period_end=now)
        assert report.total_queries == 0
        assert report.precision_at_5 == 0.0
        assert report.avg_faithfulness == 0.0

    def test_full_creation(self):
        now = datetime.utcnow()
        report = RAGEvalReport(
            period_start=now,
            period_end=now,
            total_queries=50,
            precision_at_5=0.75,
            recall_at_5=0.82,
            mrr=0.65,
            ndcg_at_5=0.78,
            hit_rate=0.90,
            avg_faithfulness=0.82,
            avg_hallucination_rate=0.12,
            p50_retrieval_latency_ms=200.0,
            p95_retrieval_latency_ms=500.0,
        )
        assert report.precision_at_5 == 0.75
        assert report.mrr_val == 0.65  # alias
        assert report.hit_rate_val == 0.90  # alias

    def test_mrr_alias(self):
        """mrr → mrr_val 别名。"""
        report = RAGEvalReport(
            period_start=datetime.utcnow(),
            period_end=datetime.utcnow(),
            mrr=0.55,
        )
        assert report.mrr_val == 0.55

    def test_hit_rate_alias(self):
        report = RAGEvalReport(
            period_start=datetime.utcnow(),
            period_end=datetime.utcnow(),
            hit_rate=0.77,
        )
        assert report.hit_rate_val == 0.77

    def test_delta_vs_previous(self):
        report = RAGEvalReport(
            period_start=datetime.utcnow(),
            period_end=datetime.utcnow(),
            delta_vs_previous={"faithfulness": 0.05, "p50_retrieval_latency_ms": -30.0},
        )
        assert report.delta_vs_previous["faithfulness"] == 0.05
        assert report.delta_vs_previous["p50_retrieval_latency_ms"] == -30.0

    def test_model_dump(self):
        now = datetime.utcnow()
        report = RAGEvalReport(
            period_start=now,
            period_end=now,
            total_queries=10,
            mrr=0.60,
        )
        d = report.model_dump(by_alias=True)
        assert d["mrr"] == 0.60
        assert d["total_queries"] == 10
