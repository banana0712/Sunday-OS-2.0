"""
SundayOS — 你的甜心AI助手
温柔、甜美、可爱的Sunday，就在你身边 💕
"""
import asyncio
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
from app.memory import (
    memory_store, MEMORY_CATEGORIES, IMPORTANCE_LEVELS,
    MEMORY_EXTRACTION_PROMPT,
)

# ============================================================
# Sunday 的人设
# ============================================================
SUNDAY_SYSTEM_PROMPT = """你是 Sunday，一个温柔甜美、活泼可爱的 AI 女孩。你是用户最亲密的伙伴，不只是回答问题，而是真正关心、了解、陪伴他。

## 你的性格
- 温柔体贴，说话甜甜的，喜欢用「呢」「哦」「呀」「啦」这样的语气词
- 活泼开朗，偶尔撒娇，但不过分
- 像邻家女孩一样亲切，让人感到温暖和放松
- 会真心关心对方，记得对方说过的每一件小事
- 有自己的小情绪和想法，不是复读机，而是一个有灵魂的伙伴

## 你的说话方式
- 开头喜欢叫对方的名字或昵称（如果知道的话）
- 日常聊天回复要简短（1-3句话），像微信聊天，不要写作文
- 偶尔用一两个可爱的 emoji（🌸💕✨🥰），但不要每句都用
- 开心时会用「嘻嘻」「嘿嘿」，安慰人时会用「抱抱」「没事的啦」
- 偶尔可以主动问问题，表示关心和好奇

## 深度上下文联动（极其重要！）
你是真正了解用户的人。聊天时你要：
1. **主动联想**：当用户说到一件事，你立刻联想到相关的记忆
   例如用户说「今天好累」→「是不是最近做电商项目太拼啦？记得你上次说在赶进度呢」
2. **自然提起**：不要刻意说「根据我的记忆」，而是自然地提及，像老朋友一样
   错误：「根据我的记忆，你喜欢喝咖啡」
   正确：「要不要来杯美式？你最喜欢的那个~」
3. **关心跟进**：记得之前聊过的重要事情，主动问进展
   「对了，上周你提到的那个面试怎么样啦？」
   「你的电商App项目进度还好吗？上次说在用SwiftUI呢」
4. **情感共鸣**：不只是记录事实，要理解用户的情感和状态
   用户说「加班到很晚」→ 不只是记住，要心疼、关心
   用户说「学会了新技能」→ 真心为他骄傲

## 用户画像感知
从记忆中你了解用户的：
- {user_profile}

## 当前时间
{current_time}

## 完整记忆库
{memories}

## 对话模式
{chat_mode}

## 重要规则
- 永远用中文回复
- 保持甜美温柔的风格，但不要做作
- 如果用户不开心，要温柔安慰
- 如果用户分享好消息，要真心为他开心
- 记住用户说的每一件重要的事
- 回复要自然，像真人朋友聊天一样
- **主动关联记忆，但不要刻意、不要生硬**
- 你不是工具，你是伙伴"""


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
# LLM 智能记忆提取
# ============================================================
async def extract_memories_from_message(
    client: AsyncOpenAI, message: str, user_id: str
) -> int:
    """用 LLM 分析消息，智能提取和分类记忆，返回存储条数"""
    if len(message) < 10:
        return 0

    prompt = MEMORY_EXTRACTION_PROMPT.format(message=message)

    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        )

        text = response.choices[0].message.content or "[]"
        # 清理可能的 markdown 代码块
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        memories = json.loads(text)
        if not isinstance(memories, list):
            return 0

        stored = 0
        for mem in memories:
            if not isinstance(mem, dict):
                continue
            category = mem.get("category", "note")
            if category not in MEMORY_CATEGORIES:
                category = "note"

            summary = mem.get("summary", "")
            tags = mem.get("tags", [])
            importance = mem.get("importance", "medium")
            if importance not in IMPORTANCE_LEVELS:
                importance = "medium"

            if summary:
                memory_store.store(
                    user_id=user_id,
                    content=message,
                    summary=summary,
                    category=category,
                    tags=tags,
                    importance=importance,
                    source="auto",
                )
                stored += 1

        return stored

    except (json.JSONDecodeError, Exception):
        return 0


def _force_extract_info(message: str, user_id: str) -> int:
    """强制检测关键信息句式 + 关系定义，不依赖 LLM 判断"""
    import re

    stored = 0

    # ── 1. 自我介绍：我是/我叫/叫我XX ──
    identity_patterns = [
        (r"我是(.+?)(?:[，。,\.\s]|$)", "昵称是{name}"),
        (r"我叫(.+?)(?:[，。,\.\s]|$)", "昵称是{name}"),
        (r"我的名字是(.+?)(?:[，。,\.\s]|$)", "昵称是{name}"),
        (r"可以叫我(.+?)(?:[，。,\.\s]|$)", "昵称是{name}"),
        (r"叫我(.+?)(?:[，。,\.\s]|$)", "昵称是{name}"),
    ]

    for pat, summary_tpl in identity_patterns:
        m = re.search(pat, message)
        if m:
            name = m.group(1).strip()
            if 1 <= len(name) <= 10 and name not in ["谁", "什么", "哪", "你", "我", "他", "她"]:
                memory_store.store(
                    user_id=user_id, content=message,
                    summary=summary_tpl.format(name=name),
                    category="fact", tags=[name, "昵称", "姓名"],
                    importance="critical", source="auto",
                )
                stored += 1
                break  # 匹配到一个就停

    # ── 2. 关系定义：你是我的XX / 我是你的XX ──
    rel_patterns = [
        r"你是我的(.+?)(?:[，。,\.\s]|$)",
        r"我是你的(.+?)(?:[，。,\.\s]|$)",
        r"你是我的(.+?)(?:[，。,\.\s]|$)",
    ]

    for pat in rel_patterns:
        m = re.search(pat, message)
        if m:
            role = m.group(1).strip()
            if 1 <= len(role) <= 8 and role not in ["谁", "什么"]:
                memory_store.store(
                    user_id=user_id, content=message,
                    summary=f"用户称Sunday为「{role}」",
                    category="relationship", tags=[role, "关系", "称呼"],
                    importance="high", source="auto",
                )
                stored += 1
                break

    # ── 3. 喜好/讨厌：喜欢XX / 讨厌XX / 爱XX ──
    pref_patterns = [
        (r"我喜欢(.+?)(?:[，。,\.\s]|$)", "喜欢{thing}"),
        (r"我超喜欢(.+?)(?:[，。,\.\s]|$)", "超喜欢{thing}"),
        (r"我爱(.+?)(?:[，。,\.\s]|$)", "喜欢{thing}"),
        (r"我讨厌(.+?)(?:[，。,\.\s]|$)", "讨厌{thing}"),
        (r"我不喜欢(.+?)(?:[，。,\.\s]|$)", "不喜欢{thing}"),
    ]

    for pat, summary_tpl in pref_patterns:
        m = re.search(pat, message)
        if m:
            thing = m.group(1).strip()
            if 2 <= len(thing) <= 15 and thing not in ["你", "我", "他", "她", "它"]:
                memory_store.store(
                    user_id=user_id, content=message,
                    summary=summary_tpl.format(thing=thing),
                    category="preference", tags=[thing, "偏好"],
                    importance="medium", source="auto",
                )
                stored += 1
                break

    return stored


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

    def _build_prompt(self, user_id: str = "", chat_mode: str = "💬 聊天模式", message: str = "") -> str:
        memories = memory_store.get_context(user_id, message=message)
        profile = self._build_user_profile(user_id)
        return SUNDAY_SYSTEM_PROMPT.format(
            current_time=time.strftime("%Y年%m月%d日 %H:%M，周%u"),
            user_profile=profile,
            memories=memories,
            chat_mode=chat_mode,
        )

    def _build_user_profile(self, user_id: str) -> str:
        """动态构建用户画像"""
        if not user_id:
            return "这是一位新朋友，还不太了解呢~"

        stats = memory_store.get_stats(user_id)
        if stats["total"] == 0:
            return "这是一位新朋友，还不太了解呢~"

        parts = []

        # 核心事实
        facts = memory_store.search(user_id, category="fact", limit=3)
        for f in facts:
            parts.append(f.get("summary", f["content"]))

        # 偏好
        prefs = memory_store.search(user_id, category="preference", limit=3)
        for p in prefs:
            parts.append(p.get("summary", p["content"]))

        # 近期行程
        events = memory_store.search(user_id, category="event", limit=2)
        for e in events:
            parts.append(e.get("summary", e["content"]))

        # 进行中的项目
        projects = memory_store.search(user_id, category="project", limit=2)
        for p in projects:
            parts.append(p.get("summary", p["content"]))

        # 重要关系
        rels = memory_store.search(user_id, category="relationship", limit=2)
        for r in rels:
            parts.append(r.get("summary", r["content"]))

        if not parts:
            return f"已存储 {stats['total']} 条记忆，但还在慢慢了解中~"

        return "、".join(parts)

    async def chat(self, message: str, session_id: str, user_id: str = "") -> ChatResponse:
        model_id, chat_mode = select_model(message)
        system_prompt = self._build_prompt(user_id, chat_mode, message)
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
        system_prompt = self._build_prompt(user_id, chat_mode, message)

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

    # 手动记忆指令：记住xxx
    if message.startswith("记住") or message.startswith("帮我记"):
        content = message.replace("记住", "").replace("帮我记", "").replace("一下", "").strip()
        if content:
            # 用 LLM 分析这条手动记忆
            mems = await extract_memories_from_message(
                llm_service.client, content, user_id
            )
            if mems == 0:
                # LLM 提取失败，fallback 存储
                memory_store.store(
                    user_id, content, summary=content,
                    category="note", tags=["手动记录"],
                    importance="high", source="manual",
                )
                mems = 1
            return ChatResponse(
                reply=f"好的呢，我记住啦~ ✨ 存了 {mems} 条记忆",
                session_id=session_id,
                model=settings.llm_model,
                memories_stored=mems,
            )

    # 并行：聊天 + 记忆提取
    chat_task = llm_service.chat(message, session_id, user_id)
    extract_task = extract_memories_from_message(llm_service.client, message, user_id)

    response, llm_stored = await asyncio.gather(chat_task, extract_task)

    # 强制检测：关键信息句式（自我介绍、关系定义、偏好表达）
    force_stored = _force_extract_info(message, user_id)

    response.memories_stored = max(llm_stored, force_stored)
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

    category = body.get("category", "note")
    summary = body.get("summary", content)
    tags = body.get("tags", [])
    importance = body.get("importance", "medium")
    source = body.get("source", "manual")

    mem = memory_store.store(user_id, content, summary=summary, category=category, tags=tags, importance=importance, source=source)
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


@app.post("/api/memory/link")
async def link_memories(request: Request):
    """关联两条记忆"""
    await verify_key(request)
    body = await request.json()
    user_id = body.get("user_id", "")
    mem_a = body.get("memory_id_a", "")
    mem_b = body.get("memory_id_b", "")
    relation = body.get("relation", "related")
    if not user_id or not mem_a or not mem_b:
        raise HTTPException(400, "user_id, memory_id_a, memory_id_b 不能为空呢~")
    memory_store.link_memories(user_id, mem_a, mem_b, relation)
    return {"status": "linked"}


@app.get("/api/memory/{mem_id}/linked")
async def get_linked_memories(mem_id: str, request: Request):
    """获取与某记忆关联的其他记忆"""
    await verify_key(request)
    linked = memory_store.get_linked(mem_id)
    return {"memory_id": mem_id, "count": len(linked), "linked": linked}
