"""
backend/services/llm.py
LLM 调用服务层。
统一封装讯飞星火（主）与多个 OpenAI 兼容接口（备），对 Agent 层屏蔽底层细节。
支持 provider: "spark" | "deepseek" | "qwen" | "openai"
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from openai import AsyncOpenAI, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config import config

logger = logging.getLogger(__name__)

# ===========================================================
# 异常处理
# ===========================================================

_QUOTA_KEYWORDS = ("quota", "insufficient_quota", "arrearage", "balance is not enough")


def _is_quota_error(exc: RateLimitError) -> bool:
    return any(kw in str(exc).lower() for kw in _QUOTA_KEYWORDS)


# ===========================================================
# 客户端工厂
# ===========================================================

def _make_client(provider: str) -> tuple[AsyncOpenAI, str]:
    """
    根据 provider 名称返回 (AsyncOpenAI client, default_model)。
    所有配置均从 backend.config 读取。
    """
    if provider == "spark":
        return AsyncOpenAI(
            api_key=config.llm.api_key,
            base_url="https://spark-api-open.xf-yun.com/v1",
        ), "generalv3.5"

    if provider == "deepseek":
        return AsyncOpenAI(
            api_key=config.llm.api_key,
            base_url="https://api.deepseek.com/v1",
        ), "deepseek-chat"

    if provider == "qwen":
        return AsyncOpenAI(
            api_key=config.llm.api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ), "qwen-plus"

    if provider == "openai":
        return AsyncOpenAI(
            api_key=config.llm.api_key,
            base_url="https://api.openai.com/v1",
        ), "gpt-4o-mini"

    # fallback: 使用配置中的默认 provider
    return _make_client(config.llm.provider)


# ===========================================================
# Embedding 模型缓存
# ===========================================================

_embedding_model = None


def _get_embedding_model():
    """单例加载 sentence-transformers BGE-M3 模型（避免每次重新加载）。"""
    global _embedding_model
    if _embedding_model is None:
        logger.info("[Embedding] 开始加载模型...")
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer(config.embedding.model)
        logger.info("[Embedding] 模型加载完成")
    return _embedding_model


# ===========================================================
# 核心调用接口
# ===========================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def chat_completion(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    provider: Optional[str] = None,
) -> str:
    """
    单次非流式对话调用。
    返回模型输出的文本内容。

    :param messages:    OpenAI 格式消息列表 [{"role": ..., "content": ...}]
    :param model:       模型名称，None 则使用 provider 默认模型
    :param temperature: 温度
    :param max_tokens:  最大输出 token 数
    :param provider:    "spark" | "deepseek" | "qwen" | "openai"，None 则读配置文件
    :return:            模型文本输出
    """
    _provider = provider or config.llm.provider
    client, default_model = _make_client(_provider)
    _model = model or default_model
    try:
        response = await client.chat.completions.create(
            model=_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""
    except RateLimitError as e:
        if _provider == "qwen" and _is_quota_error(e):
            client2, next_model = _make_client("qwen")
            response = await client2.chat.completions.create(
                model=next_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        raise


async def stream_chat_completion(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    provider: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    流式对话调用，逐 token yield 文本片段。
    供 FastAPI StreamingResponse 或 Streamlit st.write_stream 使用。
    """
    _provider = provider or config.llm.provider
    client, default_model = _make_client(_provider)
    _model = model or default_model
    try:
        stream = await client.chat.completions.create(
            model=_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
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
                max_tokens=max_tokens,
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
        logging.getLogger(__name__).info(f"[Embedding] 本地 BGE-M3 成功，维度={len(result)}")
        return result
    except Exception as e:
        logging.getLogger(__name__).warning(f"[Embedding] 本地 BGE-M3 失败: {e}，返回空向量，RAG 将降级。")
        return []


async def _api_embedding(text: str) -> list[float]:
    """调用通义千问 text-embedding-v4 API。"""
    client = AsyncOpenAI(
        api_key=config.llm.api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    response = await client.embeddings.create(
        model="text-embedding-v4",
        input=text,
    )
    return response.data[0].embedding
