"""
tests/test_evaluation_collector.py
RAGEvalCollector 采集器生命周期测试。
"""

import time
from datetime import datetime, timedelta

import pytest

from backend.evaluation.collector import RAGEvalCollector, collector
from backend.evaluation.models import RetrievalEvalRecord, GenerationEvalRecord


@pytest.fixture
def fresh_collector():
    """每次测试使用全新的 collector 实例，避免模块级单例污染。"""
    c = RAGEvalCollector(sample_rate=0.1)
    yield c
    c.clear_records()


# ============================================================
# start_query
# ============================================================

class TestStartQuery:
    def test_initializes_retrieval_record(self, fresh_collector):
        fresh_collector.start_query(
            query="什么是SGD",
            kp_name="随机梯度下降",
            user_id="42",
            session_id="99",
        )
        assert fresh_collector._current_retrieval is not None
        rec = fresh_collector._current_retrieval
        assert rec.query == "什么是SGD"
        assert rec.kp_name == "随机梯度下降"
        assert rec.user_id == "42"
        assert rec.session_id == "99"

    def test_resets_previous_state(self, fresh_collector):
        fresh_collector.start_query(query="query1", kp_name="kp1")
        fresh_collector.record_retrieval(scores=[0.9, 0.8], chunk_ids=["a", "b"])
        fresh_collector.record_generation(agent_type="doc_agent", draft_length=100)

        # 第二次 start_query 应清空状态
        fresh_collector.start_query(query="query2", kp_name="kp2")
        assert fresh_collector._current_generation is None
        assert fresh_collector._current_retrieval.query == "query2"

    def test_default_values(self, fresh_collector):
        fresh_collector.start_query(query="test")
        rec = fresh_collector._current_retrieval
        assert rec.kp_name == ""
        assert rec.user_id == ""
        assert rec.session_id == ""


# ============================================================
# record_retrieval
# ============================================================

class TestRecordRetrieval:
    def test_fills_retrieval_data(self, fresh_collector):
        fresh_collector.start_query(query="q")
        fresh_collector.record_retrieval(
            scores=[0.95, 0.80, 0.55],
            chunk_ids=["c1", "c2", "c3"],
            chunk_texts=["t1", "t2", "t3"],
            doc_ids=["d1", "d1", "d2"],
            embedding_latency_ms=100.0,
            db_query_latency_ms=50.0,
        )
        rec = fresh_collector._current_retrieval
        assert rec.scores == [0.95, 0.80, 0.55]
        assert rec.n_results == 3
        assert rec.embedding_latency_ms == 100.0
        assert rec.db_query_latency_ms == 50.0

    def test_sets_n_candidates(self, fresh_collector):
        fresh_collector.start_query(query="q")
        fresh_collector.record_retrieval(
            scores=[0.9, 0.8],
            chunk_ids=["a", "b"],
        )
        assert fresh_collector._current_retrieval.n_candidates == 2

    def test_n_candidates_at_least_1(self, fresh_collector):
        """空结果时 n_candidates 至少为 1。"""
        fresh_collector.start_query(query="q")
        fresh_collector.record_retrieval(scores=[], chunk_ids=[])
        assert fresh_collector._current_retrieval.n_candidates == 1

    def test_noop_when_no_start_query(self, fresh_collector):
        """未调用 start_query 时 record_retrieval 不应报错。"""
        fresh_collector.record_retrieval(scores=[0.9], chunk_ids=["a"])
        assert fresh_collector._current_retrieval is None


# ============================================================
# record_generation
# ============================================================

class TestRecordGeneration:
    def test_creates_generation_record(self, fresh_collector):
        fresh_collector.start_query(query="q", kp_name="kp", user_id="u1", session_id="s1")
        fresh_collector.record_generation(
            agent_type="doc_agent",
            draft_length=2000,
            generation_latency_ms=3000.0,
            safety_passed=True,
            safety_issues_count=0,
        )
        gen = fresh_collector._current_generation
        assert gen is not None
        assert gen.agent_type == "doc_agent"
        assert gen.draft_length == 2000
        assert gen.generation_latency_ms == 3000.0

    def test_links_retrieval_record(self, fresh_collector):
        fresh_collector.start_query(query="q", kp_name="kp1")
        fresh_collector.record_retrieval(scores=[0.9], chunk_ids=["c1"])
        fresh_collector.record_generation()

        gen = fresh_collector._current_generation
        assert gen.has_rag_context is True
        assert gen.n_retrieved == 1
        assert gen.kp_name == "kp1"
        assert gen.retrieval_record is not None

    def test_no_rag_context(self, fresh_collector):
        """无检索记录时 has_rag_context 应为 False。"""
        fresh_collector.start_query(query="q")
        fresh_collector.record_generation()
        assert fresh_collector._current_generation.has_rag_context is False
        assert fresh_collector._current_generation.n_retrieved == 0

    def test_safety_passed_default(self, fresh_collector):
        fresh_collector.start_query(query="q")
        fresh_collector.record_generation()
        assert fresh_collector._current_generation.safety_passed is True

    def test_safety_failed(self, fresh_collector):
        fresh_collector.start_query(query="q")
        fresh_collector.record_generation(
            safety_passed=False,
            safety_issues_count=3,
        )
        assert fresh_collector._current_generation.safety_passed is False
        assert fresh_collector._current_generation.safety_issues_count == 3


# ============================================================
# flush
# ============================================================

class TestFlush:
    def test_returns_generation_record(self, fresh_collector):
        fresh_collector.start_query(query="q")
        fresh_collector.record_retrieval(scores=[0.9], chunk_ids=["c1"])
        fresh_collector.record_generation(agent_type="doc_agent")
        result = fresh_collector.flush()
        assert isinstance(result, GenerationEvalRecord)
        assert result.agent_type == "doc_agent"

    def test_clears_state(self, fresh_collector):
        fresh_collector.start_query(query="q")
        fresh_collector.record_retrieval(scores=[0.9], chunk_ids=["c1"])
        fresh_collector.record_generation()
        fresh_collector.flush()
        assert fresh_collector._current_retrieval is None
        assert fresh_collector._current_generation is None
        assert fresh_collector._retrieval_timer is None

    def test_appends_to_records(self, fresh_collector):
        fresh_collector.start_query(query="q1")
        fresh_collector.record_retrieval(scores=[0.9], chunk_ids=["a"])
        fresh_collector.record_generation()
        fresh_collector.flush()

        fresh_collector.start_query(query="q2")
        fresh_collector.record_retrieval(scores=[0.8], chunk_ids=["b"])
        fresh_collector.record_generation()
        fresh_collector.flush()

        assert len(fresh_collector._records) == 2

    def test_flush_before_generation_returns_none(self, fresh_collector):
        """仅 start_query 未 record_generation 时 flush 返回 None。"""
        fresh_collector.start_query(query="q")
        result = fresh_collector.flush()
        assert result is None
        assert len(fresh_collector._records) == 0


# ============================================================
# decide_sample
# ============================================================

class TestDecideSample:
    def test_deterministic_with_session_id(self, fresh_collector):
        """同一 session_id 多次调用结果应一致。"""
        results = [fresh_collector.decide_sample("session_abc") for _ in range(10)]
        assert all(r == results[0] for r in results)

    def test_different_sessions_may_differ(self):
        """不同 session_id 结果可能不同（概率性，但 hash 分布均匀）。"""
        c = RAGEvalCollector(sample_rate=0.5)
        n_true = sum(1 for i in range(100) if c.decide_sample(f"session_{i}"))
        # 50% 采样率，hash 取模后大约一半为 true
        assert 20 <= n_true <= 80, f"采样分布异常: {n_true}/100"

    def test_sample_rate_0_always_false(self):
        c = RAGEvalCollector(sample_rate=0.0)
        for i in range(20):
            assert c.decide_sample(f"session_{i}") is False

    def test_sample_rate_1_always_true(self):
        c = RAGEvalCollector(sample_rate=1.0)
        for i in range(20):
            assert c.decide_sample(f"session_{i}") is True

    def test_no_session_id_uses_random(self):
        c = RAGEvalCollector(sample_rate=1.0)
        assert c.decide_sample("") is True

        c2 = RAGEvalCollector(sample_rate=0.0)
        assert c2.decide_sample("") is False


# ============================================================
# 记录查询
# ============================================================

class TestRecordQueries:
    def test_get_recent_records(self, fresh_collector):
        for i in range(5):
            fresh_collector.start_query(query=f"q{i}", session_id=str(i))
            fresh_collector.record_retrieval(scores=[0.9], chunk_ids=[f"c{i}"])
            fresh_collector.record_generation(agent_type="doc_agent")
            fresh_collector.flush()

        recent = fresh_collector.get_recent_records(n=3)
        assert len(recent) == 3
        # 最近的在最后
        assert recent[-1].query == "q4"

    def test_get_recent_records_n_greater_than_total(self, fresh_collector):
        fresh_collector.start_query(query="q")
        fresh_collector.record_retrieval(scores=[0.9], chunk_ids=["c"])
        fresh_collector.record_generation()
        fresh_collector.flush()

        assert len(fresh_collector.get_recent_records(n=100)) == 1

    def test_get_records_since(self, fresh_collector):
        fresh_collector.start_query(query="old")
        fresh_collector.record_retrieval(scores=[0.9], chunk_ids=["c"])
        fresh_collector.record_generation()
        fresh_collector.flush()

        cutoff = datetime.utcnow() + timedelta(seconds=1)
        # 没有记录在 cutoff 之后
        assert len(fresh_collector.get_records_since(cutoff)) == 0

        # 所有记录在 epoch 之后
        assert len(fresh_collector.get_records_since(datetime(2020, 1, 1))) == 1

    def test_clear_records(self, fresh_collector):
        fresh_collector.start_query(query="q")
        fresh_collector.record_retrieval(scores=[0.9], chunk_ids=["c"])
        fresh_collector.record_generation()
        fresh_collector.flush()

        assert len(fresh_collector._records) == 1
        fresh_collector.clear_records()
        assert len(fresh_collector._records) == 0


# ============================================================
# 完整生命周期
# ============================================================

class TestFullLifecycle:
    def test_complete_flow(self, fresh_collector):
        """从 start 到 flush 的完整流程。"""
        fresh_collector.start_query(
            query="什么是反向传播",
            kp_name="反向传播",
            user_id="1001",
            session_id="5001",
        )

        time.sleep(0.01)  # 模拟检索耗时

        fresh_collector.record_retrieval(
            scores=[0.92, 0.87, 0.73, 0.61, 0.45],
            chunk_ids=["d1_0", "d1_1", "d2_0", "d2_1", "d3_0"],
            chunk_texts=["t1", "t2", "t3", "t4", "t5"],
            doc_ids=["d1", "d1", "d2", "d2", "d3"],
            embedding_latency_ms=95.0,
            db_query_latency_ms=30.0,
        )

        fresh_collector.record_generation(
            agent_type="doc_agent",
            draft_length=1800,
            generation_latency_ms=2500.0,
            safety_passed=True,
        )

        result = fresh_collector.flush()
        assert result is not None
        assert result.agent_type == "doc_agent"
        assert result.kp_name == "反向传播"
        assert result.n_retrieved == 5
        assert result.safety_passed is True
        assert result.retrieval_record is not None
        assert result.retrieval_record.scores == [0.92, 0.87, 0.73, 0.61, 0.45]


# ============================================================
# 模块级单例
# ============================================================

class TestModuleSingleton:
    def test_collector_is_instance(self):
        from backend.evaluation import collector as mod_collector
        assert isinstance(mod_collector, RAGEvalCollector)

    def test_collector_has_default_sample_rate(self):
        from backend.evaluation import collector as mod_collector
        assert 0.0 <= mod_collector.sample_rate <= 1.0
