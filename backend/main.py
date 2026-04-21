"""
backend/main.py
FastAPI 应用入口：路由注册、生命周期管理、中间件配置。
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.hash_utils import hash_password, verify_password
from backend.agents.graph import get_graph, invoke, stream_invoke
from backend.db.database import close_db, get_session, health_check as db_health, init_db
from backend.db.vector import health_check as vec_health, init_vector_db
from backend.models.schemas import (
    ChatMessageIn,
    ChatMessageOut,
    ChatSessionOut,
    GenerateRequest,
    GenerateTaskOut,
    KGGraphOut,
    LearningPathOut,
    LearningRecordCreate,
    LearningRecordOut,
    QuizAttemptOut,
    QuizItemOut,
    QuizSubmitIn,
    ResourceMetaOut,
    StudentProfileIn,
    StudentProfileOut,
    TokenOut,
    UserCreate,
    UserOut,
)
from backend.services import profile as profile_svc
from backend.services import resource as resource_svc
from sqlalchemy import select
from backend.db.models import User

# ===========================================================
# Lifespan（应用启动 / 关闭）
# ===========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """初始化数据库连接池与向量库，关闭时释放资源。"""
    await init_db()
    init_vector_db()
    get_graph()  # 预热 LangGraph
    yield
    await close_db()


# ===========================================================
# 应用实例
# ===========================================================

app = FastAPI(
    title="A3 个性化学习多智能体系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 生产环境应限制为 Streamlit 域名
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================
# 健康检查
# ===========================================================

@app.get("/health", tags=["system"])
async def health():
    """系统健康检查接口，返回各组件状态。"""
    return {
        "status": "ok",
        "db": await db_health(),
        "vector_db": vec_health(),
    }


# ===========================================================
# 用户认证
# ===========================================================

@app.post("/auth/register", response_model=UserOut, tags=["auth"])
async def register(body: UserCreate, db: AsyncSession = Depends(get_session)):
    """注册新用户。"""
    

    existing = await db.scalar(select(User).where(User.username == body.username))
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists")

    user = User(username=body.username, hashed_password=hash_password(body.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@app.post("/auth/login", response_model=TokenOut, tags=["auth"])
async def login(body: UserCreate, db: AsyncSession = Depends(get_session)):
    """用户名密码登录，返回 JWT Token。"""
    # TODO: 验证密码，生成 JWT
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


# ===========================================================
# 学生画像
# ===========================================================

@app.get("/profile", response_model=StudentProfileOut, tags=["profile"])
async def get_profile(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """获取当前用户画像。"""
    result = await profile_svc.get_profile(user_id, db)
    if not result:
        raise HTTPException(status_code=404, detail="Profile not found")
    return result


@app.put("/profile", response_model=StudentProfileOut, tags=["profile"])
async def update_profile(
    user_id: uuid.UUID,
    body: StudentProfileIn,
    db: AsyncSession = Depends(get_session),
):
    """手动更新用户画像。"""
    return await profile_svc.create_or_update_profile(user_id, body, db)


@app.get("/profile/history", response_model=list[StudentProfileOut], tags=["profile"])
async def get_profile_history(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """获取画像历史版本。"""
    return await profile_svc.get_profile_history(user_id, db)


# ===========================================================
# 对话（Agent 入口）
# ===========================================================

@app.post("/chat/{session_id}", tags=["chat"])
async def chat(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    body: ChatMessageIn,
    stream: bool = False,
):
    """
    向 Agent 系统发送消息。
    stream=true 时返回 SSE 流式响应。
    """
    if stream:
        async def event_generator():
            async for event in stream_invoke(str(user_id), str(session_id), body.content):
                yield f"data: {event}\n\n"
        return StreamingResponse(event_generator(), media_type="text/event-stream")
    result = await invoke(str(user_id), str(session_id), body.content)
    return {"content": result.final_content, "metadata": result.metadata}


@app.get("/chat/sessions", response_model=list[ChatSessionOut], tags=["chat"])
async def list_sessions(user_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """列举用户的所有对话会话。"""
    # TODO: 查询 chat_session 表
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


# ===========================================================
# 知识图谱
# ===========================================================

@app.get("/kg/graph", response_model=KGGraphOut, tags=["knowledge-graph"])
async def get_kg_graph(
    root_id: Optional[str] = None,
    depth: int = 3,
    db: AsyncSession = Depends(get_session),
):
    """获取知识图谱子图，供前端 ECharts 渲染。"""
    # TODO: 从 kg_node + kg_edge 表构建子图
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


# ===========================================================
# 资源生成
# ===========================================================

@app.post("/generate", response_model=GenerateTaskOut, tags=["generate"])
async def start_generation(
    user_id: uuid.UUID,
    body: GenerateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    """
    触发异步资源生成任务。
    返回 task_id 供前端轮询 /generate/{task_id}/status。
    """
    task = await resource_svc.create_generation_task(user_id, body, db)
    # TODO: background_tasks.add_task(run_generation, task.task_id, body)
    return task


@app.get("/generate/{task_id}/status", response_model=GenerateTaskOut, tags=["generate"])
async def get_generation_status(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """轮询生成任务状态与进度。"""
    task = await resource_svc.get_task_status(task_id, db)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ===========================================================
# 资源库
# ===========================================================

@app.get("/resources", response_model=list[ResourceMetaOut], tags=["resources"])
async def list_resources(
    user_id: uuid.UUID,
    resource_type: Optional[str] = None,
    kp_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_session),
):
    """分页列举用户的学习资源。"""
    return await resource_svc.list_resources(user_id, db, resource_type, kp_id, skip, limit)


@app.get("/resources/{resource_id}", response_model=ResourceMetaOut, tags=["resources"])
async def get_resource(resource_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """获取单个资源详情。"""
    res = await resource_svc.get_resource(resource_id, db)
    if not res:
        raise HTTPException(status_code=404)
    return res


@app.delete("/resources/{resource_id}", tags=["resources"])
async def delete_resource(resource_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """删除资源。"""
    await resource_svc.delete_resource(resource_id, db)
    return {"deleted": True}


# ===========================================================
# 测验
# ===========================================================

@app.get("/resources/{resource_id}/quiz", response_model=list[QuizItemOut], tags=["quiz"])
async def get_quiz_items(resource_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """获取某资源下的所有题目。"""
    # TODO: 查询 quiz_item WHERE resource_id = ...
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@app.post("/quiz/submit", response_model=QuizAttemptOut, tags=["quiz"])
async def submit_quiz(
    user_id: uuid.UUID,
    body: QuizSubmitIn,
    db: AsyncSession = Depends(get_session),
):
    """提交答题记录，返回批改结果。"""
    # TODO: 查题目答案 → 对比 → INSERT quiz_attempt
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


# ===========================================================
# 学习路径
# ===========================================================

@app.get("/pathways", response_model=list[LearningPathOut], tags=["pathway"])
async def list_pathways(user_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """列举用户的学习路径。"""
    # TODO: 查询 learning_path + learning_path_item
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


# ===========================================================
# 学习记录
# ===========================================================

@app.post("/records", response_model=LearningRecordOut, tags=["records"])
async def add_record(
    user_id: uuid.UUID,
    body: LearningRecordCreate,
    db: AsyncSession = Depends(get_session),
):
    """记录学习行为。"""
    return await resource_svc.record_learning(user_id, body, db)
