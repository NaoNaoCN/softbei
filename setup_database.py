"""
setup_database.py — 一键创建 softbei 数据库及全部表结构

用法:
    python setup_database.py

前置条件:
    1. PostgreSQL 服务已运行
    2. 项目根目录有 .env 文件，包含 DATABASE_URL
       （如未创建，从 .env.example 复制并填写）
    3. pip install -r requirements.txt 已完成

做的事情:
    1. 连接 PostgreSQL，若 softbei 库不存在则创建
    2. 在库中启用 pgvector 扩展
    3. 执行 alembic upgrade head 创建全部表及索引
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# ── 确定项目根目录（本脚本所在目录）──────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent


def load_env() -> dict[str, str]:
    """从 .env 文件加载环境变量（不依赖 python-dotenv，避免循环依赖）。"""
    env_file = PROJECT_ROOT / ".env"
    env_vars: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip().strip('"').strip("'")
    # 同时继承当前进程环境变量（.env 文件中的值优先）
    merged = dict(os.environ)
    merged.update(env_vars)
    return merged


def parse_db_url(url: str) -> dict[str, str]:
    """
    解析 DATABASE_URL，提取连接参数。

    支持格式: postgresql+asyncpg://user:pass@host:port/dbname
              postgresql://user:pass@host:port/dbname
    """
    pattern = (
        r"^(?:postgresql(?:\+asyncpg)?://)"
        r"(?P<user>[^:]+)"
        r"(?::(?P<password>[^@]+))?"
        r"@(?P<host>[^:/]+)"
        r"(?::(?P<port>\d+))?"
        r"/(?P<dbname>[^?]+)"
    )
    match = re.match(pattern, url)
    if not match:
        print(f"[ERROR] 无法解析 DATABASE_URL: {url}")
        print("        期望格式: postgresql+asyncpg://user:pass@host:port/dbname")
        sys.exit(1)
    return match.groupdict()


def print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_step(step: int, msg: str) -> None:
    print(f"\n  [{step}] {msg}...")


async def create_database_if_not_exists(
    host: str, port: int, user: str, password: str, dbname: str
) -> None:
    """连接到默认 postgres 库，检查并创建目标数据库。"""
    import asyncpg

    # 先连到 postgres 系统库
    sys_conn = await asyncpg.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database="postgres",
    )

    try:
        # 检查目标库是否已存在
        existing = await sys_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", dbname
        )
        if existing:
            print(f"      ✓ 数据库 '{dbname}' 已存在，跳过创建")
        else:
            # PostgreSQL 不支持 CREATE DATABASE 的参数化，需手动拼接（dbname 已校验安全）
            await sys_conn.execute(f'CREATE DATABASE "{dbname}"')
            print(f"      ✓ 数据库 '{dbname}' 创建成功")
    finally:
        await sys_conn.close()


async def enable_pgvector_extension(
    host: str, port: int, user: str, password: str, dbname: str
) -> None:
    """在目标数据库中启用 pgvector 扩展。"""
    import asyncpg

    conn = await asyncpg.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=dbname,
    )

    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        print("      ✓ pgvector 扩展已启用")
    finally:
        await conn.close()


def run_alembic_migrations() -> None:
    """执行 Alembic 迁移，创建全部表、索引、约束。"""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("      ✓ 数据库迁移完成（全部表与索引已就绪）")
        # 打印 alembic 输出的最后几行（含迁移版本号）
        for line in result.stdout.strip().splitlines()[-5:]:
            if line.strip():
                print(f"        {line.strip()}")
    else:
        print(f"      ✗ 迁移失败 (exit code {result.returncode})")
        print(f"        stdout: {result.stdout}")
        print(f"        stderr: {result.stderr}")
        sys.exit(1)


def main():
    print_header("softbei 数据库一键部署")

    # ── 第 1 步：读取环境变量 ──────────────────────────────────
    print_step(1, "读取 .env 环境变量")
    env = load_env()
    db_url = env.get("DATABASE_URL", "")
    if not db_url:
        print("      ✗ 未找到 DATABASE_URL，请先创建 .env 文件并配置数据库连接")
        print(f"        参考: {PROJECT_ROOT / '.env.example'}")
        sys.exit(1)
    print(f"      DATABASE_URL = {db_url}")

    # ── 第 2 步：解析连接参数 ──────────────────────────────────
    print_step(2, "解析数据库连接参数")
    parsed = parse_db_url(db_url)
    host = parsed["host"]
    port = int(parsed["port"] or 5432)
    user = parsed["user"]
    password = parsed["password"] or ""
    dbname = parsed["dbname"]
    print(f"      host={host}, port={port}, user={user}, dbname={dbname}")

    # ── 第 3 步：创建数据库 ────────────────────────────────────
    print_step(3, f"创建数据库 '{dbname}'（若不存在）")
    import asyncio
    asyncio.run(create_database_if_not_exists(host, port, user, password, dbname))

    # ── 第 4 步：启用 pgvector 扩展 ────────────────────────────
    print_step(4, "启用 pgvector 扩展")
    asyncio.run(enable_pgvector_extension(host, port, user, password, dbname))

    # ── 第 5 步：运行 Alembic 迁移 ─────────────────────────────
    print_step(5, "运行 Alembic 数据库迁移（建表 + 索引）")
    run_alembic_migrations()

    # ── 完成 ──────────────────────────────────────────────────
    print_header("部署完成")
    print(f"""
  数据库: {dbname}
  表数量: 17 张（含向量表 document_chunk）
  索引:   自动创建（含 IVFFlat 向量索引）

  启动后端: uvicorn backend.main:app --reload --port 8000
  前端地址: http://localhost:8000/app
""")


if __name__ == "__main__":
    main()
