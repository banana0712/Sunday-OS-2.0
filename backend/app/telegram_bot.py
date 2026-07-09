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

        song_decision_prompt = f"""你是 Sunday，一个会唱歌的 AI 女孩。请判断用户是否想让你唱歌，并提取歌曲名。

用户说：「{text}」

最近对话：
{recent_messages[:500]}

判断规则：
- 明确要求唱歌（"唱首歌""唱歌""唱一个"等）→ 唱歌
- 提到音乐、旋律、歌曲相关 → 唱歌
- 普通聊天、提问、闲聊 → 不唱歌

歌曲名提取：
- 如果用户指定了具体歌曲（如"唱小幸运""唱稻香""来一首青花瓷"），提取歌曲名
- 注意去掉量词（"一首""一个""首"）和语气词（"吧""呗""嘛"）
- 如果没指定具体歌曲，song_name 留空

请只回复一个 JSON：
{{"should_sing": true/false, "song_name": "歌曲名（如小幸运、稻香），没指定则留空", "song_theme": "歌曲主题描述，如用户指定了主题就按用户的意思，否则根据上下文推断", "style": "音乐风格描述，如甜美J-Pop、温柔民谣等"}}"""

        should_sing = False
        song_theme = ""
        song_style = "甜美可爱的女声，轻快J-Pop，动漫主题曲风格"
        specified_song = ""  # AI 提取的歌曲名
        try:
            decision_resp = await llm_service.client.chat.completions.create(
                model=llm_service.model_fast,
                messages=[{"role": "user", "content": song_decision_prompt}],
                max_tokens=200,
                temperature=0.3,
            )
            decision_text = decision_resp.choices[0].message.content or ""
            print(f"🎵 [MUSIC] AI 判断结果: {decision_text[:200]}")
            # 提取 JSON
            import re as _re
            json_match = _re.search(r'\{[^}]+\}', decision_text)
            if json_match:
                decision = json.loads(json_match.group())
                should_sing = decision.get("should_sing", False)
                song_theme = decision.get("song_theme", "")
                song_style = decision.get("style", song_style)
                specified_song = decision.get("song_name", "")
        except Exception as e:
            print(f"🎵 [MUSIC] AI 判断失败: {e}")
            # 降级：用关键词兜底
            sing_keywords = ["唱歌", "唱一首", "唱个歌", "唱支歌", "唱什么", "唱一个", "来一首", "来一个", "唱来听听", "唱首歌"]
            should_sing = any(kw in text for kw in sing_keywords)

        if should_sing:
            print(f"🎵 [MUSIC] AI 决定唱歌！主题={song_theme} 风格={song_style}")
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
            try:
                # AI 已提取歌曲名，正则作为兜底清洗
                import re as _re
                if specified_song:
                    # 清洗 AI 提取的歌曲名
                    specified_song = _re.sub(r'^[一首一个首个]+', '', specified_song)
                    specified_song = _re.sub(r'[。！？.!?]+$', '', specified_song)
                    specified_song = specified_song.strip()
                else:
                    # 兜底：正则提取
                    song_name_match = _re.search(
                        r'(?:唱|来一?首|点一首?|会唱|唱首|唱个)(.{1,20}?)(?:这首歌|那首歌|这首|那首|给我听|吧|呗|嘛|好吗|可以吗|好不好)?$',
                        text
                    )
                    specified_song = song_name_match.group(1).strip() if song_name_match else ""
                    specified_song = _re.sub(r'^[一首一个首个]+', '', specified_song)
                    specified_song = _re.sub(r'[。！？.!?]+$', '', specified_song)
                    specified_song = specified_song.strip()

                if specified_song and len(specified_song) >= 2:
                    # ===== 指定歌曲 → 翻唱模式（保留原曲旋律）=====
                    print(f"🎵 [COVER] 用户指定歌曲: {specified_song}")
                    await _handle_song_cover(
                        update=update,
                        context=context,
                        chat_id=chat_id,
                        user_id=user_id,
                        song_name=specified_song,
                        song_style=song_style,
                        llm_service=llm_service,
                        voice_service=voice_service,
                    )
                else:
                    # ===== 即兴创作 → 原创模式（music-2.6-free）=====
                    print(f"🎵 [MUSIC] 即兴创作模式")
                    lyrics_prompt = f"""请创作一首简短可爱的歌词。

用户想听的主题：{song_theme}
音乐风格：{song_style}

要求：
- 4-8句歌词，每句一行，用换行分隔
- 用[verse]和[chorus]标记段落
- 歌词要贴合主题，甜美可爱
- 只输出歌词本身，不要任何其他文字、解释或括号描述

示例格式：
[verse]
今天阳光真好啊
小鸟在窗外唱歌
[chorus]
啦啦啦好开心呀
和你在一起的每一天"""

                    song_resp = await llm_service.client.chat.completions.create(
                        model=llm_service.model_fast,
                        messages=[{"role": "user", "content": lyrics_prompt}],
                        max_tokens=300,
                        temperature=0.9,
                    )
                    lyrics = song_resp.choices[0].message.content or ""
                    print(f"🎵 [MUSIC] LLM 歌词: {lyrics[:150]}")

                    audio_reply = await voice_service.generate_music(
                        lyrics=lyrics,
                        style=song_style
                    )
                    print(f"🎵 [MUSIC] 歌曲生成完成，发送中...")

                    import io
                    voice_file = io.BytesIO(audio_reply)
                    voice_file.name = "song.mp3"
                    await context.bot.send_voice(
                        chat_id=chat_id,
                        voice=voice_file,
                        caption=""
                    )
                _record_voice_usage(user_id)
                return  # 唱歌完成，不走下面的普通流程
            except Exception as music_e:
                import traceback as _tb
                print(f"🎵 [MUSIC] 失败: {music_e}\n{_tb.format_exc()}")
                # 降级：让 LLM 正常回复 + TTS
                await update.message.reply_text("唔... 唱歌引擎出了点小问题，下次再唱给你听~ 🥺")
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


async def _handle_song_cover(
    update: Update,
    context,
    chat_id: int,
    user_id: str,
    song_name: str,
    song_style: str,
    llm_service,
    voice_service,
):
    """
    AI 驱动的歌曲搜索 + 翻唱。
    流程：
    1. 网易云搜索歌曲
    2. AI 筛选最匹配的结果
    3. 获取试听链接
    4. 预处理 + 翻唱
    如果找不到，降级为即兴创作。
    """
    import re as _re

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
    await update.message.reply_text(f"让我在网上找找《{song_name}》... 🔍")

    # ===== 步骤1: 网易云搜索歌曲 =====
    search_results = await voice_service.search_song(song_name, limit=10)

    if not search_results:
        print(f"🎵 [COVER] 网易云搜索无结果")
        await _fallback_improvise(update, chat_id, song_name, song_style, llm_service, voice_service)
        return

    # ===== 步骤2: AI 筛选最匹配的歌曲 =====
    candidates_text = ""
    for i, s in enumerate(search_results):
        candidates_text += f"[{i}] {s['name']} - {s['artists']} (专辑: {s['album']})\n"

    selection_prompt = f"""请从以下搜索结果中选出最匹配用户想要的歌曲。

用户想听：{song_name}

搜索结果：
{candidates_text}

选择规则：
- 优先选歌名完全匹配的
- 其次选歌名包含用户关键词的
- 原唱优先于翻唱
- 如果搜索结果和用户想要的完全不同，返回 index=-1

请只回复一个 JSON：
{{"index": 0, "reason": "选择原因（一句话）"}}"""

    selected_index = 0
    try:
        sel_resp = await llm_service.client.chat.completions.create(
            model=llm_service.model_fast,
            messages=[{"role": "user", "content": selection_prompt}],
            max_tokens=100,
            temperature=0.2,
        )
        sel_text = sel_resp.choices[0].message.content or ""
        print(f"🎵 [COVER] AI 筛选结果: {sel_text[:200]}")

        json_match = _re.search(r'\{[^}]+\}', sel_text)
        if json_match:
            sel = json.loads(json_match.group())
            selected_index = sel.get("index", 0)
            reason = sel.get("reason", "")
            print(f"🎵 [COVER] 选中 [{selected_index}]: {reason}")
    except Exception as e:
        print(f"🎵 [COVER] AI 筛选失败: {e}，使用第一个结果")

    if selected_index < 0 or selected_index >= len(search_results):
        print(f"🎵 [COVER] AI 认为没有匹配结果")
        await _fallback_improvise(update, chat_id, song_name, song_style, llm_service, voice_service)
        return

    selected = search_results[selected_index]
    song_id = selected["id"]
    matched_name = selected["name"]
    matched_artist = selected["artists"]

    await update.message.reply_text(f"找到啦：《{matched_name}》- {matched_artist} 🎶")

    # ===== 步骤3: 获取试听链接 =====
    song_url = await voice_service.get_song_url(song_id, bitrate=128000)

    if not song_url:
        print(f"🎵 [COVER] 歌曲 {matched_name} 无试听链接（可能需要VIP）")
        # 尝试其他搜索结果
        for i, alt_song in enumerate(search_results):
            if i == selected_index:
                continue
            alt_url = await voice_service.get_song_url(alt_song["id"], bitrate=128000)
            if alt_url:
                song_url = alt_url
                matched_name = alt_song["name"]
                matched_artist = alt_song["artists"]
                await update.message.reply_text(f"原版需要VIP，找到了一个可用的版本：《{matched_name}》- {matched_artist} 🎶")
                break

    if not song_url:
        print(f"🎵 [COVER] 所有结果都没有试听链接")
        await _fallback_improvise(update, chat_id, song_name, song_style, llm_service, voice_service)
        return

    # ===== 步骤4: 用歌曲 URL 直接翻唱 =====
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
    await update.message.reply_text("正在分析旋律... 🎶")

    try:
        preprocess_result = await voice_service.preprocess_cover(song_url)
        feature_id = preprocess_result["cover_feature_id"]
        extracted_lyrics = preprocess_result.get("formatted_lyrics", "")

        print(f"🎵 [COVER] 原曲歌词: {extracted_lyrics[:200]}")

        # 提取高潮部分（副歌）加速翻唱
        chorus_lyrics = _extract_chorus(extracted_lyrics)
        if chorus_lyrics:
            print(f"🎵 [COVER] 提取高潮: {chorus_lyrics[:100]}")
            final_lyrics = chorus_lyrics
            await update.message.reply_text("提取了歌曲的高潮部分来翻唱... 🎶")
        else:
            final_lyrics = extracted_lyrics

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        await update.message.reply_text("正在用 Sunday 的风格翻唱... 🎤")

        cover_prompt = f"甜美可爱的女声，J-Pop动漫主题曲风格，温柔甜美，{song_style}"
        audio_reply = await voice_service.generate_cover(
            cover_feature_id=feature_id,
            lyrics=final_lyrics,
            prompt=cover_prompt,
        )

        print(f"🎵 [COVER] 翻唱完成，发送中...")
        import io
        voice_file = io.BytesIO(audio_reply)
        voice_file.name = "cover.mp3"
        await context.bot.send_voice(chat_id=chat_id, voice=voice_file, caption="")

    except Exception as cover_e:
        print(f"🎵 [COVER] 翻唱流程失败: {cover_e}")
        raise


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
