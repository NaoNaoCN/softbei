"""
backend/rag/loader.py
文档加载器：将本地文件（PDF / DOCX / Markdown / TXT）解析为纯文本块，
并附加结构化元数据，供后续索引使用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ----------------------------------------------------------
# 数据结构
# ----------------------------------------------------------

@dataclass
class TextChunk:
    """单个文本块，携带来源元数据。"""
    chunk_id: str               # 唯一标识，格式：{doc_id}_{chunk_index}
    text: str                   # 纯文本内容
    doc_id: str                 # 所属文档 ID
    source_path: str            # 原始文件路径
    page: Optional[int] = None  # 页码（PDF）
    section: Optional[str] = None  # 章节标题
    metadata: dict = field(default_factory=dict)


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
    """
    supported = {".pdf", ".docx", ".doc", ".md", ".txt"}
    chunks: list[TextChunk] = []
    for p in Path(dir_path).glob(glob_pattern):
        if p.is_file() and p.suffix.lower() in supported:
            try:
                chunks.extend(load_file(p))
            except Exception as e:
                # 跳过解析失败的文件，记录日志
                print(f"[loader] Skipping {p}: {e}")
    return chunks


def split_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[str]:
    """
    将长文本按 chunk_size（字符数）切分，相邻块保留 overlap 字符的上下文。
    """
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


# ----------------------------------------------------------
# 私有实现（stub）
# ----------------------------------------------------------

def _load_pdf(path: Path, doc_id: str) -> list[TextChunk]:
    """使用 pypdf 解析 PDF，按页切分并进一步 split_text。"""
    # TODO: from pypdf import PdfReader; ...
    raise NotImplementedError(f"PDF loading not implemented: {path}")


def _load_docx(path: Path, doc_id: str) -> list[TextChunk]:
    """使用 python-docx 解析 Word 文档，按段落聚合后 split_text。"""
    # TODO: from docx import Document; ...
    raise NotImplementedError(f"DOCX loading not implemented: {path}")


def _load_markdown(path: Path, doc_id: str) -> list[TextChunk]:
    """按 Markdown 标题（##）切分章节，对每节再 split_text。"""
    # TODO: 正则匹配 ## 标题，逐节处理
    raise NotImplementedError(f"Markdown loading not implemented: {path}")


def _load_txt(path: Path, doc_id: str) -> list[TextChunk]:
    """读取纯文本，按段落或 split_text 切分。"""
    # TODO: path.read_text(encoding='utf-8') + split_text
    raise NotImplementedError(f"TXT loading not implemented: {path}")
