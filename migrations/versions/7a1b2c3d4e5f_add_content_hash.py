"""add content_hash column to document_chunk for incremental indexing

在 document_chunk 表添加 content_hash 列 (MD5, 32 字符) 和复合索引
(doc_id, content_hash)，为 Level 3 增量索引更新提供基础能力。

Revision ID: 7a1b2c3d4e5f
Revises: 6f9a2b3c4d5e
Create Date: 2026-05-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7a1b2c3d4e5f'
down_revision: Union[str, None] = '6f9a2b3c4d5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 添加 content_hash 列
    #    nullable=True: legacy 数据为 NULL，首次增量索引时自动回填
    op.add_column(
        'document_chunk',
        sa.Column('content_hash', sa.String(32), nullable=True),
    )

    # 2. 创建复合索引，加速 "查某文档的所有 (chunk_id, content_hash)" 查询
    #    可支持 index-only scan，无需回表
    op.create_index(
        'ix_document_chunk_doc_id_hash',
        'document_chunk',
        ['doc_id', 'content_hash'],
    )


def downgrade() -> None:
    op.drop_index('ix_document_chunk_doc_id_hash', table_name='document_chunk')
    op.drop_column('document_chunk', 'content_hash')
