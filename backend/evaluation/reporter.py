"""
backend/evaluation/reporter.py
RAG 评估报告生成器：聚合采集数据，生成日报/周报/Markdown 报告，
并支持将报告写入 logs/ 目录。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger

from backend.config import config
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
    score_distribution,
    avg_score,
)


class RAGReporter:
    """RAG 评估报告生成器。

    用法::

        reporter = RAGReporter()
        report = reporter.generate_report(records)
        print(reporter.to_markdown(report))
    """

    def __init__(self):
        self._last_report: Optional[RAGEvalReport] = None

    # ----------------------------------------------------------
    # 报告生成
    # ----------------------------------------------------------

    def generate_report(
        self,
        records: list[GenerationEvalRecord],
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> RAGEvalReport:
        """
        从采集记录生成评估报告。

        :param records:      GenerationEvalRecord 列表
        :param period_start: 报告周期开始时间
        :param period_end:   报告周期结束时间
        :return:             RAGEvalReport
        """
        if not records:
            return RAGEvalReport(
                period_start=period_start or datetime.utcnow(),
                period_end=period_end or datetime.utcnow(),
                total_queries=0,
            )

        # 确定时间范围
        timestamps = [r.timestamp for r in records if r.timestamp]
        start = period_start or (min(timestamps) if timestamps else datetime.utcnow())
        end = period_end or (max(timestamps) if timestamps else datetime.utcnow())

        # === 检索质量 ===
        all_relevance_labels = [
            r.relevance_labels for r in records if r.relevance_labels
        ]

        k = 5
        precision_scores = [precision_at_k(labels, k) for labels in all_relevance_labels if labels]
        recall_scores = []
        for labels in all_relevance_labels:
            if labels:
                total_rel = sum(1 for v in labels if v > 0)
                recall_scores.append(recall_at_k(labels, total_rel, k) if total_rel > 0 else 0.0)

        # 从 retrieval_record 提取分数分布
        all_retrieval_scores: list[float] = []
        retrieval_latencies: list[float] = []
        for r in records:
            if r.retrieval_record and r.retrieval_record.scores:
                all_retrieval_scores.extend(r.retrieval_record.scores)
                total_latency = r.retrieval_record.embedding_latency_ms + r.retrieval_record.db_query_latency_ms
                if total_latency > 0:
                    retrieval_latencies.append(total_latency)

        score_dist = score_distribution(all_retrieval_scores)

        # === 生成质量 ===
        faithfulness_scores = [
            r.faithfulness_score for r in records
            if r.faithfulness_score is not None
        ]
        hallucination_rates = [
            r.hallucination_rate_val or 0.0 for r in records
        ]
        concept_coverages = [
            r.concept_coverage for r in records
            if r.concept_coverage is not None
        ]
        completeness_scores = [
            r.completeness_score for r in records
            if r.completeness_score is not None
        ]

        # === 系统效率 ===
        gen_latencies = [
            r.generation_latency_ms for r in records
            if r.generation_latency_ms > 0
        ]
        ret_latencies_sorted = sorted(retrieval_latencies) if retrieval_latencies else []
        gen_latencies_sorted = sorted(gen_latencies) if gen_latencies else []

        def _p50(vals: list[float]) -> float:
            if not vals:
                return 0.0
            return vals[len(vals) // 2]

        def _p95(vals: list[float]) -> float:
            if not vals:
                return 0.0
            return vals[int(len(vals) * 0.95)]

        # === 变化趋势 ===
        delta: dict[str, float] = {}
        if self._last_report is not None:
            prev = self._last_report
            if prev.avg_faithfulness > 0:
                cur_faith = (
                    sum(faithfulness_scores) / len(faithfulness_scores)
                    if faithfulness_scores else 0.0
                )
                delta["faithfulness"] = round(cur_faith - prev.avg_faithfulness, 4)
            if prev.p50_retrieval_latency_ms > 0:
                cur_lat = _p50(ret_latencies_sorted)
                delta["p50_retrieval_latency_ms"] = round(cur_lat - prev.p50_retrieval_latency_ms, 1)

        report = RAGEvalReport(
            period_start=start,
            period_end=end,
            total_queries=len(records),
            # 检索质量
            precision_at_5=round(sum(precision_scores) / len(precision_scores), 4) if precision_scores else 0.0,
            recall_at_5=round(sum(recall_scores) / len(recall_scores), 4) if recall_scores else 0.0,
            mrr_val=round(mrr(all_relevance_labels), 4) if all_relevance_labels else 0.0,
            ndcg_at_5=round(sum(ndcg_at_k(labels, k) for labels in all_relevance_labels) / len(all_relevance_labels), 4) if all_relevance_labels else 0.0,
            hit_rate_val=round(hit_rate(all_relevance_labels, k), 4) if all_relevance_labels else 0.0,
            score_p50=round(score_dist.get("p50", 0.0), 4),
            # 生成质量
            avg_faithfulness=round(sum(faithfulness_scores) / len(faithfulness_scores), 4) if faithfulness_scores else 0.0,
            avg_hallucination_rate=round(sum(hallucination_rates) / len(hallucination_rates), 4) if hallucination_rates else 0.0,
            avg_concept_coverage=round(sum(concept_coverages) / len(concept_coverages), 4) if concept_coverages else 0.0,
            # 系统效率
            p50_retrieval_latency_ms=round(_p50(ret_latencies_sorted), 1),
            p95_retrieval_latency_ms=round(_p95(ret_latencies_sorted), 1),
            p50_generation_latency_ms=round(_p50(gen_latencies_sorted), 1),
            # 变化趋势
            delta_vs_previous=delta,
        )

        self._last_report = report
        return report

    # ----------------------------------------------------------
    # 周报 / 日报
    # ----------------------------------------------------------

    def generate_daily_report(
        self,
        records: list[GenerationEvalRecord],
    ) -> RAGEvalReport:
        """生成日报：过去 24 小时的指标。"""
        now = datetime.utcnow()
        start = now - timedelta(hours=24)
        daily = [r for r in records if r.timestamp and r.timestamp >= start]
        return self.generate_report(daily, period_start=start, period_end=now)

    def generate_weekly_report(
        self,
        records: list[GenerationEvalRecord],
    ) -> RAGEvalReport:
        """生成周报：过去 7 天的指标。"""
        now = datetime.utcnow()
        start = now - timedelta(days=7)
        weekly = [r for r in records if r.timestamp and r.timestamp >= start]
        return self.generate_report(weekly, period_start=start, period_end=now)

    # ----------------------------------------------------------
    # 对比报告
    # ----------------------------------------------------------

    def compare_reports(
        self,
        report_a: RAGEvalReport,
        report_b: RAGEvalReport,
    ) -> dict:
        """对比两期报告，计算各项指标的 delta 值。"""
        fields = [
            "precision_at_5", "recall_at_5", "mrr_val", "ndcg_at_5",
            "hit_rate_val", "score_p50",
            "avg_faithfulness", "avg_hallucination_rate", "avg_concept_coverage",
            "p50_retrieval_latency_ms", "p95_retrieval_latency_ms",
            "p50_generation_latency_ms",
        ]
        comparison = {}
        for f in fields:
            val_a = getattr(report_a, f, 0.0) or 0.0
            val_b = getattr(report_b, f, 0.0) or 0.0
            comparison[f] = {
                "a": val_a,
                "b": val_b,
                "delta": round(val_b - val_a, 4),
                "delta_pct": round((val_b - val_a) / abs(val_a) * 100, 1) if val_a != 0 else 0.0,
            }
        return comparison

    # ----------------------------------------------------------
    # 渲染
    # ----------------------------------------------------------

    def to_markdown(self, report: RAGEvalReport) -> str:
        """将报告渲染为 Markdown 格式字符串。"""
        lines = [
            f"# RAG 评估报告",
            f"",
            f"**周期：** {report.period_start.strftime('%Y-%m-%d %H:%M')} → {report.period_end.strftime('%Y-%m-%d %H:%M')}",
            f"**总查询数：** {report.total_queries}",
            f"",
            f"## 检索质量",
            f"",
            f"| 指标 | 值 | 参考标准 | 达标 |",
            f"|------|-----|---------|------|",
            f"| Precision@5 | {report.precision_at_5:.3f} | > 0.60 | {_check_reference(report.precision_at_5, '> 0.60')} |",
            f"| Recall@5 | {report.recall_at_5:.3f} | > 0.70 | {_check_reference(report.recall_at_5, '> 0.70')} |",
            f"| MRR | {report.mrr_val:.3f} | > 0.50 | {_check_reference(report.mrr_val, '> 0.50')} |",
            f"| NDCG@5 | {report.ndcg_at_5:.3f} | > 0.60 | {_check_reference(report.ndcg_at_5, '> 0.60')} |",
            f"| Hit Rate@5 | {report.hit_rate_val:.3f} | > 0.80 | {_check_reference(report.hit_rate_val, '> 0.80')} |",
            f"| Score P50 | {report.score_p50:.3f} | > 0.65 | {_check_reference(report.score_p50, '> 0.65')} |",
            f"",
            f"## 生成质量",
            f"",
            f"| 指标 | 值 | 参考标准 | 达标 |",
            f"|------|-----|---------|------|",
            f"| Avg Faithfulness | {report.avg_faithfulness:.3f} | > 0.70 | {_check_reference(report.avg_faithfulness, '> 0.70')} |",
            f"| Avg Hallucination Rate | {report.avg_hallucination_rate:.3f} | < 0.30 | {_check_reference(report.avg_hallucination_rate, '< 0.30')} |",
            f"| Avg Concept Coverage | {report.avg_concept_coverage:.3f} | > 0.60 | {_check_reference(report.avg_concept_coverage, '> 0.60')} |",
            f"",
            f"## 系统效率",
            f"",
            f"| 指标 | 值 | 参考标准 | 达标 |",
            f"|------|-----|---------|------|",
            f"| P50 Retrieval Latency | {report.p50_retrieval_latency_ms:.0f} ms | < 500 ms | {_check_reference(report.p50_retrieval_latency_ms, '< 500')} |",
            f"| P95 Retrieval Latency | {report.p95_retrieval_latency_ms:.0f} ms | < 1000 ms | {_check_reference(report.p95_retrieval_latency_ms, '< 1000')} |",
            f"| P50 Generation Latency | {report.p50_generation_latency_ms:.0f} ms | < 5000 ms | {_check_reference(report.p50_generation_latency_ms, '< 5000')} |",
        ]

        # 变化趋势
        if report.delta_vs_previous:
            lines.append("")
            lines.append("## 变化趋势（与上期对比）")
            lines.append("")
            lines.append("| 指标 | Delta |")
            lines.append("|------|-------|")
            for key, val in report.delta_vs_previous.items():
                sign = "+" if val >= 0 else ""
                lines.append(f"| {key} | {sign}{val:.4f} |")

        return "\n".join(lines)

    def to_summary(self, report: RAGEvalReport) -> str:
        """生成单行摘要，适合日志输出。"""
        return (
            f"[RAGReport] queries={report.total_queries} "
            f"P@5={report.precision_at_5:.3f} "
            f"Faith={report.avg_faithfulness:.3f} "
            f"Halluc={report.avg_hallucination_rate:.3f} "
            f"P50_ret={report.p50_retrieval_latency_ms:.0f}ms "
            f"P50_gen={report.p50_generation_latency_ms:.0f}ms"
        )

    # ----------------------------------------------------------
    # 文件写入
    # ----------------------------------------------------------

    @staticmethod
    def _ensure_log_dir() -> Path:
        """确保日志目录存在，返回 Path 对象。"""
        log_dir = Path(config.logging.dir)
        if not log_dir.is_absolute():
            # 相对于项目根目录
            log_dir = Path(__file__).parent.parent.parent / config.logging.dir
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    @staticmethod
    def write_result_to_log_dir(result: dict, label: str = "eval") -> str | None:
        """
        将单次 LLM-as-Judge 评估结果写入 logs/ 目录。

        生成两个文件（共用时间戳前缀）：
        - logs/rag_{label}_{timestamp}.md   — 人类可读的 Markdown 报告
        - logs/rag_{label}_{timestamp}.json — 机器可读的完整数据

        :param result: 评估结果 dict（来自 RAGJudge.evaluate_full() 或类似结构）
        :param label:  文件标签（如 "eval"、"daily"、"weekly"）
        :return:       写入的 JSON 文件路径，失败返回 None
        """
        try:
            log_dir = RAGReporter._ensure_log_dir()
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            base_name = f"rag_{label}_{ts}"

            # -- JSON（完整数据）--
            json_path = log_dir / f"{base_name}.json"
            serializable = _make_json_safe(result)
            json_path.write_text(
                json.dumps(serializable, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # -- Markdown（人类可读摘要）--
            md_path = log_dir / f"{base_name}.md"
            md_content = _result_to_markdown(result, label, ts)
            md_path.write_text(md_content, encoding="utf-8")

            logger.info(f"[RAGReporter] 评估报告已写入: {md_path}")
            return str(json_path)
        except Exception as e:
            logger.warning(f"[RAGReporter] 写入评估报告失败: {e}")
            return None

    @staticmethod
    def write_report_to_log_dir(report: RAGEvalReport, label: str = "report") -> str | None:
        """
        将 RAGEvalReport 写入 logs/ 目录。

        :param report: RAGEvalReport 实例
        :param label:  文件标签（如 "daily"、"weekly"）
        :return:       写入的文件路径
        """
        try:
            log_dir = RAGReporter._ensure_log_dir()
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            base_name = f"rag_{label}_{ts}"

            md_path = log_dir / f"{base_name}.md"
            reporter = RAGReporter()
            md_path.write_text(reporter.to_markdown(report), encoding="utf-8")

            json_path = log_dir / f"{base_name}.json"
            json_path.write_text(
                json.dumps(report.model_dump(), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )

            logger.info(f"[RAGReporter] 汇总报告已写入: {md_path}")
            return str(md_path)
        except Exception as e:
            logger.warning(f"[RAGReporter] 写入汇总报告失败: {e}")
            return None


# ----------------------------------------------------------
# 模块级便捷函数
# ----------------------------------------------------------

def write_eval_result(result: dict, label: str = "eval") -> str | None:
    """将评估结果写入 logs/ 目录（无需实例化 RAGReporter）。"""
    return RAGReporter.write_result_to_log_dir(result, label)


def write_report(report: RAGEvalReport, label: str = "report") -> str | None:
    """将 RAGEvalReport 写入 logs/ 目录（无需实例化 RAGReporter）。"""
    return RAGReporter.write_report_to_log_dir(report, label)


# ----------------------------------------------------------
# 内部辅助
# ----------------------------------------------------------

def _check_reference(value: float, ref_str: str) -> str:
    """
    对比实际值与参考标准，返回达标状态指示符。

    支持格式:
      - ``> 0.60``  (值 >= 阈值 → 达标)
      - ``< 0.30``  (值 <= 阈值 → 达标)
      - ``-``       (无参考标准，返回空)

    :return: "✅" 达标, "❌" 未达标, "" 无参考
    """
    import re

    ref_str = ref_str.strip()
    if not ref_str or ref_str == "-":
        return ""

    match = re.match(r'([><]=?)\s*([\d.]+)', ref_str)
    if not match:
        return ""

    op, threshold_str = match.groups()
    threshold = float(threshold_str)

    if op in (">", ">="):
        return "✅" if value >= threshold else "❌"
    elif op in ("<", "<="):
        return "✅" if value <= threshold else "❌"
    return ""


def _make_json_safe(obj):
    """递归将不可序列化的对象转换为可 JSON 序列化的格式。"""
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "value"):  # Enum
        return obj.value
    return obj


def _result_to_markdown(result: dict, label: str, ts: str) -> str:
    """将 evaluate_full() 结果渲染为 Markdown。"""
    faith_score = result.get("faithfulness_score", 0) or 0
    hallu_rate = result.get("hallucination_rate", 0) or 0
    comp_score = result.get("completeness_score", 0) or 0
    prec_at_5 = result.get("precision_at_5", 0) or 0
    cit_prec = result.get("citation_precision")
    eval_ms = result.get("evaluation_time_ms", 0) or 0

    lines = [
        f"# RAG 评估结果",
        f"",
        f"- **标签：** {label}",
        f"- **时间：** {ts}",
        f"- **知识点：** {result.get('kp_name', '-')}",
        f"- **查询：** {result.get('query', '-')}",
        f"",
        f"## 汇总",
        f"",
        f"| 指标 | 值 | 参考 | 达标 |",
        f"|------|-----|------|------|",
        f"| Faithfulness | {faith_score:.3f} | > 0.70 | {_check_reference(faith_score, '> 0.70')} |",
        f"| Hallucination Rate | {hallu_rate:.3f} | < 0.30 | {_check_reference(hallu_rate, '< 0.30')} |",
        f"| Completeness | {comp_score:.3f} | > 0.60 | {_check_reference(comp_score, '> 0.60')} |",
        f"| Precision@5 | {prec_at_5:.3f} | > 0.60 | {_check_reference(prec_at_5, '> 0.60')} |",
    ]
    if cit_prec is not None:
        lines.append(f"| Citation Precision | {cit_prec:.3f} | > 0.70 | {_check_reference(cit_prec, '> 0.70')} |")
    lines.extend([
        f"| 评估耗时 | {eval_ms:.0f} ms | - | - |",
        f"",
    ])

    # 检索相关性分布
    labels_list = result.get("relevance_labels", [])
    if labels_list:
        n_high = sum(1 for s in labels_list if s == 2)
        n_partial = sum(1 for s in labels_list if s == 1)
        n_irrelevant = sum(1 for s in labels_list if s == 0)
        lines.extend([
            f"## 检索相关性分布",
            f"",
            f"| 等级 | 数量 |",
            f"|------|------|",
            f"| 高度相关 (2) | {n_high} |",
            f"| 部分相关 (1) | {n_partial} |",
            f"| 无关 (0) | {n_irrelevant} |",
            f"",
        ])

    # Faithfulness 详情
    statements = result.get("faithfulness_statements", [])
    if statements:
        lines.extend([
            f"## 忠实度逐句分析",
            f"",
        ])
        for s in statements[:20]:  # 最多显示 20 条
            icon = "✅" if s.get("verdict") == "supported" else "❌"
            lines.append(f"- {icon} {s.get('text', '')[:120]}")
            if s.get("verdict") == "unsupported" and s.get("evidence"):
                lines.append(f"  - 证据: {s['evidence'][:120]}")
        lines.append("")

    # Completeness 详情
    aspects = result.get("completeness_aspects", [])
    if aspects:
        lines.extend([
            f"## 完整度分析",
            f"",
            f"| 方面 | 覆盖 |",
            f"|------|------|",
        ])
        for a in aspects:
            cov = a.get("coverage", "?")
            emoji = {"covered": "✅", "partial": "⚠️", "missing": "❌"}.get(cov, "")
            lines.append(f"| {emoji} {a.get('aspect', '')[:80]} | {cov} |")
        lines.append("")

    # 问题列表
    issues = result.get("faithfulness_issues", [])
    if issues:
        lines.extend([
            f"## 发现的问题",
            f"",
        ])
        for i, issue in enumerate(issues, 1):
            lines.append(f"{i}. {issue}")
        lines.append("")

    return "\n".join(lines)
