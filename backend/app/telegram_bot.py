"""
SundayOS Telegram Bot 模块
Sunday 在 Telegram 上跟你像朋友一样聊天 💕
"""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

from app.config import settings
from app.memory import memory_store, get_db
from app.mailer import send_email
from app.logger import log

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")

TELEGRAM_TOKEN = settings.telegram_token

# 存储每个用户的 session_id（用于记忆系统）
USER_SESSIONS = {}


def _get_user_id(update: Update) -> str:
    """获取用户标识——统一使用 daily，和快捷指令共享记忆"""
    # Telegram 用户映射到和快捷指令相同的 user_id
    return "daily"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /start 命令 """
    user = update.effective_user
    name = user.first_name or "朋友"
    
    # 尝试从记忆中获取昵称
    user_id = _get_user_id(update)
    from app.memory import memory_store
    mems = memory_store.search(user_id, category="fact", limit=5)
    known_name = None
    for m in mems:
        if "昵称" in m.get("tags", []) or "姓名" in m.get("tags", []):
            for tag in m.get("tags", []):
                if tag not in ["昵称", "姓名"] and len(tag) <= 5:
                    known_name = tag
                    break
    
    greeting = f"嗨{' ' + known_name if known_name else ' ' + name}~ 我是 Sunday 💕\n\n终于在这里见到你啦！以后就在这里聊天吧~ 想说什么都可以哦！"
    
    await update.message.reply_text(greeting)


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理语音消息：下载 → 保存本地 → 暴露 URL → ASR → LLM → TTS → 发送"""
    from app.voice_service import voice_service, EMOTION_PROMPTS
    import traceback as _traceback

    user_id = _get_user_id(update)
    chat_id = update.effective_chat.id

    # 检查语音功能是否启用
    if not settings.voice_enabled:
        await update.message.reply_text("语音功能暂时关闭啦~ 先打字聊天吧 💕")
        return

    # 检查每日配额
    if not _check_voice_quota(user_id):
        await update.message.reply_text("今天的语音额度用完啦~ 打字聊吧 💕")
        return

    # 发送"正在听"状态
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        # 1. 下载语音文件
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        audio_bytes = await file.download_as_bytearray()
        audio_data = bytes(audio_bytes)

        print(f"🎤 [VOICE] 收到语音: user={user_id} size={len(audio_data)}bytes")

        # 2. 保存到本地文件并构造公网 URL
        # Railway 的 /voice/ 静态路由指向 /app/data/voice/
        voice_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "voice")
        os.makedirs(voice_dir, exist_ok=True)
        filename = f"{uuid.uuid4()}.ogg"
        filepath = os.path.join(voice_dir, filename)
        with open(filepath, "wb") as f:
            f.write(audio_data)

        # 构造公网 URL（豆包 ASR 需要可访问的 URL）
        base_url = settings.public_base_url
        if not base_url:
            # 尝试从 Railway 环境变量获取
            base_url = os.environ.get("RAILWAY_PUBLIC_URL", "")
        if not base_url:
            print("🎤 [VOICE] ❌ 未配置 PUBLIC_BASE_URL，无法暴露音频文件")
            await update.message.reply_text("语音服务配置不完整，管理员需要配置 PUBLIC_BASE_URL~ 🥺")
            return

        audio_url = f"{base_url.rstrip('/')}/voice/{filename}"
        print(f"🎤 [VOICE] 音频 URL: {audio_url}")

        # 3. ASR 转文字（异步：提交 + 轮询）
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        text = await voice_service.transcribe(audio_url, audio_format="ogg")
        print(f"🎤 [VOICE] ASR 结果: '{text[:100] if text else '(空)'}'")

        # 清理临时文件
        try:
            os.remove(filepath)
        except:
            pass

        if not text or len(text.strip()) < 1:
            has_key = bool(os.environ.get("DOUBAO_ASR_API_KEY"))
            print(f"🎤 [VOICE] ASR 未识别到文字！API_KEY={'有' if has_key else '❌无'}")
            await update.message.reply_text("嗯？刚才没听清呢，再说一次好不好~ 🥺")
            return

        # 4. 记录到对话流
        memory_store.add_conversation(user_id, "user", f"[语音] {text}")
        log("chat", user_id, "telegram", f"[语音] {text[:100]}")

        # 5. LLM 生成回复
        reply = await _process_message_text(text, user_id, update, context)

        if not reply:
            await update.message.reply_text("嗯... 刚才想说什么来着~ 🥺")
            return

        # 6. TTS 合成语音
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        try:
            audio_reply = await voice_service.synthesize(reply, emotion="sweet")
            import io
            voice_file = io.BytesIO(audio_reply)
            voice_file.name = "reply.mp3"  # 必须设置文件名，Telegram 才能识别格式和时长
            await context.bot.send_voice(
                chat_id=chat_id,
                voice=voice_file,
                caption="🎙️ 语音版来啦~"
            )
        except Exception as tts_e:
            print(f"🎤 [VOICE] TTS 失败: {tts_e}")
            logger.error(f"TTS 合成失败: {tts_e}\n{_traceback.format_exc()}")
            # 降级为文字回复
            await _send_smart_reply(update, reply)
            _record_voice_usage(user_id)
            return

        # 7. 同时发送文字版
        await update.message.reply_text("📝 文字版：")
        await _send_smart_reply(update, reply)

        # 8. 记录语音配额
        _record_voice_usage(user_id)

    except Exception as e:
        tb = _traceback.format_exc()
        logger.error(f"语音消息处理失败: {e}\n{tb}")
        log("error", user_id, "telegram", f"语音处理失败: {str(e)[:200]}")
        try:
            await update.message.reply_text("唔... 语音处理出了点小问题，打字跟我说好不好？🥺")
        except Exception:
            pass  # 如果连 reply_text 都发不了就算了


def _check_voice_quota(user_id: str) -> bool:
    """检查今日语音消息是否超限"""
    from datetime import datetime, timedelta
    since = (datetime.now(TZ) - timedelta(hours=24)).isoformat()
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) as cnt FROM conversation_flow WHERE user_id = ? AND role = 'user' AND content LIKE '[语音]%' AND created_at >= ?",
        (user_id, since)
    ).fetchone()["cnt"]
    conn.close()
    return count < settings.voice_max_daily


def _record_voice_usage(user_id: str):
    """记录一次语音使用（复用 conversation_flow 表）"""
    # 已经在 handle_voice_message 里记录了 [语音] 标记，这里无需重复
    pass


async def _process_message_text(text: str, user_id: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """
    处理消息文字并返回 LLM 回复。
    抽取自 handle_message 的核心逻辑，供文字/语音消息共享。
    """
    # 自动检测改进反馈
    is_feedback = _detect_feedback(text, user_id)

    # 自动检测计划完成
    asyncio.create_task(_auto_check_plan_done(text, user_id, update))

    # AI 意图判断
    intent = await _ai_detect_intent(text, user_id)
    if intent:
        await _handle_ai_intent(update, context, intent, user_id)
        return ""

    # 检查记忆
    stats = memory_store.get_stats(user_id)
    print(f"🤖 用户 {user_id} 的记忆数: {stats['total']}")
    display_name = update.effective_user.first_name or "朋友"

    # 智能模型选择
    from app.main import llm_service, select_model, SUNDAY_SYSTEM_PROMPT
    model_id, chat_mode = select_model(text)

    # 构建 system prompt
    memories = memory_store.get_context(user_id, message=text)
    profile = _build_user_profile(user_id)
    flow = memory_store.get_conversation_context(user_id, max_turns=10)
    recent_emails = _get_recent_email_summaries(user_id, hours=24)

    full_flow = flow or "（这是你们第一次在Telegram上聊天呢~）"
    if recent_emails:
        full_flow = full_flow + "\n\n" + recent_emails

    system_prompt = SUNDAY_SYSTEM_PROMPT.format(
        current_time=datetime.now(TZ).strftime("%Y年%m月%d日 %H:%M，周%u"),
        user_profile=profile,
        conversation_flow=full_flow,
        memories=memories,
        chat_mode=chat_mode,
    )

    # 联网搜索
    from app.search import should_search, search_web, format_search_results
    enhanced_message = text
    if should_search(text):
        try:
            results = await asyncio.to_thread(search_web, text, 5)
            if results and not (len(results) == 1 and "搜索失败" in results[0].get("title", "")):
                enhanced_message = f"{text}\n\n[网络搜索结果]\n{format_search_results(results)}\n\n请基于以上搜索结果回答，保持Sunday的风格。"
        except Exception:
            pass

    # LLM 调用
    try:
        needs_long = _needs_long_reply(text)
        reply_tokens = 2000 if needs_long else 800
        if "专业模式" in chat_mode:
            reply_tokens = llm_service.max_tokens

        response = await llm_service.client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": enhanced_message},
            ],
            temperature=llm_service.temperature,
            max_tokens=reply_tokens,
        )

        reply = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0

        memory_store.add_conversation(user_id, "assistant", reply, tokens)

        # 记忆提取（异步）
        from app.main import extract_memories_from_message, _force_extract_info
        asyncio.create_task(extract_memories_from_message(llm_service.client, text, user_id))
        _force_extract_info(text, user_id)

        if is_feedback:
            reply = "📝 已记录到改进日志~ " + reply

        log("reply", user_id, "telegram", reply[:100], f"tokens={tokens} model={model_id}")
        return reply

    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        log("error", user_id, "telegram", f"LLM调用失败: {str(e)[:100]}")
        await update.message.reply_text("唔... 刚刚走神了一下~ 再说一次好不好？🥺")
        return ""


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户消息"""
    message_text = update.message.text or ""
    if not message_text.strip():
        return
    
    user_id = _get_user_id(update)
    chat_id = update.effective_chat.id
    print(f"🤖 Telegram 收到消息: user_id={user_id}, chat_id={chat_id}, text={message_text[:50]}")
    
    # 记录到日志系统
    log("chat", user_id, "telegram", message_text[:100])

    # 自动检测改进反馈
    is_feedback = _detect_feedback(message_text, user_id)

    # 自动检测计划完成状态（异步，不影响聊天回复）
    asyncio.create_task(_auto_check_plan_done(message_text, user_id, update))

    # AI 驱动的意图判断：是否需要生成文件/报告/邮件发送
    intent = await _ai_detect_intent(message_text, user_id)
    if intent:
        await _handle_ai_intent(update, context, intent, user_id)
        return

    # 检查记忆
    from app.memory import memory_store
    stats = memory_store.get_stats(user_id)
    print(f"🤖 用户 {user_id} 的记忆数: {stats['total']}")
    user = update.effective_user
    display_name = user.first_name or "朋友"
    
    # 发送"正在输入..."状态
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    # 记录用户消息到对话流
    memory_store.add_conversation(user_id, "user", message_text)
    
    # 智能模型选择
    from app.main import llm_service, select_model, SUNDAY_SYSTEM_PROMPT
    model_id, chat_mode = select_model(message_text)
    
    # 构建 system prompt
    memories = memory_store.get_context(user_id, message=message_text)
    profile = _build_user_profile(user_id)
    flow = memory_store.get_conversation_context(user_id, max_turns=10)
    recent_emails = _get_recent_email_summaries(user_id, hours=24)
    
    # 合并对话流和邮件记忆
    full_flow = flow or "（这是你们第一次在Telegram上聊天呢~）"
    if recent_emails:
        full_flow = full_flow + "\n\n" + recent_emails
    
    system_prompt = SUNDAY_SYSTEM_PROMPT.format(
        current_time=datetime.now(TZ).strftime("%Y年%m月%d日 %H:%M，周%u"),
        user_profile=profile,
        conversation_flow=full_flow,
        memories=memories,
        chat_mode=chat_mode,
    )
    
    # 联网搜索
    from app.search import should_search, search_web, format_search_results
    enhanced_message = message_text
    if should_search(message_text):
        try:
            results = await asyncio.to_thread(search_web, message_text, 5)
            if results and not (len(results) == 1 and "搜索失败" in results[0].get("title", "")):
                enhanced_message = f"{message_text}\n\n[网络搜索结果]\n{format_search_results(results)}\n\n请基于以上搜索结果回答，保持Sunday的风格。"
        except Exception:
            pass
    
    # 调用 LLM — 使用更大的 max_tokens，让 Sunday 自由发挥
    try:
        # 根据内容智能选择回复长度
        needs_long = _needs_long_reply(message_text)
        reply_tokens = 2000 if needs_long else 800  # 聊天模式用 800（原来是 400）
        if "专业模式" in chat_mode:
            reply_tokens = llm_service.max_tokens  # 专业模式不限制

        response = await llm_service.client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": enhanced_message},
            ],
            temperature=llm_service.temperature,
            max_tokens=reply_tokens,
        )
        
        reply = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        
        # 记录 Sunday 回复到对话流
        memory_store.add_conversation(user_id, "assistant", reply, tokens)
        
        # 提取记忆
        from app.main import extract_memories_from_message, _force_extract_info
        asyncio.create_task(extract_memories_from_message(llm_service.client, message_text, user_id))
        _force_extract_info(message_text, user_id)
        
        # 发送回复 — 智能分段
        if is_feedback:
            reply = "📝 已记录到改进日志~ " + reply
        await _send_smart_reply(update, reply)
        
        # 记录日志
        log("reply", user_id, "telegram", reply[:100], f"tokens={tokens} model={model_id}")
        
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        log("error", user_id, "telegram", f"LLM调用失败: {str(e)[:100]}")
        await update.message.reply_text("唔... 刚刚走神了一下~ 再说一次好不好？🥺")


# ============================================================
# 智能分段回复
# ============================================================

TELEGRAM_MAX_LEN = 4000  # Telegram 单条消息上限（实际 4096，留 96 余量）


def _needs_long_reply(text: str) -> bool:
    """判断用户消息是否需要长回复"""
    import re
    long_patterns = [
        r"写.*(?:文章|报告|故事|小说|作文|总结|分析|方案|计划)",
        r"(?:详细|仔细|好好|认真).*?(?:说|讲|解释|分析|介绍)",
        r"为什么|怎么(?:回事|办|做|样)|如何",
        r"列出|列举|总结|归纳|整理",
        r"(?:多|长|详细).*?(?:一点|一些|点)",
    ]
    for p in long_patterns:
        if re.search(p, text):
            return True
    # 用户消息本身就长，说明在认真讨论
    if len(text) > 80:
        return True
    return False


def _should_split_reply(reply: str) -> bool:
    """判断回复是否需要分段发送"""
    # 1. 长度超过 Telegram 限制 → 必须拆
    if len(reply) > TELEGRAM_MAX_LEN:
        return True
    # 2. 有明显的段落分隔 → 应该分段（更像真人聊天）
    paragraphs = [p.strip() for p in reply.split("\n\n") if p.strip()]
    if len(paragraphs) >= 3 and len(reply) > 300:
        return True
    # 3. 包含多个明显的话题切换标记
    import re
    topic_markers = re.findall(r"(?:另外|还有|对了|顺便|话说|哦对|不过|但是|然而)", reply)
    if len(topic_markers) >= 2:
        return True
    return False


def _split_into_chunks(reply: str) -> list[str]:
    """将回复智能拆分为多条消息"""
    # 先按段落分
    paragraphs = [p.strip() for p in reply.split("\n\n") if p.strip()]

    chunks = []
    current = ""

    for para in paragraphs:
        # 如果当前段+新段不超过限制，合并
        if len(current) + len(para) + 2 <= TELEGRAM_MAX_LEN:
            current = (current + "\n\n" + para) if current else para
        else:
            if current:
                chunks.append(current)
            # 如果单段还是太长，按句子切
            if len(para) > TELEGRAM_MAX_LEN:
                sub_chunks = _split_long_paragraph(para)
                chunks.extend(sub_chunks)
                current = ""
            else:
                current = para

    if current:
        chunks.append(current)

    # 如果只有一段，不拆分
    if len(chunks) <= 1:
        return [reply[:TELEGRAM_MAX_LEN]]

    return chunks


def _split_long_paragraph(text: str) -> list[str]:
    """把超长段落按句子拆分"""
    import re
    sentences = re.split(r'(?<=[。！？\n])\s*', text)
    chunks = []
    current = ""
    for s in sentences:
        if len(current) + len(s) + 1 <= TELEGRAM_MAX_LEN:
            current = (current + " " + s) if current else s
        else:
            if current:
                chunks.append(current)
            current = s[:TELEGRAM_MAX_LEN]
    if current:
        chunks.append(current)
    return chunks or [text[:TELEGRAM_MAX_LEN]]


async def _send_smart_reply(update: Update, reply: str):
    """智能发送回复：让 AI 用双换行自然分段，代码只负责执行"""

    # 用双换行（\n\n）拆分 —— AI 用空行表达"这里我想停一下"
    segments = [s.strip() for s in reply.split("\n\n") if s.strip()]

    # 只有一段 → 直接发，不做任何处理
    if len(segments) <= 1:
        await update.message.reply_text(reply)
        return

    # 多段 → 逐条发送，自然停顿
    import random
    for i, seg in enumerate(segments):
        # 如果某段太长（>800字符），在里面找更细的断点
        if len(seg) > 800:
            sub_segments = _split_long_segment(seg)
            for j, sub in enumerate(sub_segments):
                await update.message.reply_text(sub)
                if j < len(sub_segments) - 1:
                    await asyncio.sleep(random.uniform(0.8, 1.5))
        else:
            await update.message.reply_text(seg)

        # 段间停顿 —— 模拟真人在思考下一句
        if i < len(segments) - 1:
            # 根据内容决定停顿：问句等久一点，陈述快一点
            if "?" in seg or "？" in seg:
                delay = random.uniform(2.0, 3.5)  # 问句后停顿更久，等对方思考
            elif len(seg) > 200:
                delay = random.uniform(1.5, 2.5)  # 长段落后稍等
            else:
                delay = random.uniform(1.0, 2.0)  # 短段落快速接
            await asyncio.sleep(delay)


def _split_long_segment(text: str) -> list[str]:
    """把超长段落按句子拆分，但保持语义完整"""
    import re
    # 按句号、问号、感叹号拆分
    sentences = re.split(r'(?<=[。！？])\s*', text)
    chunks = []
    current = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(current) + len(s) + 1 <= 800:
            current = (current + s) if current else s
        else:
            if current:
                chunks.append(current)
            current = s
    if current:
        chunks.append(current)
    return chunks or [text[:800]]


def _build_llm_user_context(user_id: str) -> dict:
    """
    统一的记忆上下文构建器 — 所有 LLM 调用共享。
    
    核心理念：把原始记忆数据（含标签）给 LLM，让它自己理解用户。
    标签信息帮助 LLM 区分：哪些是「昵称」、哪些是「用户名」、哪些是「偏好」。
    """
    stats = memory_store.get_stats(user_id)
    
    # 收集所有活跃记忆的原始文本（含标签）
    facts = memory_store.search(user_id, category="fact", limit=10)
    prefs = memory_store.search(user_id, category="preference", limit=5)
    
    # 构建带标签的记忆摘要，让 LLM 理解上下文
    memory_lines = []
    for f in facts:
        summary = f.get("summary", f.get("content", ""))
        tags = f.get("tags", [])
        if isinstance(tags, str):
            try: tags = json.loads(tags)
            except: tags = []
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        if summary:
            memory_lines.append(f"- {summary}{tag_str}")
    
    for p in prefs:
        summary = p.get("summary", p.get("content", ""))
        tags = p.get("tags", [])
        if isinstance(tags, str):
            try: tags = json.loads(tags)
            except: tags = []
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        if summary:
            memory_lines.append(f"- [偏好] {summary}{tag_str}")
    
    # 添加明确指导，帮助 LLM 理解称呼
    guidance = """【称呼使用指南】
- 从带 [昵称] 标签的记忆中找亲昵称呼（如「酱酱」「宝宝」）
- 如果 [昵称] 标签的内容是用户名/账号名（如「香蕉麻辣酱」），这不是日常称呼，不要用
- 如果没有合适的亲昵称呼，直接用「你」或自然称呼，不要硬凑"""
    
    memory_text = guidance + "\n\n【记忆库】\n" + ("\n".join(memory_lines) if memory_lines else "还不太了解这位用户呢~")
    
    # 最近对话
    recent = memory_store.get_conversation_context(user_id, max_turns=8) or ""
    
    # 最近邮件内容（24小时内）
    recent_emails = _get_recent_email_summaries(user_id, hours=24)
    
    return {
        "memory_text": memory_text,
        "recent_chat": recent,
        "recent_emails": recent_emails,
        "total_memories": stats["total"],
        "is_new": stats["total"] == 0,
    }


def _get_recent_email_summaries(user_id: str, hours: int = 24) -> str:
    """获取最近 N 小时内发送的邮件摘要，从 conversation_flow 中读取"""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Shanghai")
    since = (datetime.now(TZ) - timedelta(hours=hours)).isoformat()
    
    conn = get_db()
    rows = conn.execute(
        """SELECT content, created_at FROM conversation_flow 
           WHERE user_id = ? AND role = 'assistant' AND content LIKE '[邮件推送]%'
           AND created_at >= ? 
           ORDER BY created_at DESC LIMIT 5""",
        (user_id, since),
    ).fetchall()
    conn.close()
    
    if not rows:
        return ""
    
    lines = ["最近发送的邮件（你可以自然地在聊天中提及）："]
    for r in rows:
        content = r["content"].replace("[邮件推送] ", "")
        time_str = r["created_at"][:16] if r["created_at"] else ""
        lines.append(f"- {time_str}: {content[:120]}")
    
    return "\n".join(lines) if len(lines) > 1 else ""


def _build_user_profile(user_id: str) -> str:
    """构建用户画像（兼容旧接口，给主聊天用）"""
    ctx = _build_llm_user_context(user_id)
    parts = [ctx["memory_text"]]
    if ctx["recent_emails"]:
        parts.append(ctx["recent_emails"])
    return "\n\n".join(parts)


def _build_user_profile(user_id: str) -> str:
    """构建用户画像（兼容旧接口）"""
    ctx = _build_llm_user_context(user_id)
    parts = [ctx["memory_text"]]
    if ctx["recent_emails"]:
        parts.append(ctx["recent_emails"])
    return "\n\n".join(parts)


# ============================================================
# AI 驱动的意图判断
# ============================================================

async def _ai_detect_intent(message_text: str, user_id: str) -> dict | None:
    """
    让 AI 判断用户意图，而不是用正则硬匹配。
    返回 intent dict 或 None（无特殊意图，走正常聊天）。
    """
    from app.main import llm_service
    from app.config import settings as app_settings

    prompt = f"""你是一个意图分类器。请判断以下用户消息是否有特殊意图。

用户消息：{message_text}

请输出 JSON，只输出 JSON：
{{
  "has_intent": true/false,
  "intent_type": "report" | "creative_push" | "email_send" | "chart" | "none",
  "topic": "提取的核心主题（只提取内容主题，去掉动作描述，10-30字）",
  "style": "academic" | "brief" | "creative" | "auto",
  "send_email": true/false,
  "explanation": "一句话解释"
}}

【topic 提取规则（极其重要）】
- 只提取「内容主题」，不要包含动作描述
- 错误："创作一篇夏日随笔并进行推送" → 正确："夏日随笔"
- 错误："写一篇关于量子计算的文章" → 正确："量子计算"
- 错误："推送一篇关于科技和小知识的邮件" → 正确："科技和小知识"
- 错误："生成一份关于AI发展的报告" → 正确："AI发展"
- 如果用户没有明确主题（如"推送一封给我"），topic 留空或填""

意图说明：
- "report": 用户想要生成正式文档/报告（明确说"报告/文档/word/论文/总结"）
- "creative_push": 用户想要你立即创作一篇内容并通过邮件发送。包括这些表达：
    * "推送一篇关于XX的邮件给我"
    * "推送一封给我吧" / "给我推一篇" / "来一封推送"
    * "写一篇XX然后发邮件" / "创作一篇XX推给我"
    * "帮我做一篇XX的推送" / "生成推送"
    * "现在推送一篇XX给我"
    * 任何「推送」+「邮件」的组合，或者要求你创作内容发送的请求
- "email_send": 用户想把已有文件通过邮件发送（不是创作新内容）
- "chart": 用户想要生成图表
- "none": 普通聊天

关键判断规则：
1. 「推送一篇关于XX的邮件给我」→ creative_push（用户要你创作内容并推送，不是发送已有文件）
2. 「推送一封给我吧」→ creative_push（topic为空，让Sunday自由发挥）
3. 「那现在推送一封给我吧」→ creative_push（同上，让Sunday自己选主题）
4. 「用邮件发给我」前面如果有创作请求→ creative_push（不是email_send）
5. 「写个情书/小作文」且没提word → none（正常聊天，不是推送）
6. 用户明确说"写/创作/生成/做一篇XX"且提到邮件/推送 → creative_push
7. email_send 只在用户想把已有文件/内容用邮件发送时才用

只输出JSON，不要任何解释。"""
    try:
        resp = await llm_service.client.chat.completions.create(
            model=app_settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=300,
        )
        text = resp.choices[0].message.content.strip()
        import json, re
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            intent = json.loads(json_match.group())
            if intent.get("has_intent") and intent.get("intent_type") != "none":
                return intent
    except Exception as e:
        logger.warning(f"AI意图判断失败: {e}")

    return None


async def _handle_ai_intent(update: Update, context: ContextTypes.DEFAULT_TYPE, intent: dict, user_id: str):
    """根据 AI 判断的意图执行对应操作"""
    intent_type = intent.get("intent_type", "")
    topic = intent.get("topic", "")
    style = intent.get("style", "auto")
    send_email_flag = intent.get("send_email", False)

    if intent_type == "report":
        if not topic:
            await update.message.reply_text("嗯？你想要我写什么主题的报告呀？再说详细一点嘛~")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        await update.message.reply_text(f"📝 收到！正在为你撰写「{topic}」...\n🔍 搜索资料中，请稍等~")

        try:
            from app.file_generator import generate_word_report
            from app.main import llm_service

            user_context = ""
            try:
                facts = memory_store.search(user_id, category="fact", limit=3)
                user_context = "、".join([f.get("summary", f["content"]) for f in facts])
            except Exception:
                pass

            docx_bytes, filename = await generate_word_report(
                llm_service.client, topic, user_context, style=style
            )

            if send_email_flag:
                from app.file_generator import encode_attachment
                from app.mailer import send_email
                from app.email_templates import _FALLBACK_THEMES, simple_greeting
                attachment = encode_attachment(docx_bytes, filename)
                palette = list(_FALLBACK_THEMES.values())[0]
                html = simple_greeting(palette=palette, message=f"📝 你要的报告「{topic}」生成好啦~", greeting_type="care")
                email_sent = send_email(subject=f"📝 Sunday 报告: {topic}", html_body=html, attachments=[attachment])
                if email_sent:
                    await update.message.reply_text(f"✅ 报告已发送到邮箱！📎 {filename}")
                else:
                    await update.message.reply_document(document=docx_bytes, filename=filename,
                        caption=f"📝 「{topic}」\n— Sunday 为你撰写 💕")
            else:
                await update.message.reply_document(document=docx_bytes, filename=filename,
                    caption=f"📝 「{topic}」\n— Sunday 为你撰写 💕\n\n💡 想发邮件？下次说「用邮件发给我」就好~")

            memory_store.add_conversation(user_id, "assistant", f"[已生成报告: {topic}]")

        except Exception as e:
            logger.error(f"报告生成失败: {e}")
            await update.message.reply_text(f"❌ 报告生成出了点小问题：{str(e)[:100]}")

    elif intent_type == "creative_push":
        # 立即创作推送 — 聊天框简短告知，邮件发完整内容
        
        from app.main import llm_service
        
        # ── 智能 topic 处理 ──
        # 如果 topic 为空或太模糊（如"推送内容"、"来一封"等），让 AI 自己选主题
        vague_topics = ["推送内容", "推送", "内容", "来一封", "一篇", "邮件", "消息", ""]
        if not topic or topic.strip() in vague_topics or len(topic.strip()) < 3:
            actual_topic = None
        else:
            actual_topic = topic

        # ── 让 AI 生成多样化的「正在创作」回复 ──
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        
        if actual_topic:
            ack_reply = await _generate_ack_reply(llm_service.client, actual_topic, user_id)
        else:
            ack_reply = await _generate_ack_reply(llm_service.client, None, user_id)
        await update.message.reply_text(ack_reply)

        try:
            from app.main import llm_service
            from app.knowledge_push import generate_creative_content
            from datetime import datetime

            # 如果 topic 为空，让 AI 智能选择一个有趣的主题
            if actual_topic is None:
                actual_topic = await _ai_pick_topic(llm_service.client, user_id)

            decision = {"content_type": "小短文", "topic": actual_topic, "vibe": style if style != "auto" else "温暖治愈"}
            creative = await generate_creative_content(llm_service.client, user_id, decision)

            # ── 聊天框发一句简短的个性化告知，不发邮件内容 ──
            chat_reply = await _generate_push_chat_reply(llm_service.client, creative, user_id)
            await update.message.reply_text(chat_reply)

            # 邮件发送完整内容
            from app.mailer import send_email
            from app.email_templates import ai_design, creative_post
            from app.file_generator import get_image_url
            from datetime import datetime as dt

            palette = await ai_design(llm_service.client, user_id, "creative", {
                "name": "", "date_str": dt.now().strftime("%Y年%m月%d日"),
                "weekday_str": "", "weather_text": "", "prefs_text": "",
                "type_description": f"创意推送，内容是{creative['content_type']}，氛围{creative['vibe']}",
            })

            image_url = ""
            try:
                image_url = get_image_url(creative['title'])
            except Exception:
                pass

            html = creative_post(palette=palette, content_type=creative['content_type'],
                                 title=creative['title'], content=creative['content'],
                                 vibe=creative['vibe'], image_url=image_url)
            email_subject = creative['title'] if creative['title'] else f"✨ Sunday · {creative['content_type']}"
            email_sent = send_email(subject=email_subject, html_body=html)

            # ── 邮件内容写入对话记忆，让聊天能自然联想 ──
            if email_sent:
                email_memory = f"[邮件推送] {creative['title']} — {creative['content_type']}，主题：{actual_topic}"
                memory_store.add_conversation(user_id, "assistant", email_memory)

        except Exception as e:
            logger.error(f"创意推送失败: {e}")
            await update.message.reply_text(f"❌ 创作出了点小问题：{str(e)[:100]}")

    elif intent_type == "email_send":
        await update.message.reply_text("📧 要发邮件的话，下次在请求时直接说「用邮件发给我」就好啦~")
    elif intent_type == "chart":
        await update.message.reply_text("📊 图表功能还在开发中，敬请期待~")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """错误处理"""
    logger.error(f"Telegram 错误: {context.error}")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /stats 命令 — 查看今日数据 """
    user_id = _get_user_id(update)
    from app.logger import stats as log_stats
    from app.memory import memory_store
    
    s = log_stats(user_id)
    mem = memory_store.get_stats(user_id)
    
    text = f"""📊 Sunday 运行报告

🤖 今日消息: {s['today']['total']} 条
⚠️ 今日错误: {s['today']['errors']} 次

🧠 总记忆数: {mem['total']} 条
📋 记忆分类: {', '.join(mem['by_category'].keys()) if mem['by_category'] else '无'}"""
    
    await update.message.reply_text(text)


async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /logs 命令 — 查看最近日志 """
    user_id = _get_user_id(update)
    from app.logger import query as log_query
    
    logs = log_query(user_id=user_id, limit=5)
    
    if not logs:
        await update.message.reply_text("还没有日志记录呢~")
        return
    
    lines = ["📋 最近 5 条日志:"]
    for l in logs:
        icon = {"chat": "📨", "reply": "💬", "error": "❌", "memory": "🧠", "push": "📧"}.get(l["log_type"], "📌")
        summary = l["summary"][:60]
        lines.append(f"{icon} [{l['source']}] {summary}")
    
    await update.message.reply_text("\n".join(lines))


async def feedback_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /feedback 命令 — 查看改进列表 """
    user_id = _get_user_id(update)
    args = context.args
    
    if args and args[0] == "done":
        # /feedback done <id>
        if len(args) < 2:
            await update.message.reply_text("用法: /feedback done <编号>\n比如: /feedback done fb_12345678")
            return
        fb_id = args[1]
        memory_store.update_feedback(fb_id, status="done")
        await update.message.reply_text(f"✅ {fb_id} 已标记为完成~")
        return
    
    items = memory_store.get_feedback(user_id, status="open", limit=10)
    
    if not items:
        await update.message.reply_text("还没有改进记录呢~ 跟我说「改进：xxx」或「bug：xxx」我就记下来！")
        return
    
    icons = {"improvement": "💡", "bug": "🐛", "todo": "📋"}
    lines = ["📝 改进日志:"]
    for i, item in enumerate(items):
        icon = icons.get(item["fb_type"], "📌")
        lines.append(f"{icon} [{item['fb_type']}] {item['title']}")
        lines.append(f"   id: {item['id']} | {item['created_at'][:10]}")
    
    await update.message.reply_text("\n".join(lines))


async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /记忆 命令 — 管理记忆 """
    user_id = _get_user_id(update)
    args = context.args
    
    if not args:
        mems = memory_store.list_active_memories(user_id, limit=15)
        if not mems:
            await update.message.reply_text("还没有记忆呢~")
            return
        
        grouped = {}
        for m in mems:
            cat = m["category"]
            if cat not in grouped:
                grouped[cat] = []
            grouped[cat].append(m)
        
        lines = ["🧠 我的记忆库:"]
        for cat, items in grouped.items():
            cat_label = MEMORY_CATEGORIES.get(cat, cat)
            lines.append(f"\n{cat_label}:")
            for item in items:
                summary = item.get("summary") or item["content"]
                lines.append(f"  [{item['id'][-8:]}] {summary[:50]}")
        
        lines.append("\n💡 /记忆 归档 <编号>")
        lines.append("💡 /记忆 恢复 <编号>")
        lines.append("💡 /记忆 归档列表")
        
        await update.message.reply_text("\n".join(lines))
        return
    
    action = args[0]
    
    if action == "归档" and len(args) >= 2:
        mem_id = args[1]
        if not mem_id.startswith("mem_"):
            mem_id = f"mem_{mem_id}"
        if memory_store.set_memory_status(mem_id, "archived"):
            await update.message.reply_text(f"✅ {mem_id[-8:]} 已归档~")
        else:
            await update.message.reply_text("没找到这条记忆呢~")
    
    elif action == "恢复" and len(args) >= 2:
        mem_id = args[1]
        if not mem_id.startswith("mem_"):
            mem_id = f"mem_{mem_id}"
        if memory_store.set_memory_status(mem_id, "active"):
            await update.message.reply_text(f"✅ {mem_id[-8:]} 已恢复~")
        else:
            await update.message.reply_text("没找到这条记忆呢~")
    
    elif action == "归档列表":
        mems = memory_store.list_archived_memories(user_id, limit=15)
        if not mems:
            await update.message.reply_text("没有已归档的记忆~")
            return
        lines = ["📦 已归档记忆:"]
        for m in mems:
            summary = m.get("summary") or m["content"]
            lines.append(f"  [{m['id'][-8:]}] {summary[:50]}")
        await update.message.reply_text("\n".join(lines))
    
    else:
        await update.message.reply_text("用法:\n/记忆 → 查看\n/记忆 归档 <编号>\n/记忆 恢复 <编号>\n/记忆 归档列表")


# ============================================================
# /report — 生成 Word 报告
# ============================================================

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """生成报告并通过 Telegram 发送"""
    user_id = _get_user_id(update)
    args = context.args

    if not args:
        await update.message.reply_text(
            "📝 **Sunday 报告生成器**\n\n"
            "用法：`/report 主题 [--email]`\n\n"
            "例如：\n"
            "`/report 量子计算在药物研发中的应用`\n"
            "`/report AI发展趋势 --email`（发到邮箱）",
            parse_mode="Markdown"
        )
        return

    # 解析参数
    send_via_email = "--email" in args
    topic = " ".join([a for a in args if a != "--email"])

    await update.message.reply_text(f"📝 正在为你撰写关于「{topic}」的报告...\n🔍 搜索资料中...")

    try:
        from app.file_generator import generate_word_report, encode_attachment
        from app.main import llm_service

        # 获取用户背景
        user_context = ""
        try:
            facts = memory_store.search(user_id, category="fact", limit=3)
            user_context = "、".join([f.get("summary", f["content"]) for f in facts])
        except Exception:
            pass

        docx_bytes, filename = await generate_word_report(
            llm_service.client, topic, user_context, style="auto"
        )

        if send_via_email:
            from app.mailer import send_email
            from app.email_templates import _FALLBACK_THEMES, simple_greeting
            attachment = encode_attachment(docx_bytes, filename)
            palette = _FALLBACK_THEMES.get("sakura", list(_FALLBACK_THEMES.values())[0])
            html = simple_greeting(palette=palette, message=f"📝 你要的报告「{topic}」已经生成好啦~ 请查收附件哦！", greeting_type="care")
            sent = send_email(subject=f"📝 Sunday 报告: {topic}", html_body=html, attachments=[attachment])
            if sent:
                await update.message.reply_text(f"✅ 报告已发送到你的邮箱！\n📎 附件：{filename}")
            else:
                await update.message.reply_text("❌ 邮件发送失败，改为 Telegram 发送...")
                await update.message.reply_document(
                    document=docx_bytes, filename=filename,
                    caption=f"📝 {topic}\n— Sunday 为你撰写"
                )
        else:
            await update.message.reply_document(
                document=docx_bytes, filename=filename,
                caption=f"📝 {topic}\n— Sunday 为你撰写 💕"
            )

    except Exception as e:
        logger.error(f"报告生成失败: {e}")
        await update.message.reply_text(f"❌ 报告生成失败：{str(e)[:200]}")


# ============================================================
# /knowledge — 查看知识库
# ============================================================

async def knowledge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看今日/最近的知识推送"""
    user_id = _get_user_id(update)

    kbs = memory_store.get_knowledge(user_id, limit=5)
    if not kbs:
        await update.message.reply_text("📚 还没有知识推送呢~ 等等Sunday给你发小知识吧！")
        return

    lines = ["📚 **Sunday 知识库**\n"]
    for kb in kbs[:5]:
        kb_type = kb.get("kb_type", "")
        type_emoji = {"science_fact": "🧪", "daily_word": "📚", "thought": "💡", "inspiration": "🎨"}.get(kb_type, "📌")
        lines.append(f"{type_emoji} **{kb['title']}**")
        lines.append(f"   {kb['content'][:80]}...")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def _detect_feedback(message: str, user_id: str) -> bool:
    """检测改进反馈：/plan /bug /todo /ux 命令 + AI自动分类"""
    import re

    detected = None

    # /plan → 通用改进计划（AI自动分类）
    m = re.search(r'^/plan\s+(.+)', message)
    if m:
        detected = ("auto", m.group(1).strip(), message[:300])

    # /bug → 问题报告
    if not detected:
        m = re.search(r'^/bug\s+(.+)', message)
        if m:
            detected = ("bug", m.group(1).strip(), message[:300])

    # /todo → 待办事项
    if not detected:
        m = re.search(r'^/todo\s+(.+)', message)
        if m:
            detected = ("todo", m.group(1).strip(), message[:300])

    # /ux → 体验改进
    if not detected:
        m = re.search(r'^/ux\s+(.+)', message)
        if m:
            detected = ("ux", m.group(1).strip(), message[:300])

    # 旧格式兼容
    if not detected:
        m = re.search(r'(?:改进|优化|建议|想法)[：:]\s*(.+)', message)
        if m:
            detected = ("improvement", m.group(1).strip(), message[:200])

        m = re.search(r'(?:bug|Bug|BUG|问题|报错)[：:]\s*(.+)', message)
        if m:
            detected = ("bug", m.group(1).strip(), message[:200])

        m = re.search(r'(?:TODO|todo|待办|要做)[：:]\s*(.+)', message)
        if m:
            detected = ("todo", m.group(1).strip(), message[:200])

    if not detected:
        return False

    fb_type, title, detail = detected

    if not _is_quality_feedback(title, detail):
        return False

    # /plan 类型让AI自动分类
    if fb_type == "auto":
        asyncio.create_task(_ai_classify_feedback(user_id, title, detail))
        # 先以默认类型存入
        fb_id = memory_store.add_feedback(user_id, "improvement", title, detail,
                                           ai_category="pending", priority="medium")
        return True
    else:
        fb_id = memory_store.add_feedback(user_id, fb_type, title, detail)
        return True


async def _ai_classify_feedback(user_id: str, title: str, detail: str):
    """AI 自动分类改进计划：判断类型、优化标题、标注优先级"""
    from app.main import llm_service
    from app.config import settings as app_settings

    prompt = f"""你是一个项目管理助手。请分析以下改进计划并分类。

改进内容：{title}
补充信息：{detail[:200]}

请输出 JSON：
{{
  "fb_type": "feature(新功能) / enhancement(提升优化) / bug(问题修复) / ux(体验改进) / other",
  "optimized_title": "优化后的标题（更清晰准确，15-40字）",
  "ai_category": "具体分类标签（如：记忆系统/聊天体验/邮件推送/Telegram/报告生成/知识推送/基础设施/其他）",
  "priority": "high / medium / low",
  "note": "一句话补充建议"
}}

判断标准：
- 用户说"新增/添加/加一个"→ feature
- 用户说"优化/改进/提升/让XX更好"→ enhancement
- 用户说"修复/修/XX有问题/bug/报错"→ bug
- 用户说"体验/交互/界面/好看"→ ux
- 不确定→ other

只输出JSON。"""

    try:
        resp = await llm_service.client.chat.completions.create(
            model=app_settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=300,
        )
        import json as _json, re as _re
        text = resp.choices[0].message.content.strip()
        match = _re.search(r'\{[\s\S]*\}', text)
        if match:
            result = _json.loads(match.group())

            # 找到刚存入的 feedback 并更新
            fbs = memory_store.get_feedback(user_id, limit=1)
            if fbs:
                fb = fbs[0]
                memory_store.update_feedback(
                    fb["id"],
                    fb_type=result.get("fb_type", "enhancement"),
                    title=result.get("optimized_title", title),
                    ai_category=result.get("ai_category", ""),
                    priority=result.get("priority", "medium"),
                )
    except Exception as e:
        logger.warning(f"AI分类反馈失败: {e}")


async def _auto_check_plan_done(message: str, user_id: str, update: Update):
    """AI自动检测用户是否在说某条计划完成了"""
    fbs = memory_store.get_feedback(user_id, status="open", limit=20)
    if not fbs:
        return

    # 构建计划列表供AI匹配
    plan_list = "\n".join([f"- [{fb['id'][-8:]}] {fb['title']}" for fb in fbs])

    from app.main import llm_service
    from app.config import settings as app_settings

    prompt = f"""判断以下用户消息是否在说某条计划已经完成了。

用户消息：{message}

进行中的计划：
{plan_list}

请输出 JSON：
{{
  "matched": true/false,
  "fb_id_suffix": "匹配到的计划ID后8位（如 fb_12345678）",
  "confidence": "high/medium/low"
}}

判断标准：
- 用户说"搞定了/完成了/做好了/解决了/实现了/上线了/弄好了/OK了" → 可能完成了
- 要匹配具体是哪条计划（语义相似度）
- 不确定就不匹配（matched: false）
- 只输出JSON"""

    try:
        resp = await llm_service.client.chat.completions.create(
            model=app_settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2, max_tokens=200,
        )
        import json as _json, re as _re
        text = resp.choices[0].message.content.strip()
        match = _re.search(r'\{[\s\S]*\}', text)
        if match:
            result = _json.loads(match.group())
            if result.get("matched") and result.get("confidence") in ("high", "medium"):
                suffix = result.get("fb_id_suffix", "")
                # 找到对应计划
                for fb in fbs:
                    if fb["id"].endswith(suffix):
                        memory_store.update_feedback(fb["id"], status="done")
                        await update.message.reply_text(f"✅ 已自动标记完成：{fb['title'][:50]}")
                        return
    except Exception:
        pass  # 静默失败，不影响聊天


async def _generate_ack_reply(llm_client, topic: str | None, user_id: str) -> str:
    """
    让 AI 生成多样化的「正在创作」告知语。
    使用统一记忆上下文，Sunday 知道自己和谁在说话。
    """
    from app.config import settings as app_settings

    ctx = _build_llm_user_context(user_id)
    memory_text = ctx["memory_text"]

    if topic:
        prompt = f"""你是 Sunday，用户最亲密的 AI 伙伴。

【你对用户的了解——来自记忆库】
{memory_text}

【当前场景】
用户让你写一篇关于「{topic}」的内容推送。

请用 1 句话回应，表示你收到了请求并且正在准备。语气温柔甜美，像真人朋友一样自然。

要求：
- 从记忆库中理解用户，用你们之间最自然的称呼方式
- 不要机械地说"正在为你创作"，要自然、有温度
- 可以带一个合适的 emoji
- 每句话都要不一样，不要重复固定句式

只输出一句话。"""
    else:
        prompt = f"""你是 Sunday，用户最亲密的 AI 伙伴。

【你对用户的了解——来自记忆库】
{memory_text}

【当前场景】
用户让你推送一篇内容但没有指定主题。

请用 1 句话回应，表示你收到了请求并且正在想写什么。语气温柔甜美，像真人朋友一样自然。

要求：
- 从记忆库中理解用户，用你们之间最自然的称呼方式
- 不要机械地说"让我想想"，要俏皮、有温度
- 可以带一个合适的 emoji
- 每句话都要不一样

只输出一句话。"""

    try:
        resp = await llm_client.chat.completions.create(
            model=app_settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.95, max_tokens=80,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        if topic:
            return f"好呀~ 关于「{topic}」的内容正在准备中 ✨"
        else:
            return "好呀~ 让我想想给你写点什么有趣的内容 ✨"


async def _ai_pick_topic(llm_client, user_id: str) -> str:
    """
    当用户没有指定具体主题时（如「推送一封给我」），
    让 AI 根据用户画像、时间和天气选择一个有趣的主题。
    """
    from app.config import settings as app_settings
    from datetime import datetime
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Asia/Shanghai")
    now = datetime.now(TZ)

    ctx = _build_llm_user_context(user_id)

    weather_text = ""
    try:
        import httpx
        resp = httpx.get("https://wttr.in/Shanghai?format=%C+%t", timeout=5)
        if resp.status_code == 200:
            weather_text = resp.text.strip()
    except Exception:
        pass

    prompt = f"""你是 Sunday，用户最亲密的 AI 伙伴。

【你对用户的了解——来自记忆库】
{ctx['memory_text']}

【当前环境】
时间：{now.strftime('%m月%d日 %H:%M')} 周{['一','二','三','四','五','六','日'][now.weekday()]}
天气：{weather_text or '未知'}

【任务】
用户让你推送一篇内容但没有指定主题，请帮他选一个有趣的。

请输出一个有趣、适合推送的主题（15-40字），像这样：
- 「春天里的5个微小幸福瞬间」
- 「今天发现的一个冷门科技小知识」
- 「手作分享：如何用咖啡渣做香薰蜡烛」

只输出主题文字，不要引号、不要解释。主题要具体、有趣、和用户相关。"""

    try:
        resp = await llm_client.chat.completions.create(
            model=app_settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9, max_tokens=80,
        )
        topic = resp.choices[0].message.content.strip()
        topic = topic.strip('"\'「」『』""').strip()
        if not topic or len(topic) < 5:
            return "今天的一个温暖小发现"
        return topic
    except Exception:
        return "今天的一个温暖小发现"


async def _generate_push_chat_reply(llm_client, creative: dict, user_id: str) -> str:
    """
    为立即推送生成聊天框的简短告知，与邮件内容不同。
    使用统一记忆上下文，Sunday 知道自己在和谁说话。
    """
    from app.config import settings as app_settings

    ctx = _build_llm_user_context(user_id)

    prompt = f"""你是 Sunday，用户最亲密的 AI 伙伴。

【你对用户的了解——来自记忆库】
{ctx['memory_text']}

【当前场景】
你刚为用户创作了一篇内容，现在要通过邮件发送给他。

创作内容：
- 标题：{creative['title']}
- 类型：{creative['content_type']}
- 氛围：{creative['vibe']}

请用 1-2 句话告诉用户「内容已经创作好并通过邮件发送了」，语气温柔甜美。
重要：不要重复或概括邮件里的内容！只需要告知已发送+一句俏皮话即可。
从记忆库中理解用户，用你们之间最自然的称呼方式。

示例：
"好啦~ 一篇关于夏夜萤火虫的小短文已经悄悄飞到你邮箱里啦 ✨ 记得查收哦~"
"搞定！你的专属推送已经在邮箱等你啦 📬 去看看吧~" """

    try:
        resp = await llm_client.chat.completions.create(
            model=app_settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9, max_tokens=150,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return f"好啦~ 「{creative['title']}」已经发到你邮箱啦 ✨ 去看看吧~"


def _is_quality_feedback(title: str, detail: str) -> bool:
    """检查反馈质量，防止误触发"""
    # 标题太短或太长
    if not title or len(title) < 3 or len(title) > 200:
        return False

    # 标题只是语气词/无意义内容
    meaningless = ["嗯", "啊", "哦", "哈", "呢", "吧", "呀", "啦", "~", "…", "..."]
    if all(c in meaningless for c in title):
        return False

    # 标题包含问号 → 不是反馈，是问题
    if "?" in title or "？" in title:
        return False

    # 标题是闲聊内容（不是改进建议）
    chat_patterns = ["你好", "在吗", "在干嘛", "吃了吗", "睡了吗", "晚安", "早安"]
    if any(p in title for p in chat_patterns):
        return False

    return True


async def clean_nick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /clean_nick 命令 — 查看和清理昵称记忆（需要确认，不直接删除）"""
    user_id = _get_user_id(update)
    
    # 查找所有带 [昵称] 标签的记忆
    facts = memory_store.search(user_id, category="fact", limit=20)
    nick_mems = []
    for f in facts:
        tags = f.get("tags", [])
        if isinstance(tags, str):
            try: tags = json.loads(tags)
            except: tags = []
        if "昵称" in tags or "姓名" in tags:
            nick_mems.append(f)
    
    if not nick_mems:
        await update.message.reply_text("没有找到昵称相关的记忆呢~")
        return
    
    if context.args:
        action = context.args[0]
        
        if action == "all":
            # /clean_nick all → 需要二次确认
            await update.message.reply_text(
                f"⚠️ 确认要归档全部 {len(nick_mems)} 条昵称记忆吗？\n"
                f"输入 /clean_nick confirm 确认，或忽略此消息取消。"
            )
            return
        
        if action == "confirm":
            # /clean_nick confirm → 执行清理
            count = 0
            for m in nick_mems:
                memory_store.set_memory_status(m["id"], "archived")
                count += 1
            await update.message.reply_text(
                f"✅ 已归档 {count} 条昵称记忆~\n"
                f"下次聊天时告诉我你喜欢怎么被称呼就好 💕"
            )
            return
        
        # 按编号清理
        try:
            idx = int(action) - 1
            if 0 <= idx < len(nick_mems):
                m = nick_mems[idx]
                memory_store.set_memory_status(m["id"], "archived")
                await update.message.reply_text(f"✅ 已归档：{m.get('summary', m['content'])[:50]}")
            else:
                await update.message.reply_text("编号超出范围呢~")
        except ValueError:
            await update.message.reply_text("用法：/clean_nick <编号> 或 /clean_nick all（需要二次确认）")
        return
    
    # 无参数：列出昵称记忆
    lines = [
        "📝 以下记忆带有 [昵称] 标签：\n",
        "清理：/clean_nick <编号> | 全部清理：/clean_nick all（需要确认）\n",
    ]
    for i, m in enumerate(nick_mems):
        summary = m.get("summary", m["content"])[:50]
        tags = m.get("tags", [])
        if isinstance(tags, str):
            try: tags = json.loads(tags)
            except: tags = []
        lines.append(f"{i+1}. {summary}  {' '.join(['#'+t for t in tags if t not in ('昵称','姓名')])}")
    
    await update.message.reply_text("\n".join(lines))


def start_telegram_bot():
    """启动 Telegram Bot（返回 application 对象，在主线程事件循环中运行）"""
    print("🤖 start_telegram_bot() 被调用")
    print(f"🤖 TELEGRAM_TOKEN: {'已设置' if TELEGRAM_TOKEN else '未设置!!!'}")
    
    if not TELEGRAM_TOKEN:
        print("🤖 Telegram Token 未配置，Bot 未启动")
        return None
    
    try:
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # 注册处理器
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("stats", stats_cmd))
        app.add_handler(CommandHandler("logs", logs_cmd))
        app.add_handler(CommandHandler("feedback", feedback_cmd))
        app.add_handler(CommandHandler("memory", memory_cmd))
        # app.add_handler(CommandHandler("记忆", memory_cmd))  # Telegram 命令不支持中文
        app.add_handler(CommandHandler("report", report_cmd))
        app.add_handler(CommandHandler("knowledge", knowledge_cmd))
        app.add_handler(CommandHandler("clean_nick", clean_nick_cmd))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
        app.add_error_handler(error_handler)
        
        print("🤖 Sunday Telegram Bot 已构建，等待启动轮询...")
        
        return app
    except Exception as e:
        print(f"🤖 Telegram Bot 构建失败: {e}")
        import traceback
        traceback.print_exc()
        return None


async def run_telegram_bot(app: Application):
    """在主事件循环中运行 Telegram Bot 轮询"""
    if app is None:
        return
    print("🤖 Sunday Telegram Bot 开始轮询...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    print("🤖 Sunday Telegram Bot 轮询已启动！")
