"""
tests/test_evaluation_reporter.py
RAGReporter 报告生成与渲染测试。
"""

import json
from datetime import datetime, timedelta

import pytest

from backend.evaluation.models import RAGEvalReport, GenerationEvalRecord
from backend.evaluation.reporter import (
    RAGReporter,
    write_eval_result,
    write_report,
    _make_json_safe,
    _result_to_markdown,
)


@pytest.fixture
def reporter():
    return RAGReporter()


# ============================================================
# generate_report
# ============================================================

class TestGenerateReport:
    def test_empty_records(self, reporter):
        report = reporter.generate_report([])
        assert report.total_queries == 0
        assert report.precision_at_5 == 0.0
        assert isinstance(report, RAGEvalReport)

    def test_with_records(self, reporter, sample_generation_records):
        report = reporter.generate_report(sample_generation_records)
        assert report.total_queries == 3
        assert 0.0 <= report.precision_at_5 <= 1.0
        assert 0.0 <= report.avg_faithfulness <= 1.0
        assert 0.0 <= report.avg_hallucination_rate <= 1.0

    def test_non_empty_timestamps(self, reporter, sample_generation_record):
        report = reporter.generate_report([sample_generation_record])
        assert report.period_start is not None
        assert report.period_end is not None

    def test_system_efficiency_fields(self, reporter, sample_generation_record):
        """有检索延迟数据时应计算 P50/P95。"""
        report = reporter.generate_report([sample_generation_record])
        assert report.p50_retrieval_latency_ms >= 0
        assert report.p95_retrieval_latency_ms >= 0

    def test_record_without_judge_scores(self, reporter):
        """无 Judge 评分的记录不应导致除零错误。"""
        rec = GenerationEvalRecord(
            session_id="s1",
            agent_type="doc_agent",
            draft_length=100,
        )
        report = reporter.generate_report([rec])
        assert report.total_queries == 1
        assert report.avg_faithfulness == 0.0

    def test_delta_vs_previous(self, reporter, sample_generation_records):
        """连续两期报告应有变化趋势。"""
        # 第一期
        first = reporter.generate_report(sample_generation_records[:1])
        # 第二期（数据不同）
        second = reporter.generate_report(sample_generation_records)
        # 第二期可能包含 delta（如果 _last_report 有上一期）
        assert isinstance(second.delta_vs_previous, dict)


# ============================================================
# daily / weekly
# ============================================================

class TestDailyWeekly:
    def test_daily_filters_24h(self, reporter):
        now = datetime.utcnow()
        # 13 小时前 — 在 24h 内
        rec = GenerationEvalRecord(
            session_id="s1",
            agent_type="doc_agent",
            timestamp=now - timedelta(hours=13),
        )
        report = reporter.generate_daily_report([rec])
        assert report.total_queries == 1

    def test_daily_excludes_old(self, reporter):
        now = datetime.utcnow()
        # 25 小时前 — 超出 24h
        rec = GenerationEvalRecord(
            session_id="s1",
            agent_type="doc_agent",
            timestamp=now - timedelta(hours=25),
        )
        report = reporter.generate_daily_report([rec])
        assert report.total_queries == 0

    def test_weekly_filters_7d(self, reporter):
        now = datetime.utcnow()
        rec = GenerationEvalRecord(
            session_id="s1",
            agent_type="doc_agent",
            timestamp=now - timedelta(days=6),
        )
        report = reporter.generate_weekly_report([rec])
        assert report.total_queries == 1

    def test_weekly_excludes_old(self, reporter):
        now = datetime.utcnow()
        rec = GenerationEvalRecord(
            session_id="s1",
            agent_type="doc_agent",
            timestamp=now - timedelta(days=8),
        )
        report = reporter.generate_weekly_report([rec])
        assert report.total_queries == 0


# ============================================================
# compare_reports
# ============================================================

class TestCompareReports:
    def test_delta_calculation(self, reporter):
        now = datetime.utcnow()
        a = RAGEvalReport(
            period_start=now,
            period_end=now,
            precision_at_5=0.60,
            avg_faithfulness=0.75,
            mrr=0.50,
        )
        b = RAGEvalReport(
            period_start=now,
            period_end=now,
            precision_at_5=0.70,
            avg_faithfulness=0.80,
            mrr=0.55,
        )
        comp = reporter.compare_reports(a, b)
        assert comp["precision_at_5"]["delta"] == pytest.approx(0.10)
        assert comp["avg_faithfulness"]["delta"] == pytest.approx(0.05)
        assert comp["precision_at_5"]["delta_pct"] == pytest.approx(100 * 0.10 / 0.60, rel=0.01)

    def test_delta_zero_when_no_change(self, reporter):
        now = datetime.utcnow()
        a = RAGEvalReport(period_start=now, period_end=now, precision_at_5=0.60)
        b = RAGEvalReport(period_start=now, period_end=now, precision_at_5=0.60)
        comp = reporter.compare_reports(a, b)
        assert comp["precision_at_5"]["delta"] == 0.0

    def test_delta_with_zero_base(self, reporter):
        """基线为 0 时 delta_pct 应为 0。"""
        now = datetime.utcnow()
        a = RAGEvalReport(period_start=now, period_end=now, precision_at_5=0.0)
        b = RAGEvalReport(period_start=now, period_end=now, precision_at_5=0.05)
        comp = reporter.compare_reports(a, b)
        assert comp["precision_at_5"]["delta_pct"] == 0.0


# ============================================================
# to_markdown
# ============================================================

class TestToMarkdown:
    def test_renders_table(self, reporter, sample_generation_records):
        report = reporter.generate_report(sample_generation_records)
        md = reporter.to_markdown(report)
        assert "# RAG 评估报告" in md
        assert "Precision@5" in md
        assert "Faithfulness" in md
        assert "P50 Retrieval Latency" in md

    def test_empty_report(self, reporter):
        report = reporter.generate_report([])
        md = reporter.to_markdown(report)
        assert "0" in md

    def test_includes_delta_section(self, reporter, sample_generation_records):
        # 第一期
        reporter.generate_report(sample_generation_records[:1])
        # 第二期
        report2 = reporter.generate_report(sample_generation_records)
        md = reporter.to_markdown(report2)
        assert "变化趋势" in md or "Delta" in md


# ============================================================
# to_summary
# ============================================================

class TestToSummary:
    def test_single_line_format(self, reporter, sample_generation_records):
        report = reporter.generate_report(sample_generation_records)
        summary = reporter.to_summary(report)
        assert "[RAGReport]" in summary
        assert "queries=3" in summary
        assert "P@5=" in summary
        assert "Faith=" in summary

    def test_empty_summary(self, reporter):
        report = reporter.generate_report([])
        summary = reporter.to_summary(report)
        assert "queries=0" in summary


# ============================================================
# 文件写入（使用 tmp_path）
# ============================================================

class TestFileWriting:
    def test_write_result_to_log_dir(self, tmp_path, monkeypatch):
        """写入评估结果到临时目录。"""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        # 劫持 _ensure_log_dir 返回临时目录
        monkeypatch.setattr(
            RAGReporter, "_ensure_log_dir", staticmethod(lambda: log_dir)
        )

        result = {
            "query": "测试",
            "kp_name": "测试知识点",
            "faithfulness_score": 0.85,
            "hallucination_rate": 0.15,
            "completeness_score": 0.70,
            "precision_at_5": 0.80,
            "evaluation_time_ms": 1500.0,
            "relevance_labels": [2, 1, 0],
            "faithfulness_statements": [
                {"text": "陈述1", "verdict": "supported"},
                {"text": "陈述2", "verdict": "unsupported"},
            ],
            "completeness_aspects": [
                {"aspect": "定义", "coverage": "covered"},
                {"aspect": "应用", "coverage": "partial"},
            ],
            "faithfulness_issues": ["问题1"],
            "citation_precision": 0.90,
        }

        path = RAGReporter.write_result_to_log_dir(result, label="test")
        assert path is not None

        # 应该生成了 .md 和 .json 两个文件
        md_files = list(log_dir.glob("rag_test_*.md"))
        json_files = list(log_dir.glob("rag_test_*.json"))
        assert len(md_files) == 1
        assert len(json_files) == 1

        # JSON 文件应可解析
        with open(json_files[0], "r", encoding="utf-8") as f:
            parsed = json.load(f)
            assert parsed["kp_name"] == "测试知识点"
            assert parsed["faithfulness_score"] == 0.85

        # MD 文件应包含关键信息
        md_content = md_files[0].read_text(encoding="utf-8")
        assert "测试知识点" in md_content
        assert "0.85" in md_content

    def test_write_report_to_log_dir(self, tmp_path, monkeypatch, reporter, sample_generation_records):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.setattr(
            RAGReporter, "_ensure_log_dir", staticmethod(lambda: log_dir)
        )

        report = reporter.generate_report(sample_generation_records)
        path = RAGReporter.write_report_to_log_dir(report, label="daily")
        assert path is not None

        md_files = list(log_dir.glob("rag_daily_*.md"))
        json_files = list(log_dir.glob("rag_daily_*.json"))
        assert len(md_files) == 1
        assert len(json_files) == 1

        md_content = md_files[0].read_text(encoding="utf-8")
        assert "# RAG 评估报告" in md_content

    def test_convenience_functions(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.setattr(
            RAGReporter, "_ensure_log_dir", staticmethod(lambda: log_dir)
        )

        path = write_eval_result({"kp_name": "test", "query": "q"}, label="conv")
        assert path is not None
        assert len(list(log_dir.glob("rag_conv_*.json"))) == 1


# ============================================================
# 内部辅助函数
# ============================================================

class TestInternalHelpers:
    def test_make_json_safe_handles_datetime(self):
        obj = {"ts": datetime(2025, 1, 15, 10, 30, 0)}
        safe = _make_json_safe(obj)
        assert safe["ts"] == "2025-01-15T10:30:00"

    def test_make_json_safe_handles_nested(self):
        obj = {
            "outer": {
                "inner_list": [datetime(2025, 1, 1, 0, 0, 0)],
            }
        }
        safe = _make_json_safe(obj)
        assert safe["outer"]["inner_list"][0] == "2025-01-01T00:00:00"

    def test_make_json_safe_handles_enum(self):
        from enum import Enum

        class Color(Enum):
            RED = "red"

        safe = _make_json_safe({"color": Color.RED})
        assert safe["color"] == "red"

    def test_result_to_markdown_empty(self):
        md = _result_to_markdown({}, "test", "20250101_120000")
        assert "# RAG 评估结果" in md
        assert "test" in md

    def test_result_to_markdown_full(self):
        result = {
            "kp_name": "梯度下降",
            "query": "什么是梯度下降",
            "faithfulness_score": 0.82,
            "hallucination_rate": 0.18,
            "completeness_score": 0.65,
            "precision_at_5": 0.75,
            "citation_precision": 0.88,
            "evaluation_time_ms": 2300.0,
            "relevance_labels": [2, 2, 1, 0, 2],
            "faithfulness_statements": [
                {"text": "正确陈述", "verdict": "supported", "evidence": "原文..."},
                {"text": "错误陈述", "verdict": "unsupported", "evidence": None},
            ],
            "completeness_aspects": [
                {"aspect": "定义", "coverage": "covered"},
                {"aspect": "误区", "coverage": "missing"},
            ],
            "faithfulness_issues": ["发现捏造事实"],
        }
        md = _result_to_markdown(result, "eval", "20250101_120000")
        assert "梯度下降" in md
        assert "0.82" in md
        assert "0.18" in md
        assert "高度相关" in md or "2" in md
        assert "发现捏造事实" in md
