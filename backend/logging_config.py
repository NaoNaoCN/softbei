"""
backend/logging_config.py
统一日志配置：Loguru + 控制台输出 + 文件轮转 + 错误日志分离。
在应用启动前 import 此模块即可生效。
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

# 日志目录
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 移除默认 handler
logger.remove()

# 控制台输出（带颜色，仅 INFO 及以上）
logger.add(
    sys.stdout,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    ),
    level="INFO",
    colorize=True,
)

# 普通日志文件（每天轮转，保留 30 天）
logger.add(
    LOG_DIR / "app_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    enqueue=True,
)

# 错误日志单独记录（保留 90 天）
logger.add(
    LOG_DIR / "error_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="90 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
    level="ERROR",
    enqueue=True,
)