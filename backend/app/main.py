"""
SundayOS — 你的甜心AI助手
温柔、甜美、可爱的Sunday，就在你身边 💕
"""
import json
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings
from app.memory import memory_store, MEMORY_CATEGORIES, IMPORTANCE_LEVELS

# ============================================================
# Sunday 的人设
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

## 对话模式
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
    memories_stored: int = 0


# ============================================================
# 智能模型选择
# ============================================================
PRO_KEYWORDS = [
    "论文", "研究", "文献", "学术", "实验", "理论", "算法",
    "代码", "编程", "bug", "架构", "设计模式", "优化", "技术",
    "为什么", "怎么实现", "原理", "机制", "帮我写", "解释一下",
    "法律", "金融", "医学", "投资", "合同", "数学", "物理", "化学",
]


def select_model(message: str) -> tuple[str, str]:
    for kw in PRO_KEYWORDS:
        if kw in message:
            return (settings.llm_model_pro or settings.llm_model, "🧠 专业模式")
    return (settings.llm_model, "💬 聊天模式")


# ============================================================
# 智能记忆分类
# ============================================================
def classify_memory(content: str) -> str:
    """根据内容自动分类记忆"""
    content_lower = content.lower()
    if any(w in content_lower for w in ["喜欢", "最爱", "偏好", "讨厌", "好吃", "好喝"]):
        return "preference"
    if any(w in content_lower for w in ["明天", "后天", "下周", "面试", "会议", "旅行", "约会", "日程", "安排"]):
        return "event"
    if any(w in content_lower for w in ["朋友", "女朋友", "男朋友", "家人", "同事", "老板", "同学"]):
        return "relationship"
    if any(w in content_lower for w in ["目标", "计划", "想学", "打算", "希望", "梦想"]):
        return "goal"
    if any(w in content_lower for w in ["每天", "习惯", "总是", "经常", "一般会"]):
        return "habit"
    return "fact"


# ============================================================
# LLM 服务
# ============================================================
class LLMService:
    def __init__(self):
        api_key = settings.llm_api_key
        clean_key = api_key.replace("Bearer ", "").strip()
        self.client = AsyncOpenAI(api_key=clean_key, base_url=settings.base_url)
        self.model_fast = settings.llm_model
        self.model_pro = settings.llm_model_pro or settings.llm_model
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
            model=model_id,
        )

    async def chat_stream(self, message: str, session_id: str, user_id: str = ""):
        model_id, chat_mode = select_model(message)
        system_prompt = self._build_prompt(user_id, chat_mode)

        stream = await self.client.chat.completions.create(
            model=model_id,
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
║  聊天: {settings.llm_model}                     ║
║  专业: {settings.llm_model_pro or settings.llm_model}                     ║
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
# API 路由 — 聊天
# ============================================================
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "assistant": "Sunday 💕",
        "version": settings.app_version,
        "model_chat": settings.llm_model,
        "model_pro": settings.llm_model_pro or settings.llm_model,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.post("/api/chat")
async def chat(request: Request):
    await verify_key(request)

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
            raise HTTPException(400, "JSON 解析失败呢，检查一下格式哦~")
    elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        try:
            form = await request.form()
            message = str(form.get("message", ""))
            session_id = str(form.get("session_id", "default"))
        except Exception:
            raise HTTPException(400, "表单格式解析失败呢~")
    else:
        text_body = body.decode("utf-8", errors="ignore").strip()
        if text_body.startswith("{"):
            try:
                data = json.loads(text_body)
                message = data.get("message", "")
                session_id = data.get("session_id", "default")
            except json.JSONDecodeError:
                message = text_body
        else:
            message = text_body

    if not message:
        raise HTTPException(400, "message 不能为空呢~ 告诉我你想说什么呀？")

    user_id = session_id.replace("iphone-", "")
    memories_stored = 0

    # 手动记忆指令
    if message.startswith("记住") or message.startswith("帮我记"):
        content = message.replace("记住", "").replace("帮我记", "").replace("一下", "").strip()
        if content:
            category = classify_memory(content)
            memory_store.store(user_id, content, category=category, tags=["手动记录"], importance="high", source="manual")
            return ChatResponse(
                reply=f"好的呢，我记住啦~ ✨\n[{MEMORY_CATEGORIES.get(category, category)}] {content[:50]}{'...' if len(content) > 50 else ''}",
                session_id=session_id,
                model=settings.llm_model,
                memories_stored=1,
            )

    # 对话
    response = await llm_service.chat(message, session_id, user_id)

    # 自动提取重要记忆
    if len(message) > 15 and any(kw in message for kw in [
        "我是", "我喜欢", "我在", "我的", "我住", "我每天",
        "我习惯", "我讨厌", "我计划", "我打算", "我明天", "我后天",
        "女朋友", "男朋友", "家人", "朋友是",
    ]):
        category = classify_memory(message)
        memory_store.store(user_id, message, category=category, tags=["自动提取"], importance="medium", source="auto")
        memories_stored = 1

    response.memories_stored = memories_stored
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


# ============================================================
# API 路由 — 记忆管理
# ============================================================
@app.get("/api/memory/stats")
async def memory_stats(user_id: str, request: Request):
    """获取记忆统计信息"""
    await verify_key(request)
    return memory_store.get_stats(user_id)


@app.get("/api/memory")
async def list_memories(
    user_id: str,
    request: Request,
    category: str = Query("", description="按分类筛选"),
    importance: str = Query("", description="按重要性筛选"),
    limit: int = Query(20),
    offset: int = Query(0),
):
    """获取记忆列表"""
    await verify_key(request)
    mems = memory_store.search(user_id, category=category, importance=importance, limit=limit, offset=offset)
    return {
        "user_id": user_id,
        "count": len(mems),
        "categories": MEMORY_CATEGORIES,
        "importance_levels": {k: v["label"] for k, v in IMPORTANCE_LEVELS.items()},
        "memories": mems,
    }


@app.post("/api/memory")
async def store_memory(request: Request):
    """手动存储一条记忆"""
    await verify_key(request)
    body = await request.json()

    user_id = body.get("user_id", "")
    content = body.get("content", "")
    if not user_id or not content:
        raise HTTPException(400, "user_id 和 content 不能为空呢~")

    category = body.get("category", classify_memory(content))
    tags = body.get("tags", [])
    importance = body.get("importance", "medium")
    source = body.get("source", "manual")

    mem = memory_store.store(user_id, content, category=category, tags=tags, importance=importance, source=source)
    return {"status": "stored", "memory": mem}


@app.post("/api/memory/search")
async def search_memory(request: Request):
    """搜索记忆"""
    await verify_key(request)
    body = await request.json()
    results = memory_store.search(
        body.get("user_id", ""),
        query=body.get("query", ""),
        category=body.get("category", ""),
        importance=body.get("importance", ""),
        limit=body.get("limit", 20),
    )
    return {"query": body.get("query", ""), "count": len(results), "memories": results}


@app.put("/api/memory/{mem_id}")
async def update_memory(mem_id: str, request: Request):
    """更新记忆"""
    await verify_key(request)
    body = await request.json()
    result = memory_store.update(mem_id, **body)
    if not result:
        raise HTTPException(404, "找不到这条记忆呢~")
    return {"status": "updated", "memory": result}


@app.delete("/api/memory/{mem_id}")
async def delete_memory(mem_id: str, request: Request):
    """删除记忆"""
    await verify_key(request)
    if memory_store.delete(mem_id):
        return {"status": "deleted", "memory_id": mem_id}
    raise HTTPException(404, "找不到这条记忆呢~")


@app.post("/api/memory/{mem_id}/archive")
async def archive_memory(mem_id: str, request: Request):
    """归档记忆"""
    await verify_key(request)
    if memory_store.archive(mem_id):
        return {"status": "archived", "memory_id": mem_id}
    raise HTTPException(404, "找不到这条记忆呢~")


@app.post("/api/memory/{mem_id}/unarchive")
async def unarchive_memory(mem_id: str, request: Request):
    """取消归档"""
    await verify_key(request)
    if memory_store.unarchive(mem_id):
        return {"status": "unarchived", "memory_id": mem_id}
    raise HTTPException(404, "找不到这条记忆呢~")


@app.get("/api/memory/export")
async def export_memories(user_id: str, request: Request):
    """导出所有记忆"""
    await verify_key(request)
    mems = memory_store.export(user_id)
    return {"user_id": user_id, "count": len(mems), "memories": mems}


@app.post("/api/memory/decay")
async def decay_memories(user_id: str, days: int = 30, request: Request = None):
    """手动触发记忆衰减"""
    await verify_key(request)
    memory_store.apply_decay(user_id, days)
    return {"status": "decay_applied", "user_id": user_id, "days": days}
