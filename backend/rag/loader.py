"""
backend/rag/loader.py
文档加载器：将本地文件（PDF / DOCX / Markdown / TXT）解析为纯文本块，
并附加结构化元数据，供后续索引使用。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from langchain_community.document_loaders import (
    PyPDFLoader,           # PDF 加载
    UnstructuredWordDocumentLoader,  # DOCX/DOC 加载
    TextLoader,            # TXT 加载
)
from langchain_core.documents import Document

from backend.config import config


# ----------------------------------------------------------
# 数据结构
# ----------------------------------------------------------

class TextChunk:
    """单个文本块，携带来源元数据。"""
    chunk_id: str               # 唯一标识，格式：{doc_id}_{chunk_index}
    text: str                   # 纯文本内容
    doc_id: str                 # 所属文档 ID
    source_path: str            # 原始文件路径
    page: Optional[int] = None  # 页码（PDF）
    section: Optional[str] = None  # 章节标题
    metadata: dict = {}         # 额外元数据

    def to_langchain_doc(self) -> Document:
        """转换为 LangChain Document。"""
        return Document(
            page_content=self.text,
            metadata={
                "chunk_id": self.chunk_id,
                "doc_id": self.doc_id,
                "source": self.source_path,
                "page": self.page,
                "section": self.section,
                **self.metadata,
            }
        )

    @classmethod
    def from_langchain_doc(cls, doc: Document, doc_id: str, chunk_index: int) -> "TextChunk":
        """从 LangChain Document 转换。"""
        meta = doc.metadata
        return cls(
            chunk_id=f"{doc_id}_{chunk_index}",
            text=doc.page_content,
            doc_id=doc_id,
            source_path=meta.get("source", ""),
            page=meta.get("page"),
            section=meta.get("section"),
            metadata={k: v for k, v in meta.items()
                      if k not in ("chunk_id", "doc_id", "source", "page", "section")},
        )


# ----------------------------------------------------------
# 核心接口
# ----------------------------------------------------------

def load_file(file_path: str | Path, doc_id: Optional[str] = None) -> list[TextChunk]:
    """
    加载单个文件，自动根据扩展名选择解析器，返回文本块列表。

    支持格式：.pdf / .docx / .doc / .md / .txt
    :param file_path: 文件路径
    :param doc_id:    文档 ID，默认使用文件名（无扩展名）
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()
    _doc_id = doc_id or path.stem

    if suffix == ".pdf":
        return _load_pdf(path, _doc_id)
    elif suffix in (".docx", ".doc"):
        return _load_docx(path, _doc_id)
    elif suffix == ".md":
        return _load_markdown(path, _doc_id)
    elif suffix == ".txt":
        return _load_txt(path, _doc_id)
    else:
        raise ValueError(f"Unsupported file format: {suffix}")


def load_directory(
    dir_path: str | Path,
    glob_pattern: str = "**/*",
    recursive: bool = True,
) -> list[TextChunk]:
    """
    递归扫描目录，加载所有支持格式的文档。

    :param dir_path:      目录路径
    :param glob_pattern:  文件匹配模式
    :param recursive:     是否递归扫描子目录
    :return:              所有文档块列表
    """
    supported = {".pdf", ".docx", ".doc", ".md", ".txt"}
    chunks: list[TextChunk] = []

    base_path = Path(dir_path)
    pattern = glob_pattern if recursive else glob_pattern.replace("**/", "")

    for p in base_path.glob(pattern):
        if p.is_file() and p.suffix.lower() in supported:
            try:
                file_chunks = load_file(p)
                chunks.extend(file_chunks)
            except Exception as e:
                print(f"[loader] Skipping {p}: {e}")

    return chunks


def split_text(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """
    将长文本按 chunk_size（字符数）切分，相邻块保留 overlap 字符的上下文。

    :param text:        原始文本
    :param chunk_size:  每块字符数，默认使用配置值
    :param overlap:     重叠字符数，默认使用配置值
    :return:            文本块列表
    """
    chunk_size = chunk_size or config.rag.chunk_size
    overlap = overlap or config.rag.chunk_overlap

    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start += chunk_size - overlap

    return chunks


def docs_to_chunks(docs: list[Document], doc_id: str) -> list[TextChunk]:
    """
    将 LangChain Document 列表转换为 TextChunk 列表，
    并根据配置进行二次切分。

    :param docs:    LangChain Document 列表
    :param doc_id:  文档 ID
    :return:        TextChunk 列表
    """
    chunks: list[TextChunk] = []
    chunk_index = 0

    for doc in docs:
        text = doc.page_content.strip()
        if not text:
            continue

        # 先按配置大小切分
        sub_chunks = split_text(text)

        for sub_chunk in sub_chunks:
            chunk = TextChunk.from_langchain_doc(doc, doc_id, chunk_index)
            chunk.text = sub_chunk
            chunk.chunk_id = f"{doc_id}_{chunk_index}"
            chunks.append(chunk)
            chunk_index += 1

    return chunks


# ----------------------------------------------------------
# 私有实现：使用 LangChain Document Loader
# ----------------------------------------------------------

def _load_pdf(path: Path, doc_id: str) -> list[TextChunk]:
    """
    使用 PyPDFLoader 解析 PDF，按页切分。

    :param path:   PDF 文件路径
    :param doc_id: 文档 ID
    :return:       TextChunk 列表
    """
    try:
        loader = PyPDFLoader(str(path))
        docs = loader.load()
        return docs_to_chunks(docs, doc_id)
    except Exception as e:
        raise RuntimeError(f"Failed to load PDF {path}: {e}") from e


def _load_docx(path: Path, doc_id: str) -> list[TextChunk]:
    """
    使用 UnstructuredWordDocumentLoader 解析 Word 文档，
    按段落聚合后切分。

    :param path:   DOCX/DOC 文件路径
    :param doc_id: 文档 ID
    :return:       TextChunk 列表
    """
    try:
        loader = UnstructuredWordDocumentLoader(str(path), mode="elements")
        docs = loader.load()
        return docs_to_chunks(docs, doc_id)
    except Exception as e:
        raise RuntimeError(f"Failed to load DOCX {path}: {e}") from e


def _load_markdown(path: Path, doc_id: str) -> list[TextChunk]:
    """
    解析 Markdown 文件，按标题（##）切分章节，
    对每节再进行文本切分。

    :param path:   Markdown 文件路径
    :param doc_id: 文档 ID
    :return:       TextChunk 列表
    """
    try:
        # 使用 TextLoader 读取原始内容
        loader = TextLoader(str(path), encoding="utf-8")
        docs = loader.load()

        if not docs:
            return []

        full_text = docs[0].page_content
        sections = _split_markdown_by_headers(full_text)

        chunks: list[TextChunk] = []
        chunk_index = 0

        for section_title, section_text in sections:
            # 更新文档元数据中的 section
            doc = docs[0]
            doc.metadata["section"] = section_title

            # 对每节进行切分
            sub_chunks = split_text(section_text)
            for sub_chunk in sub_chunks:
                chunk = TextChunk(
                    chunk_id=f"{doc_id}_{chunk_index}",
                    text=sub_chunk,
                    doc_id=doc_id,
                    source_path=str(path),
                    section=section_title,
                    metadata={},
                )
                chunks.append(chunk)
                chunk_index += 1

        return chunks

    except Exception as e:
        raise RuntimeError(f"Failed to load Markdown {path}: {e}") from e


def _load_txt(path: Path, doc_id: str) -> list[TextChunk]:
    """
    读取纯文本，按段落或 split_text 切分。

    :param path:   TXT 文件路径
    :param doc_id: 文档 ID
    :return:       TextChunk 列表
    """
    try:
        loader = TextLoader(str(path), encoding="utf-8")
        docs = loader.load()
        return docs_to_chunks(docs, doc_id)
    except Exception as e:
        raise RuntimeError(f"Failed to load TXT {path}: {e}") from e


# ----------------------------------------------------------
# 私有辅助函数
# ----------------------------------------------------------

def _split_markdown_by_headers(text: str) -> list[tuple[str, str]]:
    """
    按 Markdown 标题（## ）切分章节。

    :param text: 原始 Markdown 文本
    :return:     [(章节标题, 章节内容), ...] 列表
    """
    # 匹配 ## 标题（不含代码块内的标题）
    # 先去除代码块
    code_block_pattern = re.compile(r'```[\s\S]*?```')
    text_without_code = code_block_pattern.sub('[CODE_BLOCK]', text)

    # 匹配 ## 标题行
    header_pattern = re.compile(r'^##\s+(.+)$', re.MULTILINE)
    headers = list(header_pattern.finditer(text_without_code))

    if not headers:
        # 没有标题，返回整篇作为"无标题"章节
        # 还原代码块
        text = text_without_code.replace('[CODE_BLOCK]', '```\n...\n```')
        return [("无标题", text.strip())]

    sections: list[tuple[str, str]] = []

    for i, match in enumerate(headers):
        title = match.group(1).strip()
        start = match.end()
        # 下一个标题之前，或文件末尾
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text_without_code)

        section_text = text_without_code[start:end].strip()
        # 还原代码块
        section_text = section_text.replace('[CODE_BLOCK]', '```\n...\n```')

        if section_text:
            sections.append((title, section_text))

    return sections


# ----------------------------------------------------------
# 便捷函数：直接返回 LangChain Document
# ----------------------------------------------------------

def load_file_as_documents(file_path: str | Path, doc_id: str | None = None) -> list[Document]:
    """
    加载文件并直接返回 LangChain Document 列表（跳过 TextChunk 转换）。

    适用于需要保留 LangChain Document 完整元数据的场景。

    :param file_path: 文件路径
    :param doc_id:    文档 ID
    :return:          Document 列表
    """
    chunks = load_file(file_path, doc_id)
    return [chunk.to_langchain_doc() for chunk in chunks]


def load_directory_as_documents(
    dir_path: str | Path,
    glob_pattern: str = "**/*",
    recursive: bool = True,
) -> list[Document]:
    """
    加载目录并直接返回 LangChain Document 列表。

    :param dir_path:      目录路径
    :param glob_pattern:  文件匹配模式
    :param recursive:      是否递归
    :return:               Document 列表
    """
    chunks = load_directory(dir_path, glob_pattern, recursive)
    return [chunk.to_langchain_doc() for chunk in chunks]
