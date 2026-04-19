"""
backend/services/llm.py
LLM 调用服务层。
统一封装讯飞星火（主）与 OpenAI 兼容接口（备），对 Agent 层屏蔽底层细节。
"""

from __future__ import annotations

import os
from typing import AsyncGenerator, Optional

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

# ----------------------------------------------------------
# 客户端工厂
# ----------------------------------------------------------

def _make_spark_client() -> AsyncOpenAI:
    """创建讯飞星火 OpenAI 兼容客户端。"""
    return AsyncOpenAI(
        api_key=os.environ["SPARK_API_KEY"],
        base_url=os.getenv("SPARK_BASE_URL", "https://spark-api-open.xf-yun.com/v1"),
    )


def _make_openai_client() -> AsyncOpenAI:
    """创建标准 OpenAI 客户端（备用）。"""
    return AsyncOpenAI(
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )


# ----------------------------------------------------------
# 核心调用接口
# ----------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def chat_completion(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    use_spark: bool = True,
) -> str:
    """
    单次非流式对话调用。
    返回模型输出的文本内容。

    :param messages:    OpenAI 格式消息列表 [{"role": ..., "content": ...}]
    :param model:       模型名称，默认读取环境变量 SPARK_MODEL / OPENAI_MODEL
    :param temperature: 温度
    :param max_tokens:  最大输出 token 数
    :param use_spark:   True 使用讯飞星火，False 使用 OpenAI 兼容接口
    :return:            模型文本输出
    """
    client = _make_spark_client() if use_spark else _make_openai_client()
    default_model = (
        os.getenv("SPARK_MODEL", "generalv3.5")
        if use_spark
        else os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    )
    response = await client.chat.completions.create(
        model=model or default_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


async def stream_chat_completion(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    use_spark: bool = True,
) -> AsyncGenerator[str, None]:
    """
    流式对话调用，逐 token yield 文本片段。
    供 FastAPI StreamingResponse 或 Streamlit st.write_stream 使用。
    """
    client = _make_spark_client() if use_spark else _make_openai_client()
    default_model = (
        os.getenv("SPARK_MODEL", "generalv3.5")
        if use_spark
        else os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    )
    stream = await client.chat.completions.create(
        model=model or default_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


async def get_embedding(text: str) -> list[float]:
    """
    获取文本的向量表示。
    优先使用本地 BGE-M3；若环境变量 USE_SPARK_EMBEDDING=true 则调用讯飞嵌入 API。
    """
    use_spark_emb = os.getenv("USE_SPARK_EMBEDDING", "false").lower() == "true"
    if use_spark_emb:
        return await _spark_embedding(text)
    return await _local_embedding(text)


async def _local_embedding(text: str) -> list[float]:
    """使用 sentence-transformers BGE-M3 本地嵌入（stub）。"""
    # TODO: 加载模型并计算向量
    # from sentence_transformers import SentenceTransformer
    # model = SentenceTransformer("BAAI/bge-m3")
    # return model.encode(text).tolist()
    raise NotImplementedError("Local embedding not implemented yet.")


async def _spark_embedding(text: str) -> list[float]:
    """调用讯飞星火嵌入 API（stub）。"""
    # TODO: 调用讯飞 embedding endpoint
    raise NotImplementedError("Spark embedding not implemented yet.")
