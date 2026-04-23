"""
backend/config.py
配置文件加载器，从 configs/config.yaml 读取配置。
支持 ${ENV_VAR} 格式环境变量引用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ===========================================================
# 配置数据类
# ===========================================================

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
    provider: str = "spark"


@dataclass
class EmbeddingConfig:
    """Embedding 配置"""
    model: str = "BAAI/bge-m3"
    use_spark: bool = False


@dataclass
class RAGConfig:
    """RAG 配置"""
    chunk_size: int = 500
    chunk_overlap: int = 50


@dataclass
class JWTConfig:
    """JWT 配置"""
    secret: str = ""
    algorithm: str = "HS256"
    expire_hours: int = 24


@dataclass
class Config:
    """全局配置"""
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    vector_db: VectorDBConfig = field(default_factory=VectorDBConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    rag: RAGConfig = field(default_factory=RAGConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    jwt: JWTConfig = field(default_factory=JWTConfig)


# ===========================================================
# 环境变量解析
# ===========================================================

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


# ===========================================================
# 配置加载
# ===========================================================

def _load_yaml_config() -> dict[str, Any]:
    """加载 configs/config.yaml 文件"""
    config_path = Path(__file__).parent.parent / "configs" / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        raw_config = yaml.safe_load(f)
    return _resolve_env_vars(raw_config)


def _build_config() -> Config:
    """构建配置对象"""
    yaml_config = _load_yaml_config()

    db = yaml_config.get("database", {})
    vec = yaml_config.get("vector_db", {})
    llm = yaml_config.get("llm", {})
    rag = yaml_config.get("rag", {})
    emb = yaml_config.get("embedding", {})
    jwt = yaml_config.get("jwt", {})

    return Config(
        database=DatabaseConfig(
            url=db.get("url", ""),
            echo=db.get("echo", False),
            pool_size=db.get("pool_size", 10),
            max_overflow=db.get("max_overflow", 20),
            pool_timeout=db.get("pool_timeout", 30),
            pool_recycle=db.get("pool_recycle", 3600),
        ),
        vector_db=VectorDBConfig(
            persist_dir=vec.get("persist_dir", "./chroma_data"),
            collection=vec.get("collection", "knowledge_base"),
        ),
        llm=LLMConfig(
            api_key=llm.get("api_key", ""),
            base_url=llm.get("base_url", ""),
            model=llm.get("model", ""),
            provider=llm.get("provider", "spark"),
        ),
        rag=RAGConfig(
            chunk_size=rag.get("chunk_size", 500),
            chunk_overlap=rag.get("chunk_overlap", 50),
        ),
        embedding=EmbeddingConfig(
            model=emb.get("model", "BAAI/bge-m3"),
            use_spark=emb.get("use_spark", False),
        ),
        jwt=JWTConfig(
            secret=jwt.get("secret", ""),
            algorithm=jwt.get("algorithm", "HS256"),
            expire_hours=jwt.get("expire_hours", 24),
        ),
    )


# ===========================================================
# 全局单例
# ===========================================================

config = _build_config()
