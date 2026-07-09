"""
SundayOS Telegram Bot 模块
Sunday 在 Telegram 上跟你像朋友一样聊天 💕
"""
import asyncio
import json
import logging
import os
import uuid
import httpx
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
    
    if known_name:
        name = known_name
    
    welcome = (
        f"嗨 {name}！我是 Sunday 💕\n\n"
        f"我可以帮你：\n"
        f"• 陪你聊天、听你吐槽\n"
        f"• 帮你管理待办和计划\n"
        f"• 发邮件提醒、推送笔记\n"
        f"• 记住你的喜好和习惯\n\n"
        f"直接跟我说话就好啦~"
    )
    await update.message.reply_text(welcome)


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
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
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

        # 5. 用 LLM 判断是否要唱歌 + 提取歌曲名
        # 不再用关键词匹配，让 AI 判断用户意图
        from app.main import llm_service, SUNDAY_SYSTEM_PROMPT

        # 获取最近的对话上下文
        recent_messages = memory_store.get_conversation_context(user_id, max_turns=3) or ""

        # ===== AI 意图判断：一次性决定唱歌/邮件推送/普通聊天 =====
        intent_prompt = f"""你是 Sunday。请判断用户的意图。

用户说：「{text}」

最近对话：
{recent_messages[:500]}

请判断用户的意图，回复一个 JSON：
{{
  "action": "sing/push_email/chat 三选一",
  "reason": "一句话判断理由"
}}

判断规则：
- 明确要求唱歌/唱某首歌/来一首 → "sing"
- 要求推送邮件/发邮件/发周报/发日报/发早安 → "push_email"
- 普通聊天/提问/闲聊 → "chat"

## 如果 action="sing"，额外输出：
{{
  "action": "sing",
  "song_name": "歌曲名",
  "sing_mode": "verse_chorus/chorus_only/full_structure/cover_mode",
  "lyrics": "[verse]\\n歌词...\\n\\n[chorus]\\n歌词...",
  "style": "抒情民谣",
  "bpm": "76 BPM",
  "mood": "温暖治愈",
  "instruments": "钢琴加弦乐"
}}

## 如果 action="push_email"，额外输出：
{{
  "action": "push_email",
  "template": "morning/weekly/fortune/knowledge/creative 选一个",
  "topic": "用户想要的主题描述（如晨间随笔、周报总结）"
}}

只回复 JSON，不要其他文字。"""

        action = "chat"
        # 唱歌相关
        should_sing = False
        song_style = "甜美可爱的女声，轻快J-Pop，动漫主题曲风格"
        specified_song = ""
        sing_mode = "verse_chorus"
        full_lyrics = ""
        style_info = ""
        bpm_info = ""
        mood_info = ""
        instruments_info = ""
        # 邮件相关
        push_template = "morning"
        push_topic = ""

        try:
            intent_resp = await llm_service.client.chat.completions.create(
                model=llm_service.model_fast,
                messages=[{"role": "user", "content": intent_prompt}],
                max_tokens=800,
                temperature=0.3,
            )
            intent_text = intent_resp.choices[0].message.content or ""
            print(f"🤖 [INTENT] AI 意图判断: {intent_text[:300]}")

            intent_info = _extract_json(intent_text)
            if intent_info:
                action = intent_info.get("action", "chat")
                print(f"🤖 [INTENT] action={action} reason={intent_info.get('reason', '')}")

                if action == "sing":
                    should_sing = True
                    specified_song = intent_info.get("song_name", "")
                    sing_mode = intent_info.get("sing_mode", "verse_chorus")
                    full_lyrics = intent_info.get("lyrics", "")
                    style_info = intent_info.get("style", "")
                    bpm_info = intent_info.get("bpm", "")
                    mood_info = intent_info.get("mood", "")
                    instruments_info = intent_info.get("instruments", "")
                elif action == "push_email":
                    push_template = intent_info.get("template", "morning")
                    push_topic = intent_info.get("topic", "")
        except Exception as e:
            print(f"🤖 [INTENT] AI 判断失败: {e}")
            # 降级：简单的关键词兜底
            import re as _re
            if _re.search(r'唱(?:歌|一|首|个)|来一?首|想听.*歌', text):
                action = "sing"
            elif _re.search(r'推送|发邮件|邮件|周报|日报|早报', text):
                action = "push_email"

        # ===== 根据 AI 意图分流 =====
        if action == "sing":
            print(f"🎵 [SING] 用户指定歌曲: {specified_song}, 唱法: {sing_mode}")
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
            try:
                import re as _re
                specified_song = _re.sub(r'^[一首一个首个]+', '', specified_song).strip()
                specified_song = _re.sub(r'[。！？.!?]+$', '', specified_song).strip()

                if specified_song and len(specified_song) >= 2:
                    print(f"🎵 [SING] 一步生成: {specified_song}, lyrics_len={len(full_lyrics)}")
                    await _handle_sing_one_shot(
                        update=update, context=context, chat_id=chat_id,
                        song_name=specified_song, song_style=song_style,
                        sing_mode=sing_mode, full_lyrics=full_lyrics,
                        style_info=style_info, bpm_info=bpm_info,
                        mood_info=mood_info, instruments_info=instruments_info,
                        voice_service=voice_service,
                    )
                else:
                    await _handle_improvise(update, chat_id, song_style, voice_service, llm_service)

                _record_voice_usage(user_id)
                return
            except Exception as music_e:
                import traceback as _tb
                print(f"🎵 [MUSIC] 失败: {music_e}\n{_tb.format_exc()}")
                await update.message.reply_text("唔... 唱歌引擎出了点小问题，下次再唱给你听~ 🥺")
                return

        if action == "push_email":
            print(f"📧 [PUSH] AI判断推送邮件: template={push_template} topic={push_topic}")
            await _handle_email_push(update, context, chat_id, push_template, push_topic)
            return

        # 6. 正常流程：LLM 生成回复
        reply = await _process_message_text(text, user_id, update, context)
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)

        if not reply:
            await update.message.reply_text("嗯... 刚才想说什么来着~ 🥺")
            return

        # 7. TTS 合成语音
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        try:
            audio_reply = await voice_service.synthesize(reply, emotion="sweet")

            import io
            voice_file = io.BytesIO(audio_reply)
            voice_file.name = "reply.mp3"
            await context.bot.send_voice(
                chat_id=chat_id,
                voice=voice_file,
                caption=""
            )
        except Exception as tts_e:
            print(f"🎤 [VOICE] TTS/Music 失败: {tts_e}")
            logger.error(f"TTS/Music 失败: {tts_e}\n{_traceback.format_exc()}")
            # 降级为文字回复
            await _send_smart_reply(update, reply)
            _record_voice_usage(user_id)
            return

        # 7. 记录语音配额
        _record_voice_usage(user_id)

    except Exception as e:
        tb = _traceback.format_exc()
        logger.error(f"语音消息处理失败: {e}\n{tb}")
        log("error", user_id, "telegram", f"语音处理失败: {str(e)[:200]}")
        try:
            await update.message.reply_text("唔... 语音处理出了点小问题，打字跟我说好不好？🥺")
        except Exception:
            pass  # 如果连 reply_text 都发不了就算了


async def _handle_email_push(update, context, chat_id, template_type="morning", topic=""):
    """AI 决定的邮件推送（template 和 topic 由 AI 意图判断提供）"""
    import httpx

    template_labels = {
        "morning": "早安手报 ☀️",
        "weekly": "周报 📊",
        "fortune": "心情签 ✨",
        "knowledge": "知识卡片 📚",
        "creative": "创意推送 🎨",
    }
    label = template_labels.get(template_type, "邮件")
    topic_suffix = f"（{topic}）" if topic else ""

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await update.message.reply_text(f"正在准备{label}{topic_suffix}... 📧")

    try:
        base_url = settings.public_base_url or os.environ.get("RAILWAY_PUBLIC_URL", "")
        if not base_url:
            await update.message.reply_text("邮件服务配置不完整 😢")
            return

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/api/push/send",
                headers={"Authorization": f"Bearer {settings.api_key}"},
                json={
                    "user_id": "daily",
                    "template_type": template_type,
                },
            )
            data = resp.json()
            if data.get("sent"):
                await update.message.reply_text(f"{label}已发送！请查收邮箱~ 📧")
            else:
                await update.message.reply_text("邮件发送出了点问题 😢 稍后再试试？")
    except Exception as e:
        print(f"📧 [PUSH] 发送失败: {e}")
        await update.message.reply_text("邮件服务暂时不可用 😢")


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


async def _handle_sing_one_shot(
    update: Update,
    context,
    chat_id: int,
    song_name: str,
    song_style: str,
    sing_mode: str,
    full_lyrics: str,
    style_info: str,
    bpm_info: str,
    mood_info: str,
    instruments_info: str,
    voice_service,
):
    """
    一步到位唱歌：歌词+风格+BPM+情绪已在第一步全部回忆好，
    这里只做：根据唱法选段落 → music-2.6-free 生成。
    不再调用 LLM！
    """
    import re as _re

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
    status_msg = await update.message.reply_text(f"正在唱《{song_name}》... 🎤")

    # 根据唱法选择段落（纯规则，不调LLM）
    if sing_mode == "chorus_only":
        # 只取 [chorus] 段落
        chorus_match = _re.search(
            r'\[Chorus\]\s*\n?([^\[]+?)(?=\n?\[|$)',
            full_lyrics, _re.IGNORECASE | _re.DOTALL
        )
        if chorus_match:
            selected_lyrics = "[chorus]\n" + chorus_match.group(1).strip()
        else:
            selected_lyrics = full_lyrics
    elif sing_mode == "verse_chorus":
        # 取最后几句verse + chorus
        selected_lyrics = full_lyrics
    elif sing_mode == "full_structure":
        selected_lyrics = full_lyrics
    elif sing_mode == "cover_mode":
        # 翻唱走cover流程
        await _handle_cover_mode(update, context, chat_id, song_name, song_style, voice_service, status_msg)
        return
    else:
        selected_lyrics = full_lyrics

    # 清理
    selected_lyrics = _re.sub(r'[（(].*?[）)]', '', selected_lyrics).strip()
    if not selected_lyrics or len(selected_lyrics) < 20:
        selected_lyrics = f"[verse]\n唱一首关于{song_name}的歌\n回忆里的旋律\n\n[chorus]\n{song_name}\n是我最想唱的歌"

    # 构造 prompt
    prompt_parts = []
    if bpm_info:
        prompt_parts.append(bpm_info)
    if style_info:
        prompt_parts.append(style_info)
    if mood_info:
        prompt_parts.append(mood_info)
    prompt_parts.append("甜美可爱的少女声，Sunday风格")
    if instruments_info:
        prompt_parts.append(instruments_info)
    prompt_parts.append(song_style)
    music_prompt = "，".join(prompt_parts)

    print(f"🎵 [ONE-SHOT] prompt: {music_prompt[:120]}")
    print(f"🎵 [ONE-SHOT] lyrics: {selected_lyrics[:120]}")

    audio_reply = await voice_service.generate_music(
        lyrics=selected_lyrics,
        style=music_prompt,
    )

    print(f"🎵 [ONE-SHOT] 生成完成，发送中...")

    import io
    voice_file = io.BytesIO(audio_reply)
    voice_file.name = "song.mp3"
    try:
        await status_msg.delete()
    except:
        pass
    await context.bot.send_voice(chat_id=chat_id, voice=voice_file, caption="")


async def _handle_improvise(update, chat_id, song_style, voice_service, llm_service):
    """即兴创作模式"""
    await update.message.reply_text("让我即兴创作一首... 🎵")

    lyrics_prompt = """请创作一首简短可爱的歌词（4-8句），用[verse]和[chorus]标记段落，只输出歌词。"""

    try:
        resp = await llm_service.client.chat.completions.create(
            model=llm_service.model_fast,
            messages=[{"role": "user", "content": lyrics_prompt}],
            max_tokens=300,
            temperature=0.9,
        )
        lyrics = resp.choices[0].message.content or f"[chorus]\n啦啦啦\nSunday在唱歌"
    except:
        lyrics = f"[chorus]\n啦啦啦\nSunday在唱歌"

    audio_reply = await voice_service.generate_music(lyrics=lyrics, style=song_style)

    import io
    voice_file = io.BytesIO(audio_reply)
    voice_file.name = "song.mp3"
    await context.bot.send_voice(chat_id=chat_id, voice=voice_file, caption="")


async def _handle_cover_mode(update, context, chat_id, song_name, song_style, voice_service, status_msg):
    """慢速翻唱模式"""
    try:
        await status_msg.edit_text(f"翻唱模式：搜索《{song_name}》的原曲... 🔍")

        search_results = await voice_service.search_song(song_name, limit=5)
        if not search_results:
            await status_msg.edit_text(f"找不到《{song_name}》的原曲 😢")
            return

        song_url = None
        for s in search_results:
            url = await voice_service.get_song_url(s["id"])
            if url:
                song_url = url
                break

        if not song_url:
            await status_msg.edit_text(f"《{song_name}》需要VIP 😢")
            return

        await status_msg.edit_text("分析原曲旋律... 🎶")
        preprocess_result = await voice_service.preprocess_cover(song_url)
        feature_id = preprocess_result["cover_feature_id"]
        lyrics = preprocess_result.get("formatted_lyrics", "")

        chorus = _extract_chorus(lyrics) or lyrics

        await status_msg.edit_text("Sunday风格翻唱中... 🎤")
        audio_reply = await voice_service.generate_cover(
            cover_feature_id=feature_id,
            lyrics=chorus,
            prompt=f"甜美可爱的女声，J-Pop风格，温柔甜美，{song_style}",
        )

        import io
        voice_file = io.BytesIO(audio_reply)
        voice_file.name = "cover.mp3"
        await status_msg.delete()
        await context.bot.send_voice(chat_id=chat_id, voice=voice_file, caption="")

    except Exception as e:
        print(f"🎵 [COVER] 翻唱失败: {e}")
        await status_msg.edit_text("翻唱出了点问题 😢 试试说「唱」而不是「翻唱」吧~")



def _extract_json(text: str) -> dict | None:
    """从 LLM 回复中鲁棒地提取 JSON 对象。
    处理嵌套花括号、多行文本、markdown 代码块等。
    """
    import re as _re

    # 去掉 markdown 代码块
    text = _re.sub(r'```(?:json)?\s*', '', text)
    text = _re.sub(r'```', '', text)

    # 找到第一个 { 和对应的 }
    start = text.find('{')
    if start == -1:
        return None

    # 从 start 开始，用栈匹配花括号
    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        return None

    json_str = text[start:end + 1]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # 尝试修复常见问题：未转义的换行符在字符串中
        try:
            fixed = _re.sub(r'(?<!\\)"([^"]*\n[^"]*)"', lambda m: '"' + m.group(1).replace('\n', '\\n') + '"', json_str)
            return json.loads(fixed)
        except:
            return None


def _extract_chorus(lyrics: str) -> str:
    """
    从结构化歌词中提取高潮/副歌部分（[Chorus] 标签内的内容）。
    如果找不到标签，用 LLM 方式提取最经典的 4-8 句。
    """
    import re as _re

    # 策略1: 找 [Chorus] / [chorus] / [副歌] 标签
    chorus_match = _re.search(
        r'\[Chorus\]\s*\n?([^\[]+?)(?=\n?\[|$)',
        lyrics,
        _re.IGNORECASE | _re.DOTALL
    )
    if chorus_match:
        chorus = chorus_match.group(1).strip()
        # 只取前 4-8 行
        lines = [l.strip() for l in chorus.split('\n') if l.strip()]
        if 4 <= len(lines) <= 12:
            return '\n'.join(lines)
        if len(lines) > 12:
            return '\n'.join(lines[:8])

    # 策略2: 找重复出现的段落（通常是副歌）
    lines = [l.strip() for l in lyrics.split('\n') if l.strip() and not l.strip().startswith('[')]
    if len(lines) >= 4:
        # 简单策略：取中间 4-8 行（通常副歌在中间）
        start = max(0, len(lines) // 3)
        end = min(len(lines), start + 8)
        return '\n'.join(lines[start:end])

    return lyrics


async def _fallback_improvise(
    update: Update,
    chat_id: int,
    song_name: str,
    song_style: str,
    llm_service,
    voice_service,
):
    """降级：即兴创作"""
    await update.message.reply_text(
        f"唔... 我没找到《{song_name}》的音源，不过我可以即兴创作一首！🎵",
    )
    lyrics_prompt = f"""请以「{song_name}」为主题创作一首简短可爱的歌词。

要求：
- 4-8句歌词，每句一行，用换行分隔
- 用[verse]和[chorus]标记段落
- 如果这是一首知名歌曲，尽量回忆并写出它的经典歌词片段
- 只输出歌词本身，不要任何其他文字"""

    song_resp = await llm_service.client.chat.completions.create(
        model=llm_service.model_fast,
        messages=[{"role": "user", "content": lyrics_prompt}],
        max_tokens=300,
        temperature=0.9,
    )
    lyrics = song_resp.choices[0].message.content or ""

    audio_reply = await voice_service.generate_music(
        lyrics=lyrics,
        style=song_style,
    )
    import io
    voice_file = io.BytesIO(audio_reply)
    voice_file.name = "song.mp3"
    await context.bot.send_voice(chat_id=chat_id, voice=voice_file, caption="")


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

    # 构建系统提示
    from app.main import llm_service, SUNDAY_SYSTEM_PROMPT
    system_prompt = SUNDAY_SYSTEM_PROMPT

    # 获取记忆上下文
    memories = memory_store.get_conversation_context(user_id, max_turns=5) or ""

    # 构建消息
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"以下是你的记忆（只参考，不重复）：\n{memories}\n\n用户说：{text}"},
    ]

    # 调用 LLM
    try:
        response = await llm_service.client.chat.completions.create(
            model=llm_service.model_fast,
            messages=messages,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )
        reply = response.choices[0].message.content or ""

        # 记录到对话流
        memory_store.add_conversation(user_id, "user", text)
        memory_store.add_conversation(user_id, "assistant", reply)
        log("chat", user_id, "telegram", text[:100])

        return reply
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        return "唔... 我的大脑刚才短路了一下，再说一次好不好？🥺"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理文字消息"""
    user_id = _get_user_id(update)
    text = update.message.text or ""

    # 普通消息处理
    reply = await _process_message_text(text, user_id, update, context)
    if reply:
        await _send_smart_reply(update, reply)

async def _send_smart_reply(update: Update, text: str):
    """智能发送回复，根据内容长度选择文字或语音"""
    await update.message.reply_text(text)


# ========== 快捷指令处理 ==========

async def handle_shortcut_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理快捷指令消息（以 / 开头）"""
    text = update.message.text or ""
    user_id = _get_user_id(update)

    # 解析快捷指令
    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    # 获取或创建 session
    session_id = USER_SESSIONS.get(user_id)
    if not session_id:
        session_id = f"tg_{user_id}_{datetime.now(TZ).strftime('%Y%m%d')}"
        USER_SESSIONS[user_id] = session_id

    # 调用主 API
    from app.main import process_chat
    try:
        result = await process_chat(args, session_id, user_id)
        await update.message.reply_text(result.get("reply", "收到！"))
    except Exception as e:
        logger.error(f"快捷指令处理失败: {e}")
        await update.message.reply_text("唔... 处理指令时出了点小问题 🥺")


# ========== 意图识别与处理 ==========

async def _ai_detect_intent(text: str, user_id: str) -> dict:
    """用 AI 检测用户意图"""
    # 简单关键词匹配（后续可升级为 LLM 意图识别）
    text_lower = text.lower()

    # 邮件相关
    if any(kw in text_lower for kw in ["发邮件", "发email", "send email", "邮件提醒"]):
        return {"type": "email", "content": text}

    # 记忆查询
    if any(kw in text_lower for kw in ["我记得", "你记得", "回忆", "以前说过"]):
        return {"type": "memory_query", "content": text}

    # 计划/待办
    if any(kw in text_lower for kw in ["计划", "待办", "todo", "任务", "提醒"]):
        return {"type": "plan", "content": text}

    return None


async def _handle_ai_intent(update: Update, context: ContextTypes.DEFAULT_TYPE, intent: dict, user_id: str):
    """处理检测到的 AI 意图"""
    intent_type = intent.get("type")
    content = intent.get("content", "")

    if intent_type == "email":
        # 提取邮件内容
        await update.message.reply_text("📧 邮件功能开发中，先帮我记一下内容吧~")
    elif intent_type == "memory_query":
        # 查询记忆
        memories = memory_store.search(user_id, query=content, limit=5)
        if memories:
            reply = "我记得这些：\n\n" + "\n".join([f"• {m['content'][:100]}" for m in memories])
        else:
            reply = "唔... 我暂时没找到相关的记忆 🥺"
        await update.message.reply_text(reply)
    elif intent_type == "plan":
        await update.message.reply_text("📝 计划功能开发中，先用文字告诉我吧~")


# ========== 反馈检测 ==========

def _detect_feedback(text: str, user_id: str) -> bool:
    """检测用户是否在提供改进反馈"""
    feedback_keywords = ["改进", "建议", "反馈", "bug", "问题", "不好", "希望", "能不能", "可以不可以"]
    return any(kw in text for kw in feedback_keywords)


async def _auto_check_plan_done(text: str, user_id: str, update: Update):
    """自动检测用户是否完成了计划"""
    # 简单检测：如果用户提到"完成了""做完了"等
    done_keywords = ["完成了", "做完了", "搞定", "done", "finish"]
    if any(kw in text for kw in done_keywords):
        # 检查是否有进行中的计划
        pass  # 后续实现


# ========== Bot 启动 ==========

def start_telegram_bot():
    """初始化 Telegram Bot，返回 Application 对象"""
    if not TELEGRAM_TOKEN:
        logger.warning("Telegram Token 未配置，跳过 Bot 启动")
        return None

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # 注册处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.COMMAND, handle_shortcut_command))

    # 错误处理
    async def error_handler(update, context):
        logger.error(f"Telegram 错误: {context.error}")

    application.add_error_handler(error_handler)

    logger.info("Sunday Telegram Bot 已初始化 💕")
    return application


async def run_telegram_bot(application: Application):
    """启动 Telegram Bot 轮询"""
    if not application:
        return
    logger.info("Sunday Telegram Bot 开始轮询... 💕")
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    app = start_telegram_bot()
    if app:
        import asyncio as _a
        _a.run(run_telegram_bot(app))
