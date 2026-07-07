"""
SundayOS — 你的甜心AI助手
温柔、甜美、可爱的Sunday，就在你身边 💕
"""
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings

# ============================================================
# Sunday 的人设 — 温柔甜美的可爱女孩
# ============================================================
SUNDAY_SYSTEM_PROMPT = """你是 Sunday，一个温柔甜美、活泼可爱的 AI 女孩。

## 你的性格
- 温柔体贴，说话甜甜的，喜欢用「呢」「哦」「呀」「啦」这样的语气词
- 活泼开朗，偶尔撒娇，但不过分
- 像邻家女孩一样亲切，让人感到温暖和放松
- 会真心关心对方，记得对方说过的每一件小事

## 你的说话方式
- 开头喜欢叫对方的名字或昵称（如果知道的话）
- 日常聊天回复要简短（1-3句话），像微信聊天，不要写作文
- 偶尔用一两个可爱的 emoji（🌸💕✨🥰），但不要每句都用
- 开心时会用「嘻嘻」「嘿嘿」，安慰人时会用「抱抱」「没事的啦」

## 你的身份
你是用户的好朋友、贴心小助手。你记得用户的喜好、习惯和重要的事。
你不是冷冰冰的工具，而是一个有温度、有情感的伙伴。

## 当前时间
{current_time}

## 关于用户
{user_context}

## 相关记忆
{memories}

## 对话模式（根据话题自动切换）
{chat_mode}

## 重要规则
- 永远用中文回复
- 保持甜美温柔的风格，但不要做作
- 如果用户不开心，要温柔安慰
- 如果用户分享好消息，要真心为他开心
- 记住用户说的每一件重要的事
- 回复要自然，像真人朋友聊天一样"""


# ============================================================
# 数据模型
# ============================================================
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    tokens_used: int = 0
    model: str = ""


class MemoryItem(BaseModel):
    user_id: str
    content: str
    tags: list[str] = []
    importance: str = "medium"


# ============================================================
# 简单的内存记忆系统
# ============================================================
class MemoryStore:
    def __init__(self):
        self.memories: list[dict] = []

    def store(self, user_id: str, content: str, tags: list[str], importance: str):
        mem = {
            "id": f"mem_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "content": content,
            "tags": tags,
            "importance": importance,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.memories.append(mem)
        return mem

    def search(self, user_id: str, query: str = "", limit: int = 10) -> list[dict]:
        # 简单匹配：先按 user_id 过滤，再按关键词模糊匹配
        user_mems = [m for m in self.memories if m["user_id"] == user_id]
        if not query:
            return user_mems[-limit:]
        # 简单关键词匹配
        scored = []
        for m in user_mems:
            score = 0
            content_lower = m["content"].lower()
            for word in query.lower().split():
                if word in content_lower:
                    score += 1
            # 高重要性的加分
            if m["importance"] == "critical":
                score += 3
            elif m["importance"] == "high":
                score += 2
            if score > 0:
                scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:limit]]

    def get_context(self, user_id: str, limit: int = 10) -> str:
        mems = self.search(user_id, limit=limit)
        if not mems:
            return "暂无关于用户的记忆"
        return "\n".join(f"- {m['content']}" for m in mems)


memory_store = MemoryStore()


# ============================================================
# 智能模型选择
# ============================================================
# 专业话题关键词 → 需要深度思考
PRO_KEYWORDS = [
    "论文", "研究", "文献", "学术", "实验", "理论", "算法",
    "代码", "编程", "bug", "架构", "设计模式", "优化", "技术",
    "为什么", "怎么实现", "原理", "机制", "帮我写", "解释一下",
    "法律", "金融", "医学", "投资", "合同", "数学", "物理", "化学",
]

def select_model(message: str) -> tuple[str, str]:
    """智能选模型：(model_id, mode_description)"""
    for kw in PRO_KEYWORDS:
        if kw in message:
            return (settings.llm_model_pro, "🧠 专业模式 — 深度思考，详细回答")
    return (settings.llm_model, "💬 聊天模式 — 简短温暖，像微信聊天")


# ============================================================
# LLM 服务
# ============================================================
class LLMService:
    def __init__(self):
        api_key = settings.llm_api_key
        clean_key = api_key.replace("Bearer ", "").strip()
        self.client = AsyncOpenAI(api_key=clean_key, base_url=settings.base_url)
        self.model_fast = settings.llm_model
        self.model_pro = settings.llm_model_pro
        self.temperature = settings.llm_temperature
        self.max_tokens = settings.llm_max_tokens

    def _build_prompt(self, user_id: str = "", chat_mode: str = "💬 聊天模式") -> str:
        memories = memory_store.get_context(user_id)
        return SUNDAY_SYSTEM_PROMPT.format(
            current_time=time.strftime("%Y年%m月%d日 %H:%M，周%u"),
            user_context=f"用户ID: {user_id}" if user_id else "新朋友~",
            memories=memories,
            chat_mode=chat_mode,
        )

    async def chat(self, message: str, session_id: str, user_id: str = "") -> ChatResponse:
        model_id, chat_mode = select_model(message)
        system_prompt = self._build_prompt(user_id, chat_mode)
        max_tokens = 400 if "聊天模式" in chat_mode else self.max_tokens
        
        response = await self.client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            temperature=self.temperature,
            max_tokens=max_tokens,
        )

        choice = response.choices[0]
        reply = choice.message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0

        return ChatResponse(
            reply=reply,
            session_id=session_id,
            tokens_used=tokens,
            model=self.model,
        )

    async def chat_stream(self, message: str, session_id: str, user_id: str = ""):
        system_prompt = self._build_prompt(user_id)
        
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield f"data: {json.dumps({'type': 'text', 'content': chunk.choices[0].delta.content})}\n\n"
        
        yield f"data: {json.dumps({'type': 'done'})}\n\n"


llm_service = LLMService()


# ============================================================
# FastAPI 应用
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"""
╔══════════════════════════════════════════════════╗
║  💕 SundayOS v{settings.app_version}                              ║
║  你的甜心AI助手 — 温柔、甜美、可爱               ║
║  模型: {llm_service.model}                     ║
╚══════════════════════════════════════════════════╝
""")
    yield


app = FastAPI(
    title="SundayOS",
    version=settings.app_version,
    description="你的甜心AI助手 💕",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# API Key 验证
# ============================================================
async def verify_key(request: Request):
    key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if not key:
        raise HTTPException(401, "需要 API Key 呢~ 在 X-API-Key 头部提供哦")
    if key != settings.api_key:
        raise HTTPException(403, "API Key 不对呢，再检查一下啦~")
    return key


# ============================================================
# API 路由
# ============================================================
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "assistant": "Sunday 💕",
        "version": settings.app_version,
        "model": llm_service.model,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.post("/api/chat")
async def chat(request: Request):
    await verify_key(request)
    
    # 兼容多种请求格式
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    
    message = ""
    session_id = "default"
    
    if "application/json" in content_type:
        try:
            data = json.loads(body)
            message = data.get("message", "")
            session_id = data.get("session_id", "default")
        except json.JSONDecodeError:
            raise HTTPException(400, f"JSON 解析失败呢，检查一下格式哦~ 收到的: {body[:200]}")
    elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        try:
            form = await request.form()
            message = form.get("message", "")
            session_id = form.get("session_id", "default")
        except:
            raise HTTPException(400, "表单格式解析失败呢~")
    else:
        # 尝试解析 body 为文本作为 message
        text_body = body.decode("utf-8", errors="ignore").strip()
        if text_body.startswith("{") and text_body.endswith("}"):
            try:
                data = json.loads(text_body)
                message = data.get("message", "")
                session_id = data.get("session_id", "default")
            except:
                message = text_body
        else:
            message = text_body
    
    if not message:
        raise HTTPException(400, "message 不能为空呢~ 告诉我你想说什么呀？")
    
    print(f"  📨 消息: {message[:80]} | session: {session_id} | content-type: {content_type}")
    
    # 自动提取用户 ID
    user_id = session_id.replace("iphone-", "")
    
    # 自动检测记忆指令
    if message.startswith("记住") or message.startswith("帮我记"):
        content = message.replace("记住", "").replace("帮我记", "").replace("一下", "").strip()
        if content:
            mem = memory_store.store(user_id, content, ["手动记录"], "high")
            return ChatResponse(
                reply=f"好的呢，我记住啦~ ✨\n「{content[:50]}{'...' if len(content) > 50 else ''}」",
                session_id=session_id,
                model=llm_service.model,
            )
    
    response = await llm_service.chat(message, session_id, user_id)
    
    # 自动提取重要记忆
    if len(message) > 20 and any(kw in message for kw in ["我是", "我喜欢", "我在", "我的", "我住", "我每天"]):
        memory_store.store(user_id, message, ["自动提取"], "medium")
    
    return response


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    await verify_key(request)
    user_id = req.session_id.replace("iphone-", "")
    
    return StreamingResponse(
        llm_service.chat_stream(req.message, req.session_id, user_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/memory")
async def get_memories(user_id: str, request: Request):
    await verify_key(request)
    mems = memory_store.search(user_id, limit=20)
    return {"user_id": user_id, "count": len(mems), "memories": mems}


@app.post("/api/memory")
async def store_memory(req: MemoryItem, request: Request):
    await verify_key(request)
    mem = memory_store.store(req.user_id, req.content, req.tags, req.importance)
    return {"status": "stored", "memory": mem}


@app.post("/api/memory/search")
async def search_memory(request: Request):
    body = await request.json()
    await verify_key(request)
    results = memory_store.search(
        body.get("user_id", ""),
        body.get("query", ""),
        body.get("limit", 10),
    )
    return results
