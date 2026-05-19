"""
backend/services/llm.py
LLM 调用服务层。
统一封装多个 OpenAI 兼容接口，对 Agent 层屏蔽底层细节。
所有 provider 的 URL、model、超时、重试策略均从 configs/config.yaml 读取。
"""

from __future__ import annotations

from typing import AsyncGenerator, Optional

from loguru import logger  # noqa: F401

from openai import AsyncOpenAI, RateLimitError, PermissionDeniedError
from httpx import Timeout, ConnectTimeout, ReadTimeout
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.config import config

# ===========================================================
# 异常处理
# ===========================================================

_QUOTA_KEYWORDS = ("quota", "insufficient_quota", "arrearage", "balance is not enough")


def _is_quota_error(exc: RateLimitError) -> bool:
    return any(kw in str(exc).lower() for kw in _QUOTA_KEYWORDS)


# ===========================================================
# 客户端工厂
# ===========================================================

def _get_provider_config(provider: str):
    """根据 provider 名称获取对应的配置。"""
    p = config.llm.providers
    mapping = {
        "spark": p.spark,
        "deepseek": p.deepseek,
        "qwen": p.qwen,
        "openai": p.openai,
    }
    return mapping.get(provider)


def _make_client(provider: str) -> tuple[AsyncOpenAI, str]:
    """
    根据 provider 名称返回 (AsyncOpenAI client, default_model)。
    所有配置从 backend.config 读取。
    """
    t = config.llm.timeout
    _timeout = Timeout(connect=t.connect, read=t.read, write=t.write, pool=t.pool)

    prov = _get_provider_config(provider)
    if prov and prov.base_url:
        return AsyncOpenAI(
            api_key=config.llm.api_key,
            base_url=prov.base_url,
            timeout=_timeout,
        ), prov.default_model or config.llm.model

    # fallback: 使用配置中的默认 base_url 和 model
    return AsyncOpenAI(
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        timeout=_timeout,
    ), config.llm.model


# ===========================================================
# Embedding 模型缓存
# ===========================================================

_embedding_model = None


def _get_embedding_model():
    """单例加载 sentence-transformers BGE-M3 模型（避免每次重新加载）。"""
    global _embedding_model
    if _embedding_model is None:
        import os
        if config.embedding.hf_mirror:
            os.environ["HF_ENDPOINT"] = config.embedding.hf_mirror
            logger.info(f"[Embedding] 使用 HF 镜像: {config.embedding.hf_mirror}")
        logger.info("[Embedding] 开始加载模型...")
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer(config.embedding.model)
        logger.info("[Embedding] 模型加载完成")
    return _embedding_model


# ===========================================================
# 核心调用接口
# ===========================================================

@retry(
    stop=stop_after_attempt(config.llm.retry.max_attempts),
    wait=wait_exponential(
        multiplier=config.llm.retry.backoff_multiplier,
        min=config.llm.retry.backoff_min_seconds,
        max=config.llm.retry.backoff_max_seconds,
    ),
    retry=retry_if_exception_type((RateLimitError, PermissionDeniedError, TimeoutError, ConnectionError, ConnectTimeout, ReadTimeout)),
)
async def chat_completion(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    provider: Optional[str] = None,
) -> str:
    """
    单次非流式对话调用。

    :param messages:    OpenAI 格式消息列表
    :param model:       模型名称，None 则使用 provider 默认模型
    :param temperature: 温度
    :param max_tokens:  最大输出 token 数，None 则使用配置默认值
    :param provider:    "spark" | "deepseek" | "qwen" | "openai"，None 则读配置文件
    :return:            模型文本输出
    """
    _provider = provider or config.llm.provider
    client, default_model = _make_client(_provider)
    _model = model or default_model
    _max_tokens = max_tokens if max_tokens is not None else config.llm.default_max_tokens
    try:
        response = await client.chat.completions.create(
            model=_model,
            messages=messages,
            temperature=temperature,
            max_tokens=_max_tokens,
        )
        return response.choices[0].message.content or ""
    except RateLimitError as e:
        if _provider == "qwen" and _is_quota_error(e):
            client2, next_model = _make_client("qwen")
            response = await client2.chat.completions.create(
                model=next_model,
                messages=messages,
                temperature=temperature,
                max_tokens=_max_tokens,
            )
            return response.choices[0].message.content or ""
        raise


async def stream_chat_completion(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    provider: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """流式对话调用，逐 token yield 文本片段。"""
    _provider = provider or config.llm.provider
    client, default_model = _make_client(_provider)
    _model = model or default_model
    _max_tokens = max_tokens if max_tokens is not None else config.llm.default_max_tokens
    try:
        stream = await client.chat.completions.create(
            model=_model,
            messages=messages,
            temperature=temperature,
            max_tokens=_max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
    except RateLimitError as e:
        if _provider == "qwen" and _is_quota_error(e):
            client2, next_model = _make_client("qwen")
            stream2 = await client2.chat.completions.create(
                model=next_model,
                messages=messages,
                temperature=temperature,
                max_tokens=_max_tokens,
                stream=True,
            )
            async for chunk in stream2:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
        else:
            raise


async def get_embedding(text: str) -> list[float]:
    """
    获取文本的向量表示。
    根据 config.embedding.use_spark 决定使用 API 还是本地模型。
    """
    if config.embedding.use_spark:
        return await _api_embedding(text)
    return await _local_embedding(text)


async def _local_embedding(text: str) -> list[float]:
    """使用 sentence-transformers BGE-M3 本地嵌入。"""
    try:
        model = _get_embedding_model()
        result = model.encode(text).tolist()
        logger.info(f"[Embedding] 本地 BGE-M3 成功，维度={len(result)}")
        return result
    except Exception as e:
        logger.warning(f"[Embedding] 本地 BGE-M3 失败: {e}，返回空向量，RAG 将降级。")
        return []


async def _api_embedding(text: str) -> list[float]:
    """调用远程 Embedding API。失败时自动降级到本地 BGE-M3。"""
    try:
        client = AsyncOpenAI(
            api_key=config.llm.api_key,
            base_url=config.embedding.api_base_url,
            timeout=Timeout(connect=config.embedding.timeout_connect, read=config.embedding.timeout_read, write=config.embedding.timeout_write, pool=config.embedding.timeout_pool),
        )
        response = await client.embeddings.create(
            model=config.embedding.api_model,
            input=text,
        )
        return response.data[0].embedding
    except Exception as e:
        logger.warning(f"[Embedding] API embedding 失败: {e}，降级到本地 BGE-M3")
        return await _local_embedding(text)
