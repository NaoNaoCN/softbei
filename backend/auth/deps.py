"""
backend/auth/deps.py
FastAPI 依赖：从 JWT token 提取当前用户 ID，过渡期兼容 query param 回退。
"""

from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


async def get_current_user_id(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    user_id: uuid.UUID | None = Query(None, description="过渡期兼容：query param 回退"),
) -> uuid.UUID:
    """优先从 JWT 提取 user_id，回退到 query param（过渡期）。"""
    if cred:
        try:
            from backend.config import config as app_config

            payload = jwt.decode(
                cred.credentials,
                app_config.jwt.secret,
                algorithms=[app_config.jwt.algorithm],
            )
            return uuid.UUID(payload["sub"])
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
    if user_id:
        return user_id
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )
