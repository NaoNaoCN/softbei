"""
tests/test_evaluation_metrics.py
指标计算函数的单元测试（纯 Python，无外部依赖）。
"""

import math
import pytest

from backend.evaluation.metrics import (
    precision_at_k,
    recall_at_k,
    mrr,
    ndcg_at_k,
    hit_rate,
    hallucination_rate,
    hallucination_rate_from_statements,
    score_distribution,
    avg_score,
)


# ============================================================
# precision_at_k
# ============================================================

class TestPrecisionAtK:
    def test_normal_k3(self, sample_relevance_labels):
        # [2,2,1,0,2], k=3 → 前3条中3条相关 → 3/3 = 1.0
        assert precision_at_k(sample_relevance_labels, 3) == 1.0

    def test_normal_k5(self, sample_relevance_labels):
        # [2,2,1,0,2], k=5 → 5条中4条相关 → 4/5 = 0.8
        assert precision_at_k(sample_relevance_labels, 5) == 0.8

    def test_k_greater_than_list(self, sample_relevance_labels):
        # [2,2,1,0,2], k=10 → 只用5条, 4/10=0.4
        assert precision_at_k(sample_relevance_labels, 10) == 0.4

    def test_empty_list(self):
        assert precision_at_k([], 5) == 0.0

    def test_k_zero(self, sample_relevance_labels):
        assert precision_at_k(sample_relevance_labels, 0) == 0.0

    def test_k_negative(self, sample_relevance_labels):
        assert precision_at_k(sample_relevance_labels, -1) == 0.0

    def test_all_irrelevant(self):
        assert precision_at_k([0, 0, 0, 0, 0], 3) == 0.0

    def test_all_highly_relevant(self):
        assert precision_at_k([2, 2, 2, 2, 2], 3) == 1.0

    def test_mixed_relevance(self):
        # 部分相关 (1) 也算相关
        assert precision_at_k([1, 1, 0, 2], 3) == pytest.approx(2 / 3)


# ============================================================
# recall_at_k
# ============================================================

class TestRecallAtK:
    def test_normal(self, sample_relevance_labels):
        # 5条中4条相关, total_relevant=4, k=5 → 4/4=1.0
        total_rel = sum(1 for v in sample_relevance_labels if v > 0)
        assert recall_at_k(sample_relevance_labels, total_rel, 5) == 1.0

    def test_k3_partial_recall(self, sample_relevance_labels):
        # total_relevant=4, k=3, 前3条都是相关 → 3/4=0.75
        total_rel = sum(1 for v in sample_relevance_labels if v > 0)
        assert recall_at_k(sample_relevance_labels, total_rel, 3) == 0.75

    def test_total_relevant_zero(self, sample_relevance_labels):
        assert recall_at_k(sample_relevance_labels, 0, 5) == 0.0

    def test_k_zero(self, sample_relevance_labels):
        assert recall_at_k(sample_relevance_labels, 5, 0) == 0.0

    def test_empty_list(self):
        assert recall_at_k([], 3, 5) == 0.0

    def test_total_relevant_greater_than_in_list(self, sample_relevance_labels):
        # total_relevant 设得比实际大 → 召回率偏低但不报错
        assert recall_at_k(sample_relevance_labels, 10, 5) == 0.4


# ============================================================
# mrr
# ============================================================

class TestMRR:
    def test_normal(self, sample_relevance_labels_all):
        # [2,2,1,0,2] → 第一个在第1位 → 1/1=1.0
        # [1,0,0,2,0] → 第一个在第1位 → 1/1=1.0
        # [2,2,2,1,0] → 第一个在第1位 → 1/1=1.0
        # MRR = 1.0
        assert mrr(sample_relevance_labels_all) == 1.0

    def test_first_relevant_at_position_3(self):
        labels = [[0, 0, 2, 1, 0]]  # 第一个相关在第3位 → 1/3
        assert mrr(labels) == pytest.approx(1 / 3)

    def test_no_relevant(self):
        labels = [[0, 0, 0, 0]]
        assert mrr(labels) == 0.0

    def test_empty_input(self):
        assert mrr([]) == 0.0

    def test_multiple_queries_mixed(self):
        labels = [
            [2, 1, 0],    # rank 1 → 1.0
            [0, 0, 2],    # rank 3 → 0.333
            [0, 1, 0],    # rank 2 → 0.5
        ]
        expected = (1.0 + 1 / 3 + 0.5) / 3
        assert mrr(labels) == pytest.approx(expected)


# ============================================================
# ndcg_at_k
# ============================================================

class TestNDCGAtK:
    def test_normal(self, sample_relevance_labels):
        # [2,2,1,0,2], k=5
        result = ndcg_at_k(sample_relevance_labels, 5)
        assert 0.0 <= result <= 1.0

    def test_perfect_ordering(self):
        # 理想排序: 高分在前
        labels = [2, 2, 2, 1, 0]
        result = ndcg_at_k(labels, 5)
        assert result == pytest.approx(1.0)

    def test_bad_ordering(self):
        # 低分在前
        labels = [0, 0, 1, 2, 2]
        result = ndcg_at_k(labels, 5)
        assert result < 1.0

    def test_k_zero(self, sample_relevance_labels):
        assert ndcg_at_k(sample_relevance_labels, 0) == 0.0

    def test_empty_list(self):
        assert ndcg_at_k([], 5) == 0.0

    def test_all_zero(self):
        assert ndcg_at_k([0, 0, 0], 3) == 0.0

    def test_ndcg_increases_with_better_ordering(self):
        good = ndcg_at_k([2, 2, 1, 0, 0], 5)
        bad = ndcg_at_k([0, 0, 1, 2, 2], 5)
        assert good > bad


# ============================================================
# hit_rate
# ============================================================

class TestHitRate:
    def test_all_hit(self, sample_relevance_labels_all):
        assert hit_rate(sample_relevance_labels_all, 3) == 1.0

    def test_one_miss(self):
        labels = [[2, 1, 0], [0, 0, 0]]  # 第2条无相关
        assert hit_rate(labels, 3) == 0.5

    def test_empty_input(self):
        assert hit_rate([], 5) == 0.0

    def test_k_smaller_than_first_relevant(self):
        labels = [[0, 0, 2, 1]]  # 第一个相关在第3位, k=2
        assert hit_rate(labels, 2) == 0.0


# ============================================================
# hallucination_rate
# ============================================================

class TestHallucinationRate:
    def test_from_statements(self, sample_statements):
        # 4 statements, 1 unsupported → 0.25
        assert hallucination_rate_from_statements(sample_statements) == 0.25

    def test_from_statements_all_supported(self):
        stmts = [
            {"text": "a", "verdict": "supported"},
            {"text": "b", "verdict": "supported"},
        ]
        assert hallucination_rate_from_statements(stmts) == 0.0

    def test_from_statements_all_unsupported(self):
        stmts = [
            {"text": "a", "verdict": "unsupported"},
            {"text": "b", "verdict": "unsupported"},
        ]
        assert hallucination_rate_from_statements(stmts) == 1.0

    def test_from_statements_empty(self):
        assert hallucination_rate_from_statements([]) == 0.0

    def test_from_full_result(self, sample_faithfulness_result):
        rate = hallucination_rate(sample_faithfulness_result)
        assert rate == 0.25

    def test_from_empty_result(self):
        assert hallucination_rate({}) == 0.0


# ============================================================
# score_distribution
# ============================================================

class TestScoreDistribution:
    def test_normal(self, sample_scores):
        dist = score_distribution(sample_scores)
        assert dist["min"] == 0.21
        assert dist["max"] == 0.95
        assert 0.2 < dist["p25"] < 0.95
        assert 0.2 < dist["p50"] < 0.95
        assert 0.2 < dist["p75"] < 0.95
        assert 0.2 < dist["p90"] < 0.95

    def test_single_element(self):
        dist = score_distribution([0.75])
        assert dist == {"min": 0.75, "p25": 0.75, "p50": 0.75, "p75": 0.75, "p90": 0.75, "max": 0.75}

    def test_empty(self):
        dist = score_distribution([])
        assert dist["min"] == 0.0
        assert dist["max"] == 0.0

    def test_two_elements(self):
        dist = score_distribution([0.9, 0.1])
        assert dist["min"] == 0.1
        assert dist["max"] == 0.9
        # p50 在两个值之间
        assert dist["p50"] == pytest.approx(0.5)

    def test_ordered_input(self):
        """输入已排序也不应影响结果。"""
        dist = score_distribution([0.1, 0.3, 0.5, 0.7, 0.9])
        assert dist["p50"] == pytest.approx(0.5)

    def test_p50_is_median(self):
        """p50 = 中位数。"""
        dist = score_distribution([1.0, 2.0, 3.0, 4.0, 5.0])
        assert dist["p50"] == 3.0


# ============================================================
# avg_score
# ============================================================

class TestAvgScore:
    def test_normal(self, sample_scores):
        expected = sum(sample_scores) / len(sample_scores)
        assert avg_score(sample_scores) == pytest.approx(expected)

    def test_single(self):
        assert avg_score([0.5]) == 0.5

    def test_empty(self):
        assert avg_score([]) == 0.0

    def test_negative_scores(self):
        assert avg_score([-1.0, 1.0]) == 0.0


# ============================================================
# 边界与异常
# ============================================================

class TestEdgeCases:
    def test_very_large_k(self):
        """k 远大于列表长度时不应报错。"""
        labels = [1, 0]
        # 1/1000 = 0.001
        assert precision_at_k(labels, 1000) == 0.001

    def test_zero_total_relevant(self):
        """total_relevant=0 时 recall 应为 0。"""
        assert recall_at_k([1, 2, 0], 0, 3) == 0.0

    def test_all_zeros_mrr(self):
        """全 0 标签 → MRR 为 0。"""
        assert mrr([[0, 0, 0]]) == 0.0
