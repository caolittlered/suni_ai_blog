"""
Suni AI Blog - 主应用
企业知识智能体平台
"""

import os
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr
import yaml
import asyncio

from app.models import (
    User, UserSession, KnowledgeDocument,
    init_db, get_db, async_session
)
from app.auth import (
    hash_password, verify_password, create_access_token, get_current_user
)
from app.openclaw_client import OpenClawClient, get_user_client
from app.rag_engine import get_rag_engine
from app.document_processor import process_file

# 加载配置
CONFIG_PATH = os.getenv("SUNI_CONFIG", "./config.yaml")
with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# 创建应用
app = FastAPI(
    title="Suni AI Blog",
    description="企业知识智能体平台",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件和模板
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# ==================== 页面路由 ====================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """主页"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录页"""
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """注册页"""
    return templates.TemplateResponse("register.html", {"request": request})


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """聊天页面"""
    return templates.TemplateResponse("chat.html", {"request": request})


# ==================== API 模型 ====================

class RegisterRequest(BaseModel):
    email: EmailStr
    username: str
    password: str
    company: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    company: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    use_knowledge: bool = True


class ChatResponse(BaseModel):
    response: str
    session_key: str


# ==================== 认证 API ====================

@app.post("/api/register", response_model=UserResponse)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    # 检查邮箱是否存在
    result = await db.execute(select(User).where(User.email == request.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="邮箱已被注册")
    
    # 检查用户名
    result = await db.execute(select(User).where(User.username == request.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已被使用")
    
    # 创建用户
    user = User(
        email=request.email,
        username=request.username,
        hashed_password=hash_password(request.password),
        company=request.company
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    # 创建用户 session（OpenClaw 会话）
    session_key = f"user_{user.id}_{uuid.uuid4().hex[:8]}"
    user_session = UserSession(
        user_id=user.id,
        openclaw_session_key=session_key,
        knowledge_collection=f"user_{user.id}_kb"
    )
    db.add(user_session)
    await db.commit()
    
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        company=user.company
    )


@app.post("/api/login")
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    # 查找用户
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已被禁用")
    
    # 更新最后登录时间
    user.last_login = datetime.utcnow()
    await db.commit()
    
    # 创建 token
    access_token = create_access_token(data={"sub": user.id})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "company": user.company
        }
    }


@app.get("/api/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        username=current_user.username,
        company=current_user.company
    )


# ==================== 聊天 API ====================

@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """与智能体对话"""
    # 获取用户 session
    result = await db.execute(
        select(UserSession).where(UserSession.user_id == current_user.id)
    )
    user_session = result.scalar_one_or_none()
    
    if not user_session:
        raise HTTPException(status_code=400, detail="用户会话不存在")
    
    # 获取 OpenClaw 客户端
    client = await get_user_client(current_user.id, user_session.openclaw_session_key)
    
    # 获取 RAG 上下文（如果启用）
    context = None
    if request.use_knowledge:
        rag_engine = get_rag_engine(current_user.id)
        context = rag_engine.build_context(request.message)
    
    # 发送消息并流式获取响应
    try:
        full_response = ""
        async for delta in client.stream_chat(
            request.message,
            context=context
        ):
            full_response += delta
        
        return ChatResponse(
            response=full_response,
            session_key=user_session.openclaw_session_key
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"对话失败: {str(e)}")


@app.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """流式对话（SSE）"""
    # 获取用户 session
    result = await db.execute(
        select(UserSession).where(UserSession.user_id == current_user.id)
    )
    user_session = result.scalar_one_or_none()
    
    if not user_session:
        raise HTTPException(status_code=400, detail="用户会话不存在")
    
    async def generate():
        client = await get_user_client(current_user.id, user_session.openclaw_session_key)
        
        context = None
        if request.use_knowledge:
            rag_engine = get_rag_engine(current_user.id)
            context = rag_engine.build_context(request.message)
        
        try:
            async for delta in client.stream_chat(request.message, context=context):
                yield f"data: {delta}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")


# ==================== 知识库 API ====================

@app.post("/api/knowledge/upload")
async def upload_knowledge(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """上传知识文档"""
    # 检查文件类型
    allowed_extensions = config['knowledge']['allowed_extensions']
    file_ext = Path(file.filename).suffix.lower()
    
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_ext}"
        )
    
    # 检查文件大小
    max_size = config['knowledge']['max_file_size_mb'] * 1024 * 1024
    content = await file.read()
    if len(content) > max_size:
        raise HTTPException(status_code=400, detail="文件过大")
    
    # 保存文件
    upload_dir = Path(config['knowledge']['upload_dir']) / str(current_user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = upload_dir / file.filename
    with open(file_path, "wb") as f:
        f.write(content)
    
    # 创建文档记录
    doc = KnowledgeDocument(
        user_id=current_user.id,
        filename=file.filename,
        file_path=str(file_path),
        file_size=len(content),
        file_type=file_ext
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    
    # 异步索引文档
    asyncio.create_task(index_document_task(doc.id))
    
    return {
        "message": "文件上传成功，正在索引...",
        "document_id": doc.id,
        "filename": file.filename,
        "file_size": len(content)
    }


async def index_document_task(document_id: int):
    """异步索引文档"""
    async with async_session() as db:
        # 获取文档记录
        result = await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            return
        
        try:
            # 处理文档
            document = process_file(doc.file_path, doc.user_id)
            if not document:
                doc.index_error = "无法提取文档内容"
                await db.commit()
                return
            
            # 索引到向量数据库
            rag_engine = get_rag_engine(doc.user_id)
            rag_engine.init_vectorstore()
            chunk_count = rag_engine.index_documents([document])
            
            # 更新状态
            doc.is_indexed = True
            doc.chunk_count = chunk_count
            doc.indexed_at = datetime.utcnow()
            await db.commit()
            
            print(f"[Knowledge] 文档索引完成: {doc.filename}, {chunk_count} 个片段")
        
        except Exception as e:
            doc.index_error = str(e)
            await db.commit()
            print(f"[Knowledge] 索引失败: {e}")


@app.get("/api/knowledge/documents")
async def list_knowledge_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """列出用户的知识文档"""
    result = await db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.user_id == current_user.id)
        .order_by(KnowledgeDocument.uploaded_at.desc())
    )
    documents = result.scalars().all()
    
    return {
        "documents": [
            {
                "id": doc.id,
                "filename": doc.filename,
                "file_size": doc.file_size,
                "file_type": doc.file_type,
                "is_indexed": doc.is_indexed,
                "chunk_count": doc.chunk_count,
                "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
                "index_error": doc.index_error
            }
            for doc in documents
        ]
    }


@app.delete("/api/knowledge/documents/{document_id}")
async def delete_knowledge_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除知识文档"""
    result = await db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.id == document_id)
        .where(KnowledgeDocument.user_id == current_user.id)
    )
    doc = result.scalar_one_or_none()
    
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    
    # 删除文件
    file_path = Path(doc.file_path)
    if file_path.exists():
        file_path.unlink()
    
    # 删除记录
    await db.delete(doc)
    await db.commit()
    
    return {"message": "文档已删除"}


# ==================== 启动 ====================

@app.on_event("startup")
async def startup_event():
    """启动时初始化"""
    await init_db()
    print("[Suni AI] 服务启动完成")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=config['server']['host'],
        port=config['server']['port'],
        reload=config['server']['debug']
    )