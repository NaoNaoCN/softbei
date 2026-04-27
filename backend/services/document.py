"""
backend/services/document.py
PDF 文档导入服务：保存文件、解析内容、索引到向量库。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.crud import insert
from backend.db.models import ResourceMeta
from backend.rag import loader, indexer as rag_indexer


# ----------------------------------------------------------
# 配置
# ----------------------------------------------------------

UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploaded_docs"
UPLOAD_DIR.mkdir(exist_ok=True)


# ----------------------------------------------------------
# 核心接口
# ----------------------------------------------------------

async def import_pdf(
    file_path: str,
    user_id: uuid.UUID,
    title: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> dict:
    """
    导入 PDF 文档：保存文件 → 解析为文本块 → 索引到向量库 → 创建资源记录。

    :param file_path:  临时保存的 PDF 文件路径
    :param user_id:    上传用户 ID
    :param title:      自定义文档标题，默认使用文件名
    :param db:         数据库会话（可选，无会话时仅解析和索引）
    :return:           {"doc_id": str, "chunks": int, "resource_id": uuid}
    """
    path = Path(file_path)
    doc_id = f"pdf_{uuid.uuid4().hex[:12]}"
    doc_title = title or path.stem

    # 1. 加载并解析 PDF
    chunks = loader.load_file(str(path), doc_id=doc_id)

    # 2. 索引到向量库
    indexed_count = 0
    if chunks:
        indexed_count = await rag_indexer.index_chunks(chunks)

    # 3. 创建资源记录（可选）
    resource_id = None
    if db is not None:
        resource = await insert(
            db, ResourceMeta,
            data={
                "user_id": user_id,
                "kp_id": doc_id,
                "resource_type": "doc",
                "title": doc_title,
                "content": f"已导入 PDF：{path.name}，共 {len(chunks)} 个文本块",
            },
        )
        resource_id = resource.id

    return {
        "doc_id": doc_id,
        "title": doc_title,
        "file_name": path.name,
        "chunks": len(chunks),
        "indexed": indexed_count,
        "resource_id": str(resource_id) if resource_id else None,
    }


def save_uploaded_file(content: bytes, original_name: str) -> str:
    """
    将上传的文件内容保存到 upload 目录。

    :param content:        文件字节内容
    :param original_name:  原始文件名
    :return:               保存后的文件路径
    """
    suffix = Path(original_name).suffix.lower()
    if suffix != ".pdf":
        raise ValueError("仅支持 PDF 文件")

    unique_name = f"{uuid.uuid4().hex[:12]}_{original_name}"
    dest = UPLOAD_DIR / unique_name
    dest.write_bytes(content)
    return str(dest)