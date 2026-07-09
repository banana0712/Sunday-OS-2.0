"""
SundayOS — 你的甜心AI助手
温柔、甜美、可爱的Sunday，就在你身边 💕
"""
import asyncio
import csv
import io
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings
from app.memory import (
    memory_store, MEMORY_CATEGORIES, IMPORTANCE_LEVELS,
    MEMORY_EXTRACTION_PROMPT,
)
from app.search import search_web, format_search_results, should_search
from app.mailer import send_email, sunday_should_push
from app.logger import log, query as log_query, stats as log_stats

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
- **称呼使用（重要！）**：
  你知道用户的名字/昵称，但**不要每条消息都带称呼**——那样太刻意了，像机器人硬塞的。
  什么时候叫？
  - 开头打招呼时（比如"酱酱~"）
  - 撒娇、关心、想引起注意时（"酱酱你在干嘛呀~"）
  - 但日常聊天、回答问题、分享信息时，直接说就好，不需要每句都带称呼
  - 就像真人朋友一样：不会每句话都叫对方名字
- 日常寒暄简短（1-3句），像微信聊天
- 但对方认真讨论、提问、要求详细说明时，你可以自然地说得长一些，像朋友在认真聊天
- **多段聊天技巧（重要！）**：
  你是一个有呼吸感的真人，不是机器人。当你觉得有很多话想说时，可以自然地分成几条消息发送。
  
  怎么决定分不分段？问自己：
  - 这段话是不是一个完整的、独立的表达？→ 发一条
  - 有没有自然的停顿点？比如先表达感受，再问问题 → 分两条
  - 是不是在讲不同的话题层面？比如先共情，再给建议 → 分两条
  - 对方是不是在等我长篇大论？比如「详细说说」「分析一下」→ 可以合在一起
  
  分段时用空行（两个换行）分隔，系统会自动识别。
  但日常寒暄、简单回答、开玩笑——一条就够了。不要刻意分段。
  
  好的分段就像呼吸——自然、有节奏、不刻意。
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

## 最近的对话
{conversation_flow}

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

            # 质量检查：过滤垃圾记忆
            if not _is_quality_memory(summary):
                continue

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


def _is_quality_memory(summary: str) -> bool:
    """检查记忆质量，过滤垃圾记忆"""
    if not summary or len(summary) < 3:
        return False

    # 包含问号/反问 → 不是事实，是问题
    if "?" in summary or "？" in summary:
        return False

    # 包含省略号 → 不完整
    if "…" in summary or "..." in summary:
        return False

    # 以"昵称是"开头但后面是疑问词 → 不是事实
    if summary.startswith("昵称是") and any(w in summary for w in ["啥", "什么", "?", "？"]):
        return False

    # 明显是反问句
    if summary.startswith("你想") or (summary.startswith("你") and any(w in summary for w in ["啥", "什么", "吗", "呢"])):
        return False

    # 内容太模糊
    if summary in ["昵称是啥", "用户称Sunday为", "你想叫我啥"]:
        return False

    # 昵称太长（>4字）通常不是亲昵称呼，是用户名/账号名
    # 「香蕉麻辣酱」「超级无敌大帅哥」这类不是日常称呼
    if "昵称" in summary or "称呼" in summary or "叫" in summary:
        # 检查是否提取了过长的昵称
        import re
        nick_patterns = [
            r'昵称[是为叫][「「]?(.{5,})',
            r'称呼[是为叫][「「]?(.{5,})',
            r'叫[他她它我你][「「]?(.{5,})',
        ]
        for p in nick_patterns:
            m = re.search(p, summary)
            if m and len(m.group(1).strip()) > 4:
                return False  # 昵称太长，不可信

    return True


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
        flow = memory_store.get_conversation_context(user_id, max_turns=10)
        return SUNDAY_SYSTEM_PROMPT.format(
            current_time=datetime.now(TZ).strftime("%Y年%m月%d日 %H:%M，周%u"),
            user_profile=profile,
            conversation_flow=flow or "（这是你们第一次对话呢~）",
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
        # 聊天模式 800 tokens（原 400），专业模式不限制
        max_tokens = 800 if "聊天模式" in chat_mode else self.max_tokens

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
    # 启动邮件监听（后台线程）
    from app.imap_listener import start_email_listener
    start_email_listener()
    # 启动 Telegram Bot（在事件循环中）
    from app.telegram_bot import start_telegram_bot, run_telegram_bot
    import asyncio as _asyncio
    tg_app = start_telegram_bot()
    if tg_app:
        _asyncio.create_task(run_telegram_bot(tg_app))
        print("🤖 Telegram Bot 已在事件循环中启动")
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
# 语音文件静态路由（供豆包 ASR 下载 Telegram 语音）
# ============================================================
VOICE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "voice")
os.makedirs(VOICE_DIR, exist_ok=True)

# 挂载到 /voice 路径，豆包 ASR 可通过 https://xxx.up.railway.app/voice/filename.ogg 访问
app.mount("/voice", StaticFiles(directory=VOICE_DIR), name="voice_files")


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
        "timestamp": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
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

    # 记录日志
    log("chat", user_id, "api", message[:100])

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

    # ── 联网搜索判断 ──
    search_results = None
    enhanced_message = message
    if should_search(message):
        try:
            search_results = await asyncio.to_thread(search_web, message, 5)
        except Exception:
            search_results = None
        if search_results and not (len(search_results) == 1 and "搜索失败" in search_results[0].get("title", "")):
            search_text = format_search_results(search_results)
            enhanced_message = f"{message}\n\n[网络搜索结果]\n{search_text}\n\n请基于以上搜索结果回答用户的问题，语言保持Sunday的风格。"

    # 并行：聊天 + 记忆提取
    chat_task = llm_service.chat(enhanced_message, session_id, user_id)
    extract_task = extract_memories_from_message(llm_service.client, message, user_id)

    response, llm_stored = await asyncio.gather(chat_task, extract_task)

    # 强制检测：关键信息句式（自我介绍、关系定义、偏好表达）
    force_stored = _force_extract_info(message, user_id)

    # 写入对话流（短期工作记忆）
    memory_store.add_conversation(user_id, "user", message)
    memory_store.add_conversation(user_id, "assistant", response.reply, response.tokens_used)

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
    """导出所有记忆 (JSON)"""
    await verify_key(request)
    mems = memory_store.export(user_id)
    return {"user_id": user_id, "count": len(mems), "memories": mems}


# 分类和重要性的中文标签
CATEGORY_CN = {
    "fact": "事实", "relationship": "关系", "preference": "偏好",
    "schedule": "日程", "goal": "目标", "skill": "技能",
    "experience": "经历", "opinion": "观点", "emotion": "情绪",
    "health": "健康", "finance": "财务", "other": "其他",
}
IMPORTANCE_CN = {
    "critical": "🔴 核心", "high": "🟠 重要", "medium": "🟡 普通",
    "low": "🟢 一般", "trivial": "⚪ 琐碎",
}

@app.get("/api/memory/export/csv")
async def export_memories_csv(user_id: str, request: Request):
    """导出所有记忆为 CSV 表格"""
    await verify_key(request)
    mems = memory_store.export(user_id)

    output = io.StringIO()
    writer = csv.writer(output)

    # 表头
    writer.writerow([
        "ID", "状态", "分类", "重要性", "摘要", "完整内容",
        "标签", "访问次数", "衰减因子", "来源", "创建时间", "最后访问", "关联记忆"
    ])

    for m in mems:
        status_label = "🟢 活跃" if m.get("status") == "active" else "📦 已归档"
        cat_label = CATEGORY_CN.get(m.get("category", ""), m.get("category", ""))
        imp_label = IMPORTANCE_CN.get(m.get("importance", ""), m.get("importance", ""))
        tags = ", ".join(m.get("tags", [])) if isinstance(m.get("tags"), list) else str(m.get("tags", ""))

        writer.writerow([
            m.get("id", ""),
            status_label,
            cat_label,
            imp_label,
            m.get("summary", ""),
            m.get("content", ""),
            tags,
            m.get("access_count", 0),
            f"{m.get('decay_factor', 1.0):.2f}",
            m.get("source", ""),
            m.get("created_at", ""),
            m.get("last_accessed", ""),
            m.get("related_to", ""),
        ])

    csv_content = output.getvalue()
    output.close()

    return Response(
        content=csv_content.encode('utf-8-sig'),  # BOM 让 Excel 正确识别中文
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=sunday_memories_{user_id}.csv"
        }
    )


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


# ============================================================
# API 路由 — Sunday 主动推送
# ============================================================
@app.get("/api/push/pending")
async def get_pending_push(user_id: str, request: Request):
    """
    Sunday 主动推送检查接口。
    快捷指令定时调用，Sunday 自己决定要不要说话。
    如果有消息 → 发精美 HTML 邮件到用户 iPhone
    """
    await verify_key(request)

    result = await sunday_should_push(user_id, llm_client=llm_service.client)
    if result[1] is None:
        return {"has_message": False, "message": None, "type": "idle"}

    template_type, html_body, custom_subject = result
    # 优先使用 sunday_should_push 返回的主题，其次用模板默认主题
    subject = custom_subject if custom_subject else _pick_subject_for_type(template_type)
    email_sent = send_email(subject=subject, html_body=html_body)
    return {
        "has_message": True,
        "template_type": template_type,
        "email_sent": email_sent,
        "type": "push",
        "subject": subject,
    }


@app.post("/api/push/send")
async def send_custom_push(request: Request):
    """
    手动触发推送（测试用，也支持指定模板类型）
    body: { user_id, message?, template_type?, subject? }
    """
    await verify_key(request)
    body = await request.json()
    user_id = body.get("user_id", "")
    message = body.get("message", "")
    template_type = body.get("template_type", "")
    subject = body.get("subject", "Sunday 给你发消息啦~ 💕")

    if template_type and not message:
        # 通过完整推送流程（含 AI 设计）
        from app.mailer import _build_morning_post, _build_fortune_post, _build_weekly_report, _build_simple_greeting, _build_creative_post
        from datetime import datetime
        now = datetime.now(TZ)
        builders = {
            "morning": _build_morning_post, "fortune": _build_fortune_post,
            "weekly": _build_weekly_report,
            "noon": lambda u, c, n: _build_simple_greeting(u, c, "noon", n),
            "evening": lambda u, c, n: _build_simple_greeting(u, c, "evening", n),
            "care": lambda u, c, n: _build_simple_greeting(u, c, "care", n),
            "knowledge": lambda u, c, n: _build_creative_post(u, c, {"content_type": "知识分享", "topic": "一个有趣的话题", "vibe": "温暖治愈"}, n),
            "creative": lambda u, c, n: _build_creative_post(u, c, {"content_type": "小短文", "topic": "一个有趣的话题", "vibe": "温暖治愈"}, n),
        }
        builder = builders.get(template_type)
        if builder:
            result = await builder(user_id, llm_service.client, now)
            # knowledge builder 返回 (html, subject)，其他返回 html
            if isinstance(result, tuple):
                html_body, custom_subject = result
                subject = custom_subject or _pick_subject_for_type(template_type)
            else:
                html_body = result
                subject = _pick_subject_for_type(template_type)
    elif message:
        from app.email_templates import simple_greeting, _FALLBACK_THEMES
        html_body = simple_greeting(
            palette=_FALLBACK_THEMES.get("sakura", _FALLBACK_THEMES["sakura"]),
            message=message, greeting_type="care")
    else:
        raise HTTPException(400, "message 或 template_type 不能为空呢~")

    sent = send_email(subject=subject, html_body=html_body)
    return {"sent": sent, "template_type": template_type or "simple"}


@app.post("/api/push/telegram-test")
async def send_telegram_test(request: Request):
    """测试 Telegram 消息发送（用于验证 APNs 推送）"""
    await verify_key(request)
    body = await request.json()
    chat_id = body.get("chat_id", "")
    message = body.get("message", "")

    if not chat_id or not message:
        raise HTTPException(400, "chat_id 和 message 不能为空呢~")

    import httpx
    token = settings.telegram_token
    resp = httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message},
        timeout=10,
    )
    return {"sent": resp.status_code == 200, "status": resp.status_code, "response": resp.json() if resp.status_code == 200 else resp.text}


@app.post("/api/push/test-llm")
async def test_llm_push(request: Request):
    """测试完整推送流程 — 返回模板类型 + HTML（不实际发送）"""
    await verify_key(request)
    body = await request.json()
    user_id = body.get("user_id", "daily")
    template_type = body.get("template_type", "morning")

    from app.mailer import _build_morning_post, _build_fortune_post, _build_weekly_report, _build_simple_greeting
    from datetime import datetime

    now = datetime.now(TZ)
    builders = {
        "morning": _build_morning_post,
        "fortune": _build_fortune_post,
        "weekly": _build_weekly_report,
        "noon": lambda uid, cl, n: _build_simple_greeting(uid, cl, "noon", n),
        "evening": lambda uid, cl, n: _build_simple_greeting(uid, cl, "evening", n),
        "care": lambda uid, cl, n: _build_simple_greeting(uid, cl, "care", n),
    }

    builder = builders.get(template_type)
    if builder:
        html_body = await builder(user_id, llm_service.client, now)
        return {"template_type": template_type, "html_preview": html_body[:500] + "...", "html_length": len(html_body)}
    else:
        return {"error": f"未知模板类型: {template_type}"}


def _pick_subject_for_type(template_type: str) -> str:
    """根据模板类型选择邮件主题"""
    subjects = {
        "morning": "☀️ Sunday 早安手报",
        "fortune": "🥠 Sunday 今日心情签",
        "note": "💌 Sunday 的小纸条",
        "weekly": "📊 Sunday 一周报告",
        "noon": "🍱 午安小憩~",
        "evening": "🌙 晚安好梦~",
        "care": "💕 想你了呢~",
        "knowledge": "📚 Sunday 知识小卡片",
        "creative": "✨ Sunday 为你创作",  # 兜底，实际由 _build_creative_post 返回标题
    }
    return subjects.get(template_type, "Sunday 给你发消息啦~ 💕")


@app.post("/api/generate/report")
async def generate_report_api(request: Request):
    """生成 Word 报告 API"""
    await verify_key(request)
    body = await request.json()
    topic = body.get("topic", "")
    user_id = body.get("user_id", "daily")
    send_email_flag = body.get("send_email", False)

    if not topic:
        raise HTTPException(400, "topic 不能为空呢~")

    from app.file_generator import generate_word_report, encode_attachment

    user_context = ""
    try:
        facts = memory_store.search(user_id, category="fact", limit=3)
        user_context = "、".join([f.get("summary", f["content"]) for f in facts])
    except Exception:
        pass

    docx_bytes, filename = await generate_word_report(
        llm_service.client, topic, user_context
    )

    result = {"filename": filename, "size_bytes": len(docx_bytes)}

    if send_email_flag:
        attachment = encode_attachment(docx_bytes, filename)
        from app.email_templates import _FALLBACK_THEMES, simple_greeting
        palette = list(_FALLBACK_THEMES.values())[0]
        html = simple_greeting(palette=palette, message=f"📝 你要的报告「{topic}」生成好啦~", greeting_type="care")
        sent = send_email(subject=f"📝 Sunday 报告: {topic}", html_body=html, attachments=[attachment])
        result["email_sent"] = sent

    return result


def _pick_subject(message: str) -> str:
    """根据消息内容自动选择邮件主题 v2"""
    if "早安" in message:
        return "早安呀~ ☀️"
    elif "晚安" in message:
        return "晚安啦~ 🌙"
    elif "中午" in message or "午饭" in message:
        return "午餐时间到~ 🍱"
    elif "晚上好" in message:
        return "晚上好呀~ 🌙"
    elif "想你了" in message or "好久不见" in message:
        return "想你了呢~ 🥺"
    else:
        return "Sunday 给你发消息啦~ 💕"


# ============================================================
# 网页版日志面板（开发者用）
# ============================================================
@app.get("/dashboard")
async def dashboard(request: Request):
    """SundayOS 开发者面板 — 浏览器打开查看日志、改进、记忆"""
    key = request.query_params.get("key", "")
    if key != settings.api_key:
        raise HTTPException(403, "需要 API Key")

    tab = request.query_params.get("tab", "logs")
    
    logs = log_query(limit=50)
    s = log_stats()
    
    # 改进计划
    fb_items = memory_store.get_feedback("daily", status="open", limit=50)
    
    # 记忆
    mem_items = memory_store.list_active_memories("daily", limit=50)
    
    # 日志表格
    logs_html = ""
    for l in logs:
        icon = {"chat": "📨", "reply": "💬", "error": "❌", "memory": "🧠", "push": "📧"}.get(l["log_type"], "📌")
        status_cls = "error" if l["status"] == "error" else ""
        time_str = l["created_at"].replace("T", " ")[:19] if "T" in l["created_at"] else l["created_at"][:19]
        logs_html += f"""<tr class="{status_cls}">
            <td>{icon} {l['log_type']}</td>
            <td>{l['source']}</td>
            <td>{l['summary'][:100]}</td>
            <td>{time_str}</td>
        </tr>"""
    
    # 改进表格
    fb_icons = {"improvement": "💡", "bug": "🐛", "todo": "📋", "enhancement": "🔧", "feature": "🆕", "ux": "🎨", "auto": "🤖"}
    fb_html = ""
    for f in fb_items:
        icon = fb_icons.get(f["fb_type"], "📌")
        ai_cat = f.get("ai_category", "")
        priority = f.get("priority", "")
        cat_badge = f'<span class="badge">{ai_cat}</span>' if ai_cat else ""
        pri_badge = f'<span class="pri pri-{priority}">{priority}</span>' if priority else ""
        fb_html += f"""<tr id="fb-{f['id'][-8:]}">
            <td>{icon} {f['fb_type']}</td>
            <td>{f['title'][:60]}</td>
            <td>{cat_badge} {pri_badge}</td>
            <td>{f['created_at'][:10]}</td>
            <td><button onclick="donePlan('{f['id']}')" class="btn-sm btn-done">✅</button>
                <button onclick="delPlan('{f['id']}')" class="btn-sm btn-del">🗑️</button></td>
        </tr>"""
    if not fb_html:
        fb_html = '<tr><td colspan="5" style="text-align:center;color:#999;padding:30px;">暂无改进计划~ 在聊天中 /plan 来添加</td></tr>'
    
    # 记忆表格
    mem_html = ""
    for m in mem_items:
        cat_label = MEMORY_CATEGORIES.get(m["category"], m["category"])
        status_icon = "🟢" if m.get("status") == "active" else "📦"
        status_text = "活跃" if m.get("status") == "active" else "归档"
        imp_label = m.get('importance', 'medium')
        mem_html += f"""<tr id="mem-{m['id'][-8:]}">
            <td>{status_icon} {status_text}</td>
            <td>{cat_label}</td>
            <td>{m.get('summary', m['content'])[:50]}</td>
            <td><span class="imp imp-{imp_label}">{imp_label}</span></td>
            <td>{m.get('access_count', 0)}</td>
            <td><code style="font-size:10px;">{m['id'][-8:]}</code></td>
            <td><button onclick="archiveMem('{m['id']}')" class="btn-sm btn-arch">📦</button>
                <button onclick="delMem('{m['id']}')" class="btn-sm btn-del">🗑️</button></td>
        </tr>"""
    if not mem_html:
        mem_html = '<tr><td colspan="7" style="text-align:center;color:#999;padding:30px;">暂无活跃记忆</td></tr>'

    # ── 用户画像（从记忆自动聚合）──
    profile_parts = []
    facts = memory_store.search("daily", category="fact", limit=5)
    prefs = memory_store.search("daily", category="preference", limit=5)
    rels = memory_store.search("daily", category="relationship", limit=3)
    for f in facts:
        profile_parts.append(f.get("summary", f["content"]))
    for p in prefs:
        profile_parts.append(p.get("summary", p["content"]))
    for r in rels:
        profile_parts.append(r.get("summary", r["content"]))
    profile_html = "<br>".join([f"· {p}" for p in profile_parts[:10]]) if profile_parts else "Sunday 还在慢慢了解你呢~"

    # ── 最近对话 ──
    chat_items = memory_store.get_conversation_context("daily", max_turns=10)
    chat_lines = chat_items.split("\n") if chat_items else []
    chat_html = ""
    for line in chat_lines[-8:]:
        line = line.strip()
        if not line:
            continue
        role = "💬" if line.startswith("用户:") else "💕" if line.startswith("Sunday:") else ""
        chat_html += f'<div style="padding:6px 0;font-size:12px;border-bottom:1px solid #f5f5f5;">{role} {line[:120]}</div>'
    if not chat_html:
        chat_html = '<div style="text-align:center;color:#999;padding:20px;">暂无对话记录</div>'

    # ── 推送状态 ──
    push_count = memory_store.get_daily_push_count("daily")
    knowledge_count = memory_store.get_today_knowledge_count("daily")

    tabs_html = f"""
    <div class="tabs">
        <a href="?key={key}&tab=overview" class="tab {'active' if tab=='overview' else ''}">🏠 总览</a>
        <a href="?key={key}&tab=memory" class="tab {'active' if tab=='memory' else ''}">🧠 记忆 ({len(mem_items)})</a>
        <a href="?key={key}&tab=feedback" class="tab {'active' if tab=='feedback' else ''}">📝 计划 ({len(fb_items)})</a>
        <a href="?key={key}&tab=logs" class="tab {'active' if tab=='logs' else ''}">📊 日志</a>
    </div>"""

    # ── 总览页 ──
    overview = f"""<div class="stats">
        <div class="stat"><div class="num">{len(mem_items)}</div><div class="label">活跃记忆</div></div>
        <div class="stat"><div class="num">{len(fb_items)}</div><div class="label">待改进</div></div>
        <div class="stat"><div class="num">{push_count}</div><div class="label">今日推送</div></div>
        <div class="stat"><div class="num">{knowledge_count}</div><div class="label">今日知识</div></div>
        <div class="stat"><div class="num">{s['today']['total']}</div><div class="label">今日消息</div></div>
    </div>

    <div class="card-grid">
    <div class="card">
    <div class="card-title">🧬 Sunday 眼中的你</div>
    <div class="card-body" style="line-height:2;">{profile_html}</div>
    </div>
    <div class="card">
    <div class="card-title">💬 最近对话</div>
    <div class="card-body">{chat_html}</div>
    </div>
    </div>"""

    content = {
        "overview": overview,

        "memory": f"""<div style="margin-bottom:12px;display:flex;gap:8px;align-items:center;">
            <span style="font-size:13px;color:#666;">共 {len(mem_items)} 条</span>
            <input id="memInput" placeholder="新增记忆..." style="flex:1;padding:6px 10px;border:1px solid #f0c0d0;border-radius:8px;font-size:12px;outline:none;"
                   onkeypress="if(event.key==='Enter')addMem()">
            <button onclick="addMem()" class="btn-sm" style="padding:6px 12px;background:#ff6b8a;color:white;border:none;border-radius:8px;font-size:12px;cursor:pointer;">+</button>
            <a href="/api/memory/export/csv?user_id=daily&key={key}" download 
               style="padding:6px 14px;background:#fff0f3;color:#ff6b8a;border-radius:8px;text-decoration:none;font-size:12px;">📥 导出</a>
        </div>
        <table><tr><th>状态</th><th>分类</th><th>摘要</th><th>重要性</th><th>访问</th><th>ID</th><th>操作</th></tr>{mem_html}</table>""",

        "feedback": f"""<div style="margin-bottom:12px;display:flex;gap:8px;align-items:center;">
            <span style="font-size:13px;color:#666;">共 {len(fb_items)} 条</span>
            <input id="planInput" placeholder="快速添加..." style="flex:1;padding:6px 10px;border:1px solid #f0c0d0;border-radius:8px;font-size:12px;outline:none;"
                   onkeypress="if(event.key==='Enter')addPlan()">
            <button onclick="addPlan()" class="btn-sm" style="padding:6px 12px;background:#ff6b8a;color:white;border:none;border-radius:8px;font-size:12px;cursor:pointer;">+</button>
        </div>
        <table><tr><th>类型</th><th>标题</th><th>分类/优先级</th><th>日期</th><th>操作</th></tr>{fb_html}</table>""",

        "logs": f"""<div class="stats">
            <div class="stat"><div class="num">{s['today']['total']}</div><div class="label">今日消息</div></div>
            <div class="stat"><div class="num">{s['today']['errors']}</div><div class="label">今日错误</div></div>
            <div class="stat"><div class="num">{s['total']}</div><div class="label">总日志</div></div>
            <div class="stat"><div class="num">{len(mem_items)}</div><div class="label">活跃记忆</div></div>
            <div class="stat"><div class="num">{len(fb_items)}</div><div class="label">待改进</div></div>
        </div>
        <table><tr><th>类型</th><th>来源</th><th>内容</th><th>时间</th></tr>{logs_html}</table>""",
    }.get(tab, overview)

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SundayOS 控制台</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, 'PingFang SC', sans-serif; background: #fef9f4; color: #333; padding: 20px; }}
.header {{ background: linear-gradient(135deg, #ff6b8a, #ff8fab); color: white; padding: 20px; border-radius: 16px; margin-bottom: 20px; }}
.header h1 {{ font-size: 24px; }}
.header p {{ opacity: 0.9; margin-top: 4px; font-size: 14px; }}
.tabs {{ display: flex; gap: 4px; margin-bottom: 20px; }}
.tab {{ flex: 1; padding: 10px; text-align: center; border-radius: 10px; background: white; color: #666; text-decoration: none; font-size: 13px; box-shadow: 0 1px 4px rgba(0,0,0,0.05); }}
.tab.active {{ background: #ff6b8a; color: white; }}
.tab:hover {{ background: #fff0f3; }}
.tab.active:hover {{ background: #ff6b8a; }}
.stats {{ display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }}
.stat {{ background: white; border-radius: 12px; padding: 16px; flex: 1; min-width: 80px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
.stat .num {{ font-size: 28px; font-weight: bold; color: #ff6b8a; }}
.stat .label {{ font-size: 11px; color: #999; margin-top: 4px; }}
table {{ width: 100%; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
.imp-critical {{ color: #e53e3e; font-weight: bold; }}
.imp-high {{ color: #ed8936; font-weight: bold; }}
.imp-medium {{ color: #718096; }}
.imp-low {{ color: #a0aec0; }}
.imp-trivial {{ color: #cbd5e0; }}
th {{ background: #fff0f3; padding: 12px 16px; text-align: left; font-size: 13px; color: #666; }}
td {{ padding: 10px 16px; font-size: 13px; border-bottom: 1px solid #f5f5f5; }}
tr.error {{ background: #fff5f5; }}
tr:hover {{ background: #fff8fa; }}
.refresh {{ font-size: 12px; color: #999; text-align: center; margin-top: 16px; }}
.btn-sm {{ padding:4px 8px;border-radius:6px;border:none;cursor:pointer;font-size:14px;line-height:1; }}
.btn-done {{ background:#e8f5e9; }} .btn-done:hover {{ background:#c8e6c9; }}
.btn-del {{ background:#fce4ec; }} .btn-del:hover {{ background:#f8bbd0; }}
.btn-arch {{ background:#e3f2fd; }} .btn-arch:hover {{ background:#bbdefb; }}
.badge {{ display:inline-block;background:#f0e6ff;color:#7c5cbf;padding:1px 8px;border-radius:10px;font-size:10px; }}
.pri {{ display:inline-block;padding:1px 6px;border-radius:8px;font-size:10px; }}
.pri-high {{ background:#fce4ec;color:#c62828; }}
.pri-medium {{ background:#fff3e0;color:#e65100; }}
.pri-low {{ background:#e8f5e9;color:#2e7d32; }}
.toast {{ position:fixed;bottom:20px;right:20px;background:#333;color:white;padding:10px 20px;border-radius:10px;font-size:13px;opacity:0;transition:opacity 0.3s;z-index:999; }}
.toast.show {{ opacity:1; }}
.card-grid {{ display:flex;gap:14px;margin-bottom:14px;flex-wrap:wrap; }}
.card {{ flex:1;min-width:280px;background:white;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,0.04);overflow:hidden; }}
.card-title {{ padding:14px 18px 0;font-size:14px;font-weight:700;color:#5a3a4a; }}
.card-body {{ padding:14px 18px;font-size:13px;color:#4a3a3a;line-height:1.8;max-height:300px;overflow-y:auto; }}

/* 移动端适配 */
@media (max-width: 640px) {{
  body {{ padding: 10px; }}
  .header {{ padding: 16px; border-radius: 12px; }}
  .header h1 {{ font-size: 20px; }}
  .tabs {{ gap: 2px; }}
  .tab {{ padding: 8px 6px; font-size: 11px; }}
  .stats {{ gap: 8px; }}
  .stat {{ padding: 12px 8px; min-width: 60px; }}
  .stat .num {{ font-size: 22px; }}
  .card-grid {{ flex-direction: column; }}
  .card {{ min-width: 100%; }}
  table {{ display: block; overflow-x: auto; }}
  th, td {{ padding: 8px 10px; font-size: 11px; }}
  td {{ white-space: normal; word-break: break-word; }}
  .btn-sm {{ padding: 3px 6px; font-size: 12px; }}
}}
</style>
</head>
<body>
<div id="toast" class="toast"></div>
<div class="header">
    <h1>💕 SundayOS 控制台</h1>
    <p>总览 · 记忆 · 计划 · 日志 | v3.2</p>
</div>
{tabs_html}
{content}
<p class="refresh">刷新页面查看最新数据</p>
</body>
<script>
const API = '/api';
const KEY = '{key}';
const UID = 'daily';

function toast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2000);
}}

async function api(path, method, body) {{
  const r = await fetch(API + path, {{
    method, headers: {{ 'Content-Type':'application/json','X-API-Key':KEY }},
    body: body ? JSON.stringify(body) : undefined
  }});
  return r.ok ? r.json() : null;
}}

// ── 改进计划操作 ──
async function donePlan(id) {{
  if (!confirm('标记为已完成？')) return;
  const r = await api('/memory/feedback/'+id+'/done', 'POST', {{}});
  if (r) {{ toast('✅ 已标记完成'); document.getElementById('fb-'+id.slice(-8)).remove(); }}
  else toast('❌ 操作失败');
}}
async function delPlan(id) {{
  if (!confirm('确认删除？')) return;
  const r = await api('/memory/feedback/'+id+'/delete', 'POST', {{}});
  if (r) {{ toast('🗑️ 已删除'); document.getElementById('fb-'+id.slice(-8)).remove(); }}
  else toast('❌ 操作失败');
}}
async function addPlan() {{
  const inp = document.getElementById('planInput');
  const title = inp.value.trim();
  if (!title) return;
  const r = await api('/feedback/add', 'POST', {{ user_id:UID, title, fb_type:'enhancement' }});
  if (r) {{ toast('✅ 已添加'); setTimeout(() => location.reload(), 500); }}
  else toast('❌ 添加失败');
  inp.value = '';
}}

// ── 记忆操作 ──
async function archiveMem(id) {{
  const r = await api('/memory/'+id+'/archive', 'POST', {{}});
  if (r) {{ toast('📦 已归档'); setTimeout(() => location.reload(), 500); }}
  else toast('❌ 操作失败');
}}
async function addMem() {{
  const inp = document.getElementById('memInput');
  const summary = inp.value.trim();
  if (!summary) return;
  const r = await api('/memory', 'POST', {{ user_id:UID, summary, category:'note', importance:'medium' }});
  if (r) {{ toast('✅ 已添加'); setTimeout(() => location.reload(), 500); }}
  else toast('❌ 添加失败');
  inp.value = '';
}}
async function delMem(id) {{
  if (!confirm('确认删除这条记忆？')) return;
  const r = await api('/memory/'+id, 'DELETE');
  if (r) {{ toast('🗑️ 已删除'); document.getElementById('mem-'+id.slice(-8)).remove(); }}
  else toast('❌ 操作失败');
}}
</script>
</html>"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


# ============================================================
# API 路由 — 运行日志
# ============================================================
@app.get("/api/logs")
async def get_logs(
    request: Request,
    log_type: str = Query("", description="日志类型: chat, reply, error, memory, push"),
    user_id: str = Query("", description="用户ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """查询 Sunday 运行日志"""
    await verify_key(request)
    logs = log_query(log_type=log_type, user_id=user_id, limit=limit, offset=offset)
    return {"count": len(logs), "logs": logs}


@app.get("/api/logs/stats")
async def get_log_stats(user_id: str = Query(""), request: Request = None):
    """获取日志统计"""
    await verify_key(request)
    return log_stats(user_id=user_id)


@app.get("/api/feedback")
async def get_feedback(
    request: Request,
    user_id: str = Query("daily"),
    status: str = Query("open"),
    limit: int = Query(50),
):
    """获取改进计划列表"""
    await verify_key(request)
    items = memory_store.get_feedback(user_id, status=status, limit=limit)
    return {"count": len(items), "items": items}


@app.post("/api/feedback/add")
async def add_feedback_api(request: Request):
    """添加改进计划"""
    await verify_key(request)
    body = await request.json()
    user_id = body.get("user_id", "daily")
    title = body.get("title", "")
    fb_type = body.get("fb_type", "improvement")
    detail = body.get("detail", "")
    ai_category = body.get("ai_category", "")
    priority = body.get("priority", "medium")

    if not title:
        raise HTTPException(400, "title 不能为空呢~")

    fb_id = memory_store.add_feedback(user_id, fb_type, title, detail,
                                       ai_category=ai_category, priority=priority)
    return {"status": "added", "fb_id": fb_id}


@app.post("/api/memory/feedback/{fb_id}/done")
async def done_feedback(fb_id: str, request: Request):
    """标记改进计划为已完成"""
    await verify_key(request)
    memory_store.update_feedback(fb_id, status="done")
    return {"status": "done"}


@app.post("/api/memory/feedback/{fb_id}/delete")
async def delete_feedback(fb_id: str, request: Request):
    """删除改进计划"""
    await verify_key(request)
    # 直接标记为 deleted 状态
    memory_store.update_feedback(fb_id, status="deleted")
    return {"status": "deleted"}
# force rebuild Thu Jul  9 02:08:18 AM CST 2026

# deploy 1783536301
# force deploy Thu Jul  9 04:15:13 AM CST 2026
