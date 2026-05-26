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
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
load_dotenv(Path(__file__).parent.parent / ".env")


# ===========================================================
# 配置数据类
# ===========================================================

@dataclass
class LLMRetryConfig:
    """LLM 调用重试策略"""
    max_attempts: int = 5
    backoff_multiplier: int = 2
    backoff_min_seconds: int = 3
    backoff_max_seconds: int = 30


@dataclass
class LLMTimeoutConfig:
    """LLM HTTP 超时配置"""
    connect: int = 10
    read: int = 120
    write: int = 30
    pool: int = 10


@dataclass
class LLMProviderConfig:
    """单个 LLM Provider 配置"""
    base_url: str = ""
    default_model: str = ""


@dataclass
class LLMProvidersConfig:
    """所有 LLM Provider 配置"""
    spark: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    deepseek: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    qwen: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    openai: LLMProviderConfig = field(default_factory=LLMProviderConfig)


@dataclass
class LLMConfig:
    """LLM 配置"""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    provider: str = "qwen"
    default_max_tokens: int = 2048
    retry: LLMRetryConfig = field(default_factory=LLMRetryConfig)
    timeout: LLMTimeoutConfig = field(default_factory=LLMTimeoutConfig)
    providers: LLMProvidersConfig = field(default_factory=LLMProvidersConfig)


@dataclass
class DatabaseConfig:
    """数据库配置"""
    url: str = ""
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 3600
    command_timeout: int = 60


@dataclass
class VectorDBConfig:
    """向量库配置"""
    collection: str = "knowledge_base"


@dataclass
class EmbeddingConfig:
    """Embedding 配置"""
    use_spark: bool = True
    concurrency: int = 8
    api_model: str = "text-embedding-v4"
    api_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    timeout_read: int = 60
    timeout_connect: int = 10
    timeout_write: int = 30
    timeout_pool: int = 10
    index_batch_size: int = 128
    vector_dimension: int = 1024


@dataclass
class ParentChunkingConfig:
    """父子切割配置"""
    enabled: bool = False
    parent_max_chars: int = 2000
    child_chunk_size: int | None = None   # None = 使用 rag.chunk_size
    child_chunk_overlap: int = 100
    score_weight: str = "max"             # "max"（取子块最高分）| "mean"（子块均分）


@dataclass
class RAGConfig:
    """RAG 配置"""
    chunk_size: int = 500
    chunk_overlap: int = 50
    n_results: int = 5
    score_threshold: float = 0.5
    context_max_tokens: int = 3000
    max_sections_before_coarse_split: int = 50
    parent_chunking: ParentChunkingConfig = field(default_factory=ParentChunkingConfig)
    # Query Rewrite 子配置
    query_rewrite_enabled: bool = True
    query_rewrite_decontextualize: bool = True
    query_rewrite_profile_aware: bool = True
    query_rewrite_multi_query: bool = False
    query_rewrite_multi_query_count: int = 3
    query_rewrite_temperature: float = 0.1
    query_rewrite_max_tokens: int = 150


@dataclass
class TokenEstimationConfig:
    """Token 估算系数"""
    cn_chars_per_token: float = 1.5
    en_chars_per_token: float = 4.0


@dataclass
class ChatConfig:
    """对话配置"""
    max_turns: int = 10
    history_max_tokens: int = 4000
    message_max_length: int = 4096
    session_expiry_days: int = 30
    cleanup_interval_hours: int = 24
    auto_title_max_chars: int = 15
    auto_title_message_truncate: int = 200
    auto_title_max_tokens: int = 30
    auto_title_final_length: int = 20
    token_estimation: TokenEstimationConfig = field(default_factory=TokenEstimationConfig)


@dataclass
class KnowledgeGraphConfig:
    """知识图谱构建配置"""
    llm_concurrency: int = 10
    max_batches: int = 30
    toc_max_items: int = 100
    batch_chars_limit: int = 12000
    text_truncate_chars: int = 6000
    node_extraction_max_tokens: int = 4000
    edge_batch_size: int = 40
    edge_overlap: int = 10
    section_merge_min_chars: int = 200


@dataclass
class GenerationQuizConfig:
    """题目生成 — 弱项阈值与配比"""
    weak_threshold_high: int = 5
    weak_threshold_mid: int = 2
    counts_high: list[int] = field(default_factory=lambda: [3, 2, 2])
    counts_mid: list[int] = field(default_factory=lambda: [2, 1, 1])
    counts_default: list[int] = field(default_factory=lambda: [2, 1, 1])


@dataclass
class GenerationConfig:
    """资源生成配置"""
    default_num_questions: int = 4
    max_questions: int = 20
    mindmap_max_depth: int = 4
    mindmap_max_children: int = 6
    quiz: GenerationQuizConfig = field(default_factory=GenerationQuizConfig)


@dataclass
class StorageCleanupConfig:
    """文档存储清理配置"""
    enabled: bool = True
    retention_days: int = 30
    orphan_retention_days: int = 7
    interval_hours: int = 24
    min_file_age_seconds: int = 300


@dataclass
class StorageConfig:
    """文档存储配置"""
    upload_dir: str = "uploaded_docs"
    knowledge_base_dir: str = "knowledge_base/ai_intro"
    supported_extensions: list[str] = field(default_factory=lambda: [".pdf", ".docx", ".doc", ".md", ".txt"])
    doc_id_hex_length: int = 12
    cleanup: StorageCleanupConfig = field(default_factory=StorageCleanupConfig)


@dataclass
class LoggingConfig:
    """日志配置"""
    dir: str = "logs"
    retention_days: int = 30
    error_retention_days: int = 90
    trace_id_length: int = 8


@dataclass
class JWTConfig:
    """JWT 配置"""
    secret: str = ""
    algorithm: str = "HS256"
    expire_hours: int = 24


# ===========================================================
# Agent 配置
# ===========================================================

@dataclass
class ClarifyAgentConfig:
    """Clarify Agent 配置"""
    temperature: float = 0.7


@dataclass
class CodeAgentConfig:
    """Code Agent 配置"""
    temperature: float = 0.7
    max_tokens: int = 5000


@dataclass
class DocAgentConfig:
    """Doc Agent 配置"""
    temperature: float = 0.7
    max_tokens: int = 4000


@dataclass
class MindmapAgentConfig:
    """Mindmap Agent 配置"""
    temperature: float = 0.5
    max_tokens: int = 2000


@dataclass
class PlannerAgentConfig:
    """Planner Agent 配置"""
    intent_temperature: float = 0.0
    classify_temperature: float = 0.1
    smart_plan_temperature: float = 0.3
    history_lookback_messages: int = 6
    fallback_kp_id_length: int = 50
    smart_plan_default_types: list[str] = field(default_factory=lambda: ["doc", "quiz"])


@dataclass
class ProfileAgentConfig:
    """Profile Agent 配置"""
    extract_temperature: float = 0.1
    intent_temperature: float = 0.0
    clarify_temperature: float = 0.7
    goal_summary_temperature: float = 0.3
    max_goal_questions: int = 50
    history_max_versions: int = 10


@dataclass
class QuizAgentConfig:
    """Quiz Agent 配置"""
    temperature: float = 0.6
    max_tokens: int = 3000


@dataclass
class RecommendAgentConfig:
    """Recommend Agent 配置"""
    temperature: float = 0.7
    max_tokens: int = 2000
    min_recommendations: int = 3
    max_recommendations: int = 5


@dataclass
class SafetyAgentConfig:
    """Safety Agent 配置"""
    temperature: float = 0.1
    max_tokens: int = 300
    max_ref_docs: int = 3
    draft_preview_chars: int = 500


@dataclass
class SummaryAgentConfig:
    """Summary Agent 配置"""
    temperature: float = 0.7
    max_tokens: int = 1200
    target_words_min: int = 300
    target_words_max: int = 500


@dataclass
class AgentsConfig:
    """所有 Agent 配置汇总"""
    clarify: ClarifyAgentConfig = field(default_factory=ClarifyAgentConfig)
    code: CodeAgentConfig = field(default_factory=CodeAgentConfig)
    doc: DocAgentConfig = field(default_factory=DocAgentConfig)
    mindmap: MindmapAgentConfig = field(default_factory=MindmapAgentConfig)
    planner: PlannerAgentConfig = field(default_factory=PlannerAgentConfig)
    profile: ProfileAgentConfig = field(default_factory=ProfileAgentConfig)
    quiz: QuizAgentConfig = field(default_factory=QuizAgentConfig)
    recommend: RecommendAgentConfig = field(default_factory=RecommendAgentConfig)
    safety: SafetyAgentConfig = field(default_factory=SafetyAgentConfig)
    summary: SummaryAgentConfig = field(default_factory=SummaryAgentConfig)


# ===========================================================
# 其他新增配置
# ===========================================================

@dataclass
class PaginationConfig:
    """分页配置"""
    default_limit: int = 20
    quiz_attempts_limit: int = 50


@dataclass
class ServerConfig:
    """服务配置"""
    version: str = "0.1.0"
    cors_origins: list[str] = field(default_factory=lambda: ["*"])


@dataclass
class AuthConfig:
    """认证配置"""
    bcrypt_rounds: int = 12


# ===========================================================
# 全局配置汇总
# ===========================================================

@dataclass
class Config:
    """全局配置"""
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    vector_db: VectorDBConfig = field(default_factory=VectorDBConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    rag: RAGConfig = field(default_factory=RAGConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    chat: ChatConfig = field(default_factory=ChatConfig)
    knowledge_graph: KnowledgeGraphConfig = field(default_factory=KnowledgeGraphConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    jwt: JWTConfig = field(default_factory=JWTConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    pagination: PaginationConfig = field(default_factory=PaginationConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)


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
    y = _load_yaml_config()

    def _get(path: str, default: Any = None) -> Any:
        keys = path.split(".")
        val = y
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
        return val if val is not None else default

    # LLM providers
    providers_raw = _get("llm.providers", {})
    providers = LLMProvidersConfig(
        spark=LLMProviderConfig(
            base_url=providers_raw.get("spark", {}).get("base_url", ""),
            default_model=providers_raw.get("spark", {}).get("default_model", ""),
        ),
        deepseek=LLMProviderConfig(
            base_url=providers_raw.get("deepseek", {}).get("base_url", ""),
            default_model=providers_raw.get("deepseek", {}).get("default_model", ""),
        ),
        qwen=LLMProviderConfig(
            base_url=providers_raw.get("qwen", {}).get("base_url", ""),
            default_model=providers_raw.get("qwen", {}).get("default_model", ""),
        ),
        openai=LLMProviderConfig(
            base_url=providers_raw.get("openai", {}).get("base_url", ""),
            default_model=providers_raw.get("openai", {}).get("default_model", ""),
        ),
    )

    # Token estimation
    token_estimation = TokenEstimationConfig(
        cn_chars_per_token=_get("chat.token_estimation.cn_chars_per_token", 1.5),
        en_chars_per_token=_get("chat.token_estimation.en_chars_per_token", 4.0),
    )

    # Generation quiz sub-config
    gen_quiz = GenerationQuizConfig(
        weak_threshold_high=_get("generation.quiz.weak_threshold_high", 5),
        weak_threshold_mid=_get("generation.quiz.weak_threshold_mid", 2),
        counts_high=_get("generation.quiz.counts_high", [3, 2, 2]),
        counts_mid=_get("generation.quiz.counts_mid", [2, 1, 1]),
        counts_default=_get("generation.quiz.counts_default", [2, 1, 1]),
    )

    # Agent configs
    agents = AgentsConfig(
        clarify=ClarifyAgentConfig(
            temperature=_get("agents.clarify.temperature", 0.7),
        ),
        code=CodeAgentConfig(
            temperature=_get("agents.code.temperature", 0.7),
            max_tokens=_get("agents.code.max_tokens", 5000),
        ),
        doc=DocAgentConfig(
            temperature=_get("agents.doc.temperature", 0.7),
            max_tokens=_get("agents.doc.max_tokens", 4000),
        ),
        mindmap=MindmapAgentConfig(
            temperature=_get("agents.mindmap.temperature", 0.5),
            max_tokens=_get("agents.mindmap.max_tokens", 2000),
        ),
        planner=PlannerAgentConfig(
            intent_temperature=_get("agents.planner.intent_temperature", 0.0),
            classify_temperature=_get("agents.planner.classify_temperature", 0.1),
            smart_plan_temperature=_get("agents.planner.smart_plan_temperature", 0.3),
            history_lookback_messages=_get("agents.planner.history_lookback_messages", 6),
            fallback_kp_id_length=_get("agents.planner.fallback_kp_id_length", 50),
            smart_plan_default_types=_get("agents.planner.smart_plan_default_types", ["doc", "quiz"]),
        ),
        profile=ProfileAgentConfig(
            extract_temperature=_get("agents.profile.extract_temperature", 0.1),
            intent_temperature=_get("agents.profile.intent_temperature", 0.0),
            clarify_temperature=_get("agents.profile.clarify_temperature", 0.7),
            goal_summary_temperature=_get("agents.profile.goal_summary_temperature", 0.3),
            max_goal_questions=_get("agents.profile.max_goal_questions", 50),
            history_max_versions=_get("agents.profile.history_max_versions", 10),
        ),
        quiz=QuizAgentConfig(
            temperature=_get("agents.quiz.temperature", 0.6),
            max_tokens=_get("agents.quiz.max_tokens", 3000),
        ),
        recommend=RecommendAgentConfig(
            temperature=_get("agents.recommend.temperature", 0.7),
            max_tokens=_get("agents.recommend.max_tokens", 2000),
            min_recommendations=_get("agents.recommend.min_recommendations", 3),
            max_recommendations=_get("agents.recommend.max_recommendations", 5),
        ),
        safety=SafetyAgentConfig(
            temperature=_get("agents.safety.temperature", 0.1),
            max_tokens=_get("agents.safety.max_tokens", 300),
            max_ref_docs=_get("agents.safety.max_ref_docs", 3),
            draft_preview_chars=_get("agents.safety.draft_preview_chars", 500),
        ),
        summary=SummaryAgentConfig(
            temperature=_get("agents.summary.temperature", 0.7),
            max_tokens=_get("agents.summary.max_tokens", 1200),
            target_words_min=_get("agents.summary.target_words_min", 300),
            target_words_max=_get("agents.summary.target_words_max", 500),
        ),
    )

    return Config(
        database=DatabaseConfig(
            url=_get("database.url", ""),
            echo=_get("database.echo", False),
            pool_size=_get("database.pool_size", 10),
            max_overflow=_get("database.max_overflow", 20),
            pool_timeout=_get("database.pool_timeout", 30),
            pool_recycle=_get("database.pool_recycle", 3600),
            command_timeout=_get("database.command_timeout", 60),
        ),
        vector_db=VectorDBConfig(
            collection=_get("vector_db.collection", "knowledge_base"),
        ),
        llm=LLMConfig(
            api_key=_get("llm.api_key", ""),
            base_url=_get("llm.base_url", ""),
            model=_get("llm.model", ""),
            provider=_get("llm.provider", "qwen"),
            default_max_tokens=_get("llm.default_max_tokens", 2048),
            retry=LLMRetryConfig(
                max_attempts=_get("llm.retry.max_attempts", 5),
                backoff_multiplier=_get("llm.retry.backoff_multiplier", 2),
                backoff_min_seconds=_get("llm.retry.backoff_min_seconds", 3),
                backoff_max_seconds=_get("llm.retry.backoff_max_seconds", 30),
            ),
            timeout=LLMTimeoutConfig(
                connect=_get("llm.timeout.connect", 10),
                read=_get("llm.timeout.read", 120),
                write=_get("llm.timeout.write", 30),
                pool=_get("llm.timeout.pool", 10),
            ),
            providers=providers,
        ),
        rag=RAGConfig(
            chunk_size=_get("rag.chunk_size", 500),
            chunk_overlap=_get("rag.chunk_overlap", 50),
            n_results=_get("rag.n_results", 5),
            score_threshold=_get("rag.score_threshold", 0.5),
            context_max_tokens=_get("rag.context_max_tokens", 3000),
            max_sections_before_coarse_split=_get("rag.max_sections_before_coarse_split", 50),
            parent_chunking=ParentChunkingConfig(
                enabled=_get("rag.parent_chunking.enabled", False),
                parent_max_chars=_get("rag.parent_chunking.parent_max_chars", 2000),
                child_chunk_size=_get("rag.parent_chunking.child_chunk_size", None),
                child_chunk_overlap=_get("rag.parent_chunking.child_chunk_overlap", 100),
                score_weight=_get("rag.parent_chunking.score_weight", "max"),
            ),
            query_rewrite_enabled=_get("rag.query_rewrite.enabled", True),
            query_rewrite_decontextualize=_get("rag.query_rewrite.decontextualize", True),
            query_rewrite_profile_aware=_get("rag.query_rewrite.profile_aware", True),
            query_rewrite_multi_query=_get("rag.query_rewrite.multi_query", False),
            query_rewrite_multi_query_count=_get("rag.query_rewrite.multi_query_count", 3),
            query_rewrite_temperature=_get("rag.query_rewrite.temperature", 0.1),
            query_rewrite_max_tokens=_get("rag.query_rewrite.max_tokens", 150),
        ),
        embedding=EmbeddingConfig(
            use_spark=_get("embedding.use_spark", True),
            concurrency=_get("embedding.concurrency", 8),
            api_model=_get("embedding.api_model", "text-embedding-v4"),
            api_base_url=_get("embedding.api_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            timeout_read=_get("embedding.timeout_read", 60),
            timeout_connect=_get("embedding.timeout_connect", 10),
            timeout_write=_get("embedding.timeout_write", 30),
            timeout_pool=_get("embedding.timeout_pool", 10),
            index_batch_size=_get("embedding.index_batch_size", 128),
            vector_dimension=_get("embedding.vector_dimension", 1024),
        ),
        chat=ChatConfig(
            max_turns=_get("chat.max_turns", 10),
            history_max_tokens=_get("chat.history_max_tokens", 4000),
            message_max_length=_get("chat.message_max_length", 4096),
            session_expiry_days=_get("chat.session_expiry_days", 30),
            cleanup_interval_hours=_get("chat.cleanup_interval_hours", 24),
            auto_title_max_chars=_get("chat.auto_title_max_chars", 15),
            auto_title_message_truncate=_get("chat.auto_title_message_truncate", 200),
            auto_title_max_tokens=_get("chat.auto_title_max_tokens", 30),
            auto_title_final_length=_get("chat.auto_title_final_length", 20),
            token_estimation=token_estimation,
        ),
        knowledge_graph=KnowledgeGraphConfig(
            llm_concurrency=_get("knowledge_graph.llm_concurrency", 10),
            max_batches=_get("knowledge_graph.max_batches", 30),
            toc_max_items=_get("knowledge_graph.toc_max_items", 100),
            batch_chars_limit=_get("knowledge_graph.batch_chars_limit", 12000),
            text_truncate_chars=_get("knowledge_graph.text_truncate_chars", 6000),
            node_extraction_max_tokens=_get("knowledge_graph.node_extraction_max_tokens", 4000),
            edge_batch_size=_get("knowledge_graph.edge_batch_size", 40),
            edge_overlap=_get("knowledge_graph.edge_overlap", 10),
            section_merge_min_chars=_get("knowledge_graph.section_merge_min_chars", 200),
        ),
        generation=GenerationConfig(
            default_num_questions=_get("generation.default_num_questions", 4),
            max_questions=_get("generation.max_questions", 20),
            mindmap_max_depth=_get("generation.mindmap_max_depth", 4),
            mindmap_max_children=_get("generation.mindmap_max_children", 6),
            quiz=gen_quiz,
        ),
        jwt=JWTConfig(
            secret=_get("jwt.secret", ""),
            algorithm=_get("jwt.algorithm", "HS256"),
            expire_hours=_get("jwt.expire_hours", 24),
        ),
        storage=StorageConfig(
            upload_dir=_get("storage.upload_dir", "uploaded_docs"),
            knowledge_base_dir=_get("storage.knowledge_base_dir", "knowledge_base/ai_intro"),
            supported_extensions=_get("storage.supported_extensions", [".pdf", ".docx", ".doc", ".md", ".txt"]),
            doc_id_hex_length=_get("storage.doc_id_hex_length", 12),
            cleanup=StorageCleanupConfig(
                enabled=_get("storage.cleanup.enabled", True),
                retention_days=_get("storage.cleanup.retention_days", 30),
                orphan_retention_days=_get("storage.cleanup.orphan_retention_days", 7),
                interval_hours=_get("storage.cleanup.interval_hours", 24),
                min_file_age_seconds=_get("storage.cleanup.min_file_age_seconds", 300),
            ),
        ),
        logging=LoggingConfig(
            dir=_get("logging.dir", "logs"),
            retention_days=_get("logging.retention_days", 30),
            error_retention_days=_get("logging.error_retention_days", 90),
            trace_id_length=_get("logging.trace_id_length", 8),
        ),
        agents=agents,
        pagination=PaginationConfig(
            default_limit=_get("pagination.default_limit", 20),
            quiz_attempts_limit=_get("pagination.quiz_attempts_limit", 50),
        ),
        server=ServerConfig(
            version=_get("server.version", "0.1.0"),
            cors_origins=_get("server.cors_origins", ["*"]),
        ),
        auth=AuthConfig(
            bcrypt_rounds=_get("auth.bcrypt_rounds", 12),
        ),
    )


# ===========================================================
# 全局单例
# ===========================================================

config = _build_config()
