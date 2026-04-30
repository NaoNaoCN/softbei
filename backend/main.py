"""
backend/main.py
FastAPI 应用入口：路由注册、生命周期管理、中间件配置。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status, UploadFile, File, Form
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
    KGEdgeOut,
    KGNodeOut,
    LearningPathCreate,
    LearningPathItemCreate,
    LearningPathItemOut,
    LearningPathItemUpdate,
    LearningPathOut,
    LearningPathUpdate,
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
    KGNodeType,
    KGRelation,
)
from backend.services import profile as profile_svc
from backend.services import resource as resource_svc
from backend.services import document as document_svc
from backend.db.models import User, ChatSession, ChatMessage, KGNode, KGEdge, QuizItem, QuizAttempt, LearningPath, LearningPathItem, ResourceMeta

# ===========================================================
# JWT 配置（从 configs/config.yaml 读取）
# ===========================================================
from backend.config import config as app_config

JWT_SECRET = app_config.jwt.secret
JWT_ALGORITHM = app_config.jwt.algorithm
JWT_EXPIRE_HOURS = app_config.jwt.expire_hours

# ===========================================================
# Lifespan（应用启动 / 关闭）
# ===========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """初始化数据库连接池与向量库，启动后台清理任务，关闭时释放资源。"""
    await init_db()
    init_vector_db()
    get_graph()  # 预热 LangGraph

    # 启动动态会话表过期清理后台任务
    from backend.db.dynamic_chat import start_cleanup_task
    cleanup_task = asyncio.create_task(start_cleanup_task())

    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except (asyncio.CancelledError, Exception):
            pass
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
    from backend.db.crud import select_one, insert

    existing = await select_one(db, User, filters={"username": body.username})
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists")

    user = await insert(
        db, User,
        data={"username": body.username, "hashed_password": hash_password(body.password)},
    )
    return UserOut.model_validate(user)


@app.post("/auth/login", response_model=TokenOut, tags=["auth"])
async def login(body: UserCreate, db: AsyncSession = Depends(get_session)):
    """用户名密码登录，返回 JWT Token。"""
    from backend.db.crud import select_one

    user = await select_one(db, User, filters={"username": body.username})
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {"sub": str(user.id), "exp": expire}
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return TokenOut(user_id=user.id, access_token=token, token_type="bearer")


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

@app.get("/chat/sessions", response_model=list[ChatSessionOut], tags=["chat"])
async def list_sessions(user_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """列举用户的所有对话会话。"""
    from backend.db.crud import select as db_select
    sessions = await db_select(db, ChatSession, filters={"user_id": user_id})
    return [ChatSessionOut.model_validate(s) for s in sessions]


@app.post("/chat/sessions", response_model=ChatSessionOut, tags=["chat"])
async def create_chat_session(user_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """创建新的对话会话，同时为该会话创建一张独立的消息表。"""
    from backend.db.crud import insert, select_by_id, update_by_id
    from backend.db.dynamic_chat import build_table_name, create_session_table

    # 1. 查用户名（用于表名拼接）
    user = await select_by_id(db, User, user_id)
    username = user.username if user else "anon"

    # 2. 插入 chat_session 记录
    session = await insert(db, ChatSession, data={"user_id": user_id})

    # 3. 以 username + 创建时间 + session_id 生成动态表名，并创建表
    table_name = build_table_name(username, str(session.id), session.created_at)
    try:
        await create_session_table(table_name)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"动态会话表创建失败: {e}")
        table_name = None

    # 4. 回写 messages_table 字段
    if table_name:
        await update_by_id(db, ChatSession, session.id, data={"messages_table": table_name})
        session.messages_table = table_name

    return ChatSessionOut.model_validate(session)


@app.post("/chat/{session_id}", tags=["chat"])
async def chat(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    body: ChatMessageIn,
    stream: bool = False,
    db: AsyncSession = Depends(get_session),
):
    """
    向 Agent 系统发送消息。
    stream=true 时返回 SSE 流式响应。
    """
    if stream:
        async def event_generator():
            async for event in stream_invoke(str(user_id), str(session_id), body.content, db):
                yield f"data: {event}\n\n"
        return StreamingResponse(event_generator(), media_type="text/event-stream")
    result = await invoke(str(user_id), str(session_id), body.content, db)

    # 刷新 last_used_at，并将本轮对话写入动态会话表
    try:
        from backend.db.crud import select_by_id, update_by_id
        from backend.db.dynamic_chat import insert_message
        chat_sess = await select_by_id(db, ChatSession, session_id)
        if chat_sess:
            await update_by_id(
                db, ChatSession, session_id,
                data={"last_used_at": datetime.utcnow()},
            )
            if chat_sess.messages_table:
                await insert_message(chat_sess.messages_table, "user", body.content)
                if result.final_content:
                    await insert_message(
                        chat_sess.messages_table, "assistant", result.final_content
                    )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"动态会话表写入失败: {e}")

    # 如果生成了资源，持久化到 resource_meta 表
    if result.resource_type and result.draft_content:
        try:
            from backend.db.crud import insert, select_one
            # 解析 kp_id → 知识点名称
            kp_id = result.kp_id or "unknown"
            kp_title = kp_id
            if kp_id.startswith("kp_"):
                node = await select_one(db, KGNode, filters={"id": kp_id})
                if node:
                    kp_title = node.name
            await insert(db, ResourceMeta, data={
                "user_id": user_id,
                "kp_id": kp_id,
                "resource_type": result.resource_type.value,
                "title": f"{kp_title} - {result.resource_type.value}",
                "content": result.draft_content,
            })
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"资源保存失败: {e}")

    return {
        "content": result.final_content,
        "metadata": result.metadata,
        "profile_complete": result.profile_complete,
    }


# ===========================================================
# 知识图谱
# ===========================================================

@app.get("/kg/graph", response_model=KGGraphOut, tags=["knowledge-graph"])
async def get_kg_graph(
    root_id: Optional[str] = None,
    doc_id: Optional[str] = None,
    depth: int = 3,
    db: AsyncSession = Depends(get_session),
):
    """获取知识图谱子图，供前端 ECharts 渲染。支持按 doc_id 过滤 + depth 控制展开层数。"""
    from backend.db.crud import select as db_select

    filters = {"course_id": doc_id} if doc_id else {}
    all_nodes = await db_select(db, KGNode, filters=filters)
    node_map = {n.id: n for n in all_nodes}
    node_ids = set(node_map.keys())

    all_edges = await db_select(db, KGEdge)
    edges_in_scope = [e for e in all_edges if e.source_id in node_ids and e.target_id in node_ids]

    # depth 统一按节点类型层级过滤
    type_levels = ["Course", "Chapter", "KnowledgePoint", "SubPoint", "Concept"]
    allowed_types = set(type_levels[:depth])
    reachable = {nid for nid, n in node_map.items() if n.node_type in allowed_types}

    # 如果指定了 root_id，进一步限制为该根节点的层级子树
    if root_id and root_id in node_ids:
        hierarchy_adj: dict[str, list[str]] = {nid: [] for nid in node_ids}
        for e in edges_in_scope:
            if e.relation in ("IS_PART_OF", "CONTAINS"):
                hierarchy_adj[e.target_id].append(e.source_id)
                hierarchy_adj[e.source_id].append(e.target_id)
        # BFS 找出 root 的所有后代
        descendants: set[str] = {root_id}
        frontier = [root_id]
        while frontier:
            next_frontier = []
            for nid in frontier:
                for child in hierarchy_adj.get(nid, []):
                    if child not in descendants:
                        descendants.add(child)
                        next_frontier.append(child)
            frontier = next_frontier
        reachable = reachable & descendants

    # 过滤节点和边
    filtered_nodes = [n for n in all_nodes if n.id in reachable]
    filtered_edges = [e for e in edges_in_scope if e.source_id in reachable and e.target_id in reachable]

    kg_nodes = [
        KGNodeOut(
            id=n.id,
            type=KGNodeType(n.node_type),
            name=n.name,
            difficulty=None,
            is_core=False,
            extra={"description": n.description or ""},
        )
        for n in filtered_nodes
    ]
    kg_edges = [
        KGEdgeOut(
            source_id=e.source_id,
            target_id=e.target_id,
            relation=KGRelation(e.relation),
        )
        for e in filtered_edges
    ]
    return KGGraphOut(nodes=kg_nodes, edges=kg_edges)


@app.post("/kg/build", tags=["knowledge-graph"])
async def build_kg_endpoint(
    doc_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    """异步构建知识图谱，立即返回任务 ID 供轮询。"""
    from backend.db.crud import insert
    from backend.db.models import KGBuildTask
    from backend.models.schemas import KGBuildTaskOut

    print(f"[POST /kg/build] 创建异步构建任务，doc_id={doc_id}")
    task = await insert(db, KGBuildTask, data={
        "doc_id": doc_id,
        "status": "pending",
        "progress": 0,
        "stage": "排队中",
    })

    from backend.services.kg_builder import run_kg_build
    background_tasks.add_task(run_kg_build, task.id, doc_id, db)

    return KGBuildTaskOut(
        task_id=task.id,
        doc_id=doc_id,
        status="pending",
        progress=0,
        stage="排队中",
    )


@app.get("/kg/build/{task_id}/status", tags=["knowledge-graph"])
async def get_kg_build_status(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """轮询知识图谱构建任务状态。"""
    from backend.db.crud import select_one
    from backend.db.models import KGBuildTask
    from backend.models.schemas import KGBuildTaskOut

    task = await select_one(db, KGBuildTask, filters={"id": task_id})
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return KGBuildTaskOut(
        task_id=task.id,
        doc_id=task.doc_id,
        status=task.status,
        progress=task.progress,
        stage=task.stage,
        nodes_count=task.nodes_count,
        edges_count=task.edges_count,
        error_msg=task.error_message,
    )


@app.get("/kg/build/by-doc/{doc_id}/status", tags=["knowledge-graph"])
async def get_kg_build_status_by_doc(
    doc_id: str,
    db: AsyncSession = Depends(get_session),
):
    """按 doc_id 查询最新的构建任务状态（刷新浏览器后恢复跟踪）。"""
    from backend.db.crud import select as db_select
    from backend.db.models import KGBuildTask
    from backend.models.schemas import KGBuildTaskOut

    tasks = await db_select(
        db, KGBuildTask, filters={"doc_id": doc_id},
        order_by=KGBuildTask.created_at.desc(), limit=1,
    )
    if not tasks:
        return {"status": "none"}
    task = tasks[0]
    return KGBuildTaskOut(
        task_id=task.id,
        doc_id=task.doc_id,
        status=task.status,
        progress=task.progress,
        stage=task.stage,
        nodes_count=task.nodes_count,
        edges_count=task.edges_count,
        error_msg=task.error_message,
    )


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
    from backend.services.generation import run_generation
    task = await resource_svc.create_generation_task(user_id, body, db)

    # 获取或创建会话 ID
    session_id = str(uuid.uuid4())

    background_tasks.add_task(
        run_generation,
        task.task_id,
        str(user_id),
        session_id,
        body,
        db,
    )
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


@app.get("/resources/stats", tags=["resources"])
async def get_resource_stats(user_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """返回用户的资源统计：按类型计数的字典。"""
    from backend.db.crud import count

    stats = {}
    for rt in ["doc", "mindmap", "quiz", "code", "summary"]:
        stats[rt] = await count(db, ResourceMeta, {"user_id": user_id, "resource_type": rt})
    return stats


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
    from backend.db.crud import select as db_select
    quiz_items = await db_select(db, QuizItem, filters={"resource_id": resource_id})
    return [
        QuizItemOut(
            id=item.id,
            kp_id=None,
            question_type=item.question_type,
            difficulty=None,
            stem=item.stem,
            options=item.options,
            answer=item.answer,
            explanation=item.explanation,
        )
        for item in quiz_items
    ]


@app.post("/quiz/submit", response_model=QuizAttemptOut, tags=["quiz"])
async def submit_quiz(
    user_id: uuid.UUID,
    body: QuizSubmitIn,
    db: AsyncSession = Depends(get_session),
):
    """提交答题记录，返回批改结果。"""
    from backend.db.crud import select_one, insert

    quiz_item = await select_one(db, QuizItem, filters={"id": body.quiz_item_id})
    if not quiz_item:
        raise HTTPException(status_code=404, detail="Quiz item not found")

    # 判分
    user_answer_str = str(body.user_answer).strip().lower()
    correct_answer_str = str(quiz_item.answer).strip().lower()
    is_correct = user_answer_str == correct_answer_str
    score = 1.0 if is_correct else 0.0

    attempt = await insert(
        db, QuizAttempt,
        data={
            "quiz_item_id": body.quiz_item_id,
            "user_id": user_id,
            "user_answer": str(body.user_answer),
            "is_correct": is_correct,
            "score": score,
        },
    )
    return QuizAttemptOut(
        id=attempt.id,
        quiz_item_id=attempt.quiz_item_id,
        user_answer=attempt.user_answer,
        is_correct=attempt.is_correct,
        score=attempt.score,
        created_at=attempt.submitted_at,
    )


@app.get("/quiz/attempts", response_model=list[QuizAttemptOut], tags=["quiz"])
async def get_quiz_attempts(
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_session),
):
    """获取用户的答题历史。"""
    from backend.db.crud import select as db_select

    attempts = await db_select(
        db, QuizAttempt,
        filters={"user_id": user_id},
        limit=limit,
        offset=skip,
    )
    return [QuizAttemptOut.model_validate(a) for a in attempts]


# ===========================================================
# 学习路径
# ===========================================================

from backend.services import pathway as pathway_svc


@app.get("/pathways", response_model=list[LearningPathOut], tags=["pathway"])
async def list_pathways(user_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """列举用户的学习路径。"""
    return await pathway_svc.list_pathways(user_id, db)


@app.post("/pathways", response_model=LearningPathOut, tags=["pathway"])
async def create_pathway(
    user_id: uuid.UUID,
    body: LearningPathCreate,
    db: AsyncSession = Depends(get_session),
):
    """创建新学习路径。"""
    return await pathway_svc.create_pathway(user_id, body, db)


@app.get("/pathways/{path_id}", response_model=LearningPathOut, tags=["pathway"])
async def get_pathway(
    path_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """获取单条学习路径详情。"""
    result = await pathway_svc.get_pathway(path_id, db)
    if not result:
        raise HTTPException(status_code=404, detail="Pathway not found")
    return result


@app.put("/pathways/{path_id}", response_model=LearningPathOut, tags=["pathway"])
async def update_pathway(
    path_id: uuid.UUID,
    user_id: uuid.UUID,
    body: LearningPathUpdate,
    db: AsyncSession = Depends(get_session),
):
    """更新学习路径标题/描述。"""
    result = await pathway_svc.update_pathway(path_id, user_id, body, db)
    if not result:
        raise HTTPException(status_code=404, detail="Pathway not found")
    return result


@app.delete("/pathways/{path_id}", tags=["pathway"])
async def delete_pathway(
    path_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """删除学习路径（级联删除路径项）。"""
    deleted = await pathway_svc.delete_pathway(path_id, user_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pathway not found")
    return {"deleted": True}


@app.post("/pathways/{path_id}/items", response_model=LearningPathItemOut, tags=["pathway"])
async def add_pathway_item(
    path_id: uuid.UUID,
    user_id: uuid.UUID,
    body: LearningPathItemCreate,
    db: AsyncSession = Depends(get_session),
):
    """向学习路径添加知识点项。"""
    result = await pathway_svc.add_pathway_item(path_id, user_id, body, db)
    if not result:
        raise HTTPException(status_code=404, detail="Pathway not found or unauthorized")
    return result


@app.put("/pathways/{path_id}/items/{item_id}", response_model=LearningPathItemOut, tags=["pathway"])
async def update_pathway_item(
    path_id: uuid.UUID,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    body: LearningPathItemUpdate,
    db: AsyncSession = Depends(get_session),
):
    """更新学习路径项（顺序/完成状态）。"""
    result = await pathway_svc.update_pathway_item(item_id, user_id, body, db)
    if not result:
        raise HTTPException(status_code=404, detail="Item not found or unauthorized")
    return result


@app.delete("/pathways/{path_id}/items/{item_id}", tags=["pathway"])
async def remove_pathway_item(
    path_id: uuid.UUID,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """从学习路径移除知识点项。"""
    deleted = await pathway_svc.remove_pathway_item(item_id, user_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found or unauthorized")
    return {"deleted": True}


# ===============================================================
# 文档导入
# ===============================================================

@app.post("/documents/import", tags=["documents"])
async def import_document(
    user_id: uuid.UUID,
    file: UploadFile = File(...),
    title: Optional[str] = None,
    db: AsyncSession = Depends(get_session),
):
    """
    上传并导入 PDF 文档。

    - 保存文件到 uploaded_docs 目录
    - 解析 PDF 内容并切分为文本块
    - 索引到向量库（供 RAG 检索使用）
    - 创建资源记录到数据库
    """
    import logging
    _log = logging.getLogger(__name__)
    file_name = file.filename or "unknown.pdf"
    if not file_name.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只支持 PDF 格式文件",
        )

    try:
        content = await file.read()
        saved_path = document_svc.save_uploaded_file(content, file_name)
        _log.info(f"[import_document] 文件 {file_name} 已保存到 {saved_path}，开始处理...")
        result = await document_svc.import_pdf(
            file_path=saved_path,
            user_id=user_id,
            title=title,
            db=db,
        )
        return {
            "success": True,
            "doc_id": result["doc_id"],
            "title": result["title"],
            "file_name": result["file_name"],
            "chunks": result["chunks"],
            "indexed": result["indexed"],
            "resource_id": result["resource_id"],
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导入失败：{str(e)}",
        )


@app.get("/documents", tags=["documents"])
async def list_documents(
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_session),
):
    """列举用户导入的文档列表。"""
    from backend.db.crud import select as db_select

    resources = await db_select(
        db, ResourceMeta,
        filters={"user_id": user_id, "resource_type": "doc"},
        limit=limit,
        offset=skip,
    )
    return [
        {
            "id": str(r.id),
            "title": r.title or "无标题",
            "kp_id": r.kp_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in resources
    ]


@app.delete("/documents/{doc_id}", tags=["documents"])
async def delete_document(
    doc_id: str,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """删除文档（同时从向量库移除）。"""
    from backend.db.crud import delete_by_id
    from backend.db.vector import delete_by_doc_id

    try:
        delete_by_doc_id(doc_id)
    except Exception:
        pass

    from backend.db.crud import select_one
    resource = await select_one(db, ResourceMeta, filters={"kp_id": doc_id, "user_id": user_id})
    if resource:
        await delete_by_id(db, ResourceMeta, resource.id)

    return {"deleted": True}


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


@app.get("/records", response_model=list[LearningRecordOut], tags=["records"])
async def list_records(
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_session),
):
    """获取用户的学习记录列表。"""
    return await resource_svc.list_learning_records(user_id, db, skip, limit)
