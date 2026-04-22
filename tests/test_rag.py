"""
tests/test_rag.py
RAG 模块（loader / retriever）测试。
"""

import pytest
import tempfile
from pathlib import Path

from backend.rag.loader import (
    split_text,
    _split_markdown_by_headers,
    load_file,
    load_directory,
    TextChunk,
)


class TestSplitText:
    """split_text 函数的单元测试。"""

    def test_short_text_no_split(self):
        """短文本不应被切分。"""
        text = "这是一段短文本。"
        result = split_text(text, chunk_size=512)
        assert result == [text]

    def test_long_text_splits_correctly(self):
        """长文本应被正确切分为多个块。"""
        text = "A" * 1000
        chunks = split_text(text, chunk_size=200, overlap=50)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 200

    def test_overlap_preserved(self):
        """相邻块之间应保留 overlap。"""
        text = "0123456789" * 20   # 200 chars
        chunks = split_text(text, chunk_size=50, overlap=10)
        # 第二个 chunk 的开头应与第一个 chunk 的结尾有 overlap
        assert chunks[0][-10:] == chunks[1][:10]

    def test_exact_size_text(self):
        """长度等于 chunk_size 的文本不应被切分。"""
        text = "A" * 500
        result = split_text(text, chunk_size=500)
        assert len(result) == 1
        assert result[0] == text

    def test_empty_text(self):
        """空文本应返回空列表。"""
        result = split_text("", chunk_size=500)
        assert result == []

    def test_overlap_clamped_to_chunk_size(self):
        """overlap 超过 chunk_size 时应被限制。"""
        text = "A" * 1000
        chunks = split_text(text, chunk_size=100, overlap=150)
        # overlap 会被限制为 chunk_size - 1，不应无限循环
        assert all(len(c) <= 100 for c in chunks)
        assert len(chunks) > 1


class TestSplitMarkdownByHeaders:
    """_split_markdown_by_headers 函数的单元测试。"""

    def test_single_section_no_headers(self):
        """无标题的 Markdown 应返回单个"无标题"章节。"""
        text = "这是一些内容。\n\n第二段文字。"
        sections = _split_markdown_by_headers(text)
        assert len(sections) == 1
        assert sections[0][0] == "无标题"

    def test_multiple_headers(self):
        """多个 ## 标题应正确分割章节。"""
        text = """## 第一章
这是第一章的内容。
## 第二章
这是第二章的内容。
## 第三章
这是第三章的内容。
"""
        sections = _split_markdown_by_headers(text)
        assert len(sections) == 3
        assert sections[0][0] == "第一章"
        assert sections[1][0] == "第二章"
        assert sections[2][0] == "第三章"
        assert "第一章" in sections[0][1]
        assert "第二章" in sections[1][1]

    def test_header_with_code_blocks(self):
        """代码块内的 ## 不应被识别为标题。"""
        text = """## 标题
这是正文。
```python
## 这不是标题
print("hello")
```
"""
        sections = _split_markdown_by_headers(text)
        # 应该只有一个标题
        assert len(sections) == 1
        assert sections[0][0] == "标题"

    def test_consecutive_headers(self):
        """连续标题（有正文）应被正确处理。"""
        text = """## 标题A
这是标题A的内容。

## 标题B
这是标题B的内容。
"""
        sections = _split_markdown_by_headers(text)
        assert len(sections) == 2
        assert sections[0][0] == "标题A"
        assert "标题A的内容" in sections[0][1]
        assert sections[1][0] == "标题B"
        assert "标题B的内容" in sections[1][1]

    def test_deeply_nested_headers(self):
        """仅识别 ## 标题，不识别 ### 等更深的标题。"""
        text = """## 主标题
### 子标题（不应独立）
内容文字。
"""
        sections = _split_markdown_by_headers(text)
        assert len(sections) == 1
        assert sections[0][0] == "主标题"
        assert "子标题" in sections[0][1]


class TestLoadFile:
    """load_file 函数的集成测试（需要真实文件）。"""

    def test_load_txt_file(self, tmp_path):
        """应正确加载 TXT 文件。"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("第一段。\n\n第二段。\n\n第三段。", encoding="utf-8")

        chunks = load_file(test_file)
        assert len(chunks) >= 1
        assert all(isinstance(c, TextChunk) for c in chunks)
        assert chunks[0].doc_id == "test"
        assert chunks[0].source_path == str(test_file)

    def test_load_markdown_file(self, tmp_path):
        """应正确加载 Markdown 文件并按章节切分。"""
        test_file = tmp_path / "test.md"
        test_file.write_text("""# 标题

## 第一章
这是第一章的内容。

## 第二章
这是第二章的内容。
""", encoding="utf-8")

        chunks = load_file(test_file)
        assert len(chunks) >= 2
        sections = [c.section for c in chunks]
        assert "第一章" in sections
        assert "第二章" in sections

    def test_unsupported_format_raises(self, tmp_path):
        """不支持的文件格式应抛出 ValueError。"""
        test_file = tmp_path / "test.xyz"
        test_file.write_text("内容", encoding="utf-8")

        with pytest.raises(ValueError, match="Unsupported file format"):
            load_file(test_file)

    def test_nonexistent_file_raises(self):
        """不存在的文件应抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            load_file("/nonexistent/path/file.txt")

    def test_custom_doc_id(self, tmp_path):
        """应支持自定义 doc_id。"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("内容", encoding="utf-8")

        chunks = load_file(test_file, doc_id="custom_id")
        assert chunks[0].doc_id == "custom_id"


class TestLoadDirectory:
    """load_directory 函数的集成测试。"""

    def test_load_directory_recursive(self, tmp_path):
        """应递归加载目录中的所有支持的文件。"""
        # 创建测试文件
        (tmp_path / "file1.txt").write_text("内容1", encoding="utf-8")
        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()
        (sub_dir / "file2.txt").write_text("内容2", encoding="utf-8")

        chunks = load_directory(tmp_path)
        assert len(chunks) == 2

    def test_load_directory_non_recursive(self, tmp_path):
        """recursive=False 时不应加载子目录。"""
        (tmp_path / "file1.txt").write_text("内容1", encoding="utf-8")
        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()
        (sub_dir / "file2.txt").write_text("内容2", encoding="utf-8")

        chunks = load_directory(tmp_path, recursive=False)
        assert len(chunks) == 1

    def test_load_directory_ignores_unsupported(self, tmp_path):
        """应忽略不支持的文件格式。"""
        (tmp_path / "supported.txt").write_text("支持", encoding="utf-8")
        (tmp_path / "unsupported.xyz").write_text("不支持", encoding="utf-8")

        chunks = load_directory(tmp_path)
        assert len(chunks) == 1

    def test_load_empty_directory(self, tmp_path):
        """空目录应返回空列表。"""
        chunks = load_directory(tmp_path)
        assert chunks == []


class TestTextChunk:
    """TextChunk 数据类的单元测试。"""

    def test_chunk_creation(self):
        """应正确创建 TextChunk。"""
        chunk = TextChunk(
            chunk_id="doc1_0",
            text="这是文本内容。",
            doc_id="doc1",
            source_path="/path/to/file.txt",
            page=None,
            section="第一章",
        )
        assert chunk.chunk_id == "doc1_0"
        assert chunk.text == "这是文本内容。"
        assert chunk.doc_id == "doc1"
        assert chunk.section == "第一章"

    def test_to_langchain_doc(self):
        """应正确转换为 LangChain Document。"""
        chunk = TextChunk(
            chunk_id="doc1_0",
            text="文本内容",
            doc_id="doc1",
            source_path="/path/file.txt",
            page=1,
            section="章节",
        )
        doc = chunk.to_langchain_doc()
        assert doc.page_content == "文本内容"
        assert doc.metadata["chunk_id"] == "doc1_0"
        assert doc.metadata["doc_id"] == "doc1"
        assert doc.metadata["page"] == 1
        assert doc.metadata["section"] == "章节"

    def test_from_langchain_doc(self):
        """应正确从 LangChain Document 转换。"""
        from langchain_core.documents import Document

        doc = Document(
            page_content="文档内容",
            metadata={
                "source": "/path/file.txt",
                "page": 2,
                "section": "小节",
                "extra_key": "extra_value",
            }
        )
        chunk = TextChunk.from_langchain_doc(doc, "doc2", 5)

        assert chunk.chunk_id == "doc2_5"
        assert chunk.text == "文档内容"
        assert chunk.doc_id == "doc2"
        assert chunk.source_path == "/path/file.txt"
        assert chunk.page == 2
        assert chunk.section == "小节"
        assert chunk.metadata.get("extra_key") == "extra_value"
