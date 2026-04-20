"""
backend/config.py
配置文件加载器，从 configs/config.yaml 读取配置。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class DatabaseConfig:
    """数据库配置"""
    url: str = ""
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 3600


@dataclass
class VectorDBConfig:
    """向量库配置"""
    persist_dir: str = "./chroma_data"
    collection: str = "knowledge_base"


@dataclass
class LLMConfig:
    """LLM 配置"""
    api_key: str = ""
    base_url: str = ""
    model: str = ""


@dataclass
class RAGConfig:
    """RAG 配置"""
    chunk_size: int = 500
    chunk_overlap: int = 50
    embedding_model: str = "BAAI/bge-m3"


@dataclass
class Config:
    """全局配置"""
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    vector_db: VectorDBConfig = field(default_factory=VectorDBConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    rag: RAGConfig = field(default_factory=RAGConfig)


def _resolve_env_vars(value: Any) -> Any:
    """递归解析 ${ENV_VAR} 格式的环境变量引用"""
    if isinstance(value, str):
        if value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.getenv(env_var, "")
        return value
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def _load_yaml_config() -> dict[str, Any]:
    """加载 configs/config.yaml 文件"""
    config_path = Path(__file__).parent.parent / "configs" / "config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw_config = yaml.safe_load(f)

    # 解析环境变量引用（如 ${LLM_API_KEY}）
    return _resolve_env_vars(raw_config)


def _build_config() -> Config:
    """构建配置对象"""
    yaml_config = _load_yaml_config()

    database_data = yaml_config.get("database", {})
    vector_data = yaml_config.get("vector_db", {})
    llm_data = yaml_config.get("llm", {})
    rag_data = yaml_config.get("rag", {})

    return Config(
        database=DatabaseConfig(
            url=database_data.get("url", ""),
            echo=database_data.get("echo", False),
            pool_size=database_data.get("pool_size", 10),
            max_overflow=database_data.get("max_overflow", 20),
            pool_timeout=database_data.get("pool_timeout", 30),
            pool_recycle=database_data.get("pool_recycle", 3600),
        ),
        vector_db=VectorDBConfig(
            persist_dir=vector_data.get("persist_dir", "./chroma_data"),
            collection=vector_data.get("collection", "knowledge_base"),
        ),
        llm=LLMConfig(
            api_key=llm_data.get("api_key", ""),
            base_url=llm_data.get("base_url", ""),
            model=llm_data.get("model", ""),
        ),
        rag=RAGConfig(
            chunk_size=rag_data.get("chunk_size", 500),
            chunk_overlap=rag_data.get("chunk_overlap", 50),
            embedding_model=rag_data.get("embedding_model", "BAAI/bge-m3"),
        ),
    )


# 全局配置实例
config = _build_config()
