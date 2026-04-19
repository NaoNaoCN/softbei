"""
tests/test_rag.py
RAG 模块（loader / retriever）基础逻辑测试（不依赖向量库）。
"""

import pytest

from backend.rag.loader import split_text


class TestSplitText:
    def test_short_text_no_split(self):
        text = "这是一段短文本。"
        result = split_text(text, chunk_size=512)
        assert result == [text]

    def test_long_text_splits_correctly(self):
        text = "A" * 1000
        chunks = split_text(text, chunk_size=200, overlap=50)
        assert len(chunks) > 1
        # 每个 chunk 长度不超过 chunk_size
        for chunk in chunks:
            assert len(chunk) <= 200

    def test_overlap_preserved(self):
        text = "0123456789" * 20   # 200 chars
        chunks = split_text(text, chunk_size=50, overlap=10)
        # 第二个 chunk 的开头应与第一个 chunk 的结尾有 overlap
        assert chunks[0][-10:] == chunks[1][:10]
