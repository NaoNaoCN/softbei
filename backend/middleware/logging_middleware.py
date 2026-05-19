"""
backend/middleware/logging_middleware.py
请求日志中间件：为每个请求注入 trace_id，记录请求入口、耗时、响应状态。
"""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from typing import Callable

from backend.config import config
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# 每个请求的 trace_id 通过 contextvar 传递，方便在任意位置获取
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


def get_trace_id() -> str:
    """获取当前请求的 trace_id（未在请求上下文中时返回 '-'）。"""
    return trace_id_var.get()


class LoggingMiddleware(BaseHTTPMiddleware):
    """FastAPI 中间件：记录请求入口、trace_id、HTTP 方法、路径、耗时、状态码。"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())[:config.logging.trace_id_length]
        trace_id_var.set(trace_id)
        request.state.trace_id = trace_id

        from backend.logging_config import logger

        logger.info(
            f"[{trace_id}] --> {request.method} {request.url.path} "
            f"| query: {request.query_params}"
        )

        start_time = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as e:
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"[{trace_id}] <-- {request.method} {request.url.path} "
                f"| EXCEPTION: {type(e).__name__}: {e} | {elapsed:.1f}ms"
            )
            raise

        elapsed = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"[{trace_id}] <-- {request.method} {request.url.path} "
            f"| status: {response.status_code} | {elapsed:.1f}ms"
        )
        return response
