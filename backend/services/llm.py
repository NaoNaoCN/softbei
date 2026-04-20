"""
backend/services/llm.py
LLM 调用服务层。
统一封装讯飞星火（主）与多个 OpenAI 兼容接口（备），对 Agent 层屏蔽底层细节。
支持 provider: "spark" | "deepseek" | "qwen" | "openai"
"""

from __future__ import annotations

import logging
import os
from typing import AsyncGenerator, Optional

from openai import AsyncOpenAI, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# ----------------------------------------------------------
# 默认 provider（读取环境变量，未设置则用 spark）
# ----------------------------------------------------------

DEFAULT_PROVIDER: str = os.getenv("LLM_PROVIDER", "spark")

# ----------------------------------------------------------
# Qwen 模型池：配额耗尽时自动切换
# ----------------------------------------------------------

_QUOTA_KEYWORDS = ("quota", "insufficient_quota", "arrearage", "balance is not enough")


def _is_quota_error(exc: RateLimitError) -> bool:
    return any(kw in str(exc).lower() for kw in _QUOTA_KEYWORDS)


class _QwenModelPool:
    """
    按优先级维护 Qwen 模型列表。
    收到配额耗尽错误时将当前模型标记为不可用并切换到下一个。

    通过环境变量配置：
        QWEN_MODELS=qwen-turbo,qwen-plus,qwen-long   # 按优先级排列，默认值如左
    """

    def __init__(self) -> None:
        raw = os.getenv("QWEN_MODELS", "qwen-turbo,qwen-plus,qwen-long")
        self._models: list[str] = [m.strip() for m in raw.split(",") if m.strip()]
        self._exhausted: set[str] = set()

    @property
    def current(self) -> str:
        for m in self._models:
            if m not in self._exhausted:
                return m
        raise RuntimeError(
            "All Qwen models exhausted. Add more models via QWEN_MODELS env var."
        )

    def mark_exhausted(self, model: str) -> None:
        self._exhausted.add(model)
        logger.warning("Qwen model '%s' quota exhausted, switched to '%s'.", model, self.current)


_qwen_pool = _QwenModelPool()

# ----------------------------------------------------------
# 客户端工厂
# ----------------------------------------------------------

def _make_client(provider: str) -> tuple[AsyncOpenAI, str]:
    """
    根据 provider 名称返回 (AsyncOpenAI client, default_model)。
    所有 provider 均使用 OpenAI 兼容协议，无需额外路由逻辑。
    """
    if provider == "spark":
        return AsyncOpenAI(
            api_key=os.environ["SPARK_API_KEY"],
            base_url=os.getenv("SPARK_BASE_URL", "https://spark-api-open.xf-yun.com/v1"),
        ), os.getenv("SPARK_MODEL", "generalv3.5")

    if provider == "deepseek":
        return AsyncOpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        ), os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    if provider == "qwen":
        return AsyncOpenAI(
            api_key=os.environ["QWEN_API_KEY"],
            base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ), _qwen_pool.current

    # fallback: openai
    return AsyncOpenAI(
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    ), os.getenv("OPENAI_MODEL", "gpt-4o-mini")


# ----------------------------------------------------------
# 核心调用接口
# ----------------------------------------------------------

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
    :param model:       模型名称，None 则使用 provider 对应的默认模型
    :param temperature: 温度
    :param max_tokens:  最大输出 token 数
    :param provider:    "spark" | "deepseek" | "qwen" | "openai"，None 则读 LLM_PROVIDER 环境变量
    :return:            模型文本输出
    """
    _provider = provider or DEFAULT_PROVIDER
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
            _qwen_pool.mark_exhausted(_model)
            # 用新模型立即重试一次（不走 tenacity，避免等待）
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
    _provider = provider or DEFAULT_PROVIDER
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
            _qwen_pool.mark_exhausted(_model)
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
    优先使用本地 BGE-M3；若环境变量 USE_SPARK_EMBEDDING=true 则调用讯飞嵌入 API。
    """
    use_spark_emb = os.getenv("USE_SPARK_EMBEDDING", "false").lower() == "true"
    if use_spark_emb:
        print("Using Spark embedding for text:", text)
        return await _spark_embedding(text)
    print("Using local embedding for text:", text)
    return await _local_embedding(text)


async def _local_embedding(text: str) -> list[float]:
    """使用 sentence-transformers BGE-M3 本地嵌入（stub）。"""
    # TODO: 加载模型并计算向量
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("BAAI/bge-m3")
    return model.encode(text).tolist()
    # raise NotImplementedError("Local embedding not implemented yet.")


async def _spark_embedding(text: str) -> list[float]:
    """调用讯飞星火嵌入 API（stub）。"""
    # TODO: 调用讯飞 embedding endpoint
    raise NotImplementedError("Spark embedding not implemented yet.")
