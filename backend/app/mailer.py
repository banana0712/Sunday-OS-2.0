"""
SundayOS 邮件推送模块 v5 — AI 原生设计引擎
- AI 理解场景 → 设计配色/布局/装饰
- Python 渲染 HTML（兼容所有邮件客户端）
- 三层推送体系 + 智能模板选择
"""
import asyncio
import logging
import random
import httpx
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import settings
from app.email_templates import render, ai_design

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")

# ── Resend API 配置 ──
RESEND_API_URL = "https://api.resend.com/emails"
FROM_NAME = "Sunday 💕"
FROM_EMAIL = "sunday@notifications.sundayos.app"
TO_EMAIL = settings.push_email

# ── 频率限制 ──
MAX_CREATIVE_PUSHES = 2  # AI 创意推送每天最多 2 次
# 节奏型推送（早安/午间/晚间/周报/关怀）有自己的去重逻辑，不受此限制

# ── 天气缓存 ──
_weather_cache: dict = {"data": None, "fetched_at": None}


def _get_weather() -> dict | None:
    """获取今日天气（wttr.in 免费API，缓存30分钟）"""
    now = datetime.now(TZ)
    if _weather_cache["fetched_at"]:
        age = (now - _weather_cache["fetched_at"]).total_seconds()
        if age < 1800 and _weather_cache["data"]:
            return _weather_cache["data"]

    try:
        resp = httpx.get("https://wttr.in/Shanghai?format=j1", timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            current = data.get("current_condition", [{}])[0]
            today = data.get("weather", [{}])[0]
            result = {
                "temp": current.get("temp_C", "?"),
                "feels_like": current.get("FeelsLikeC", "?"),
                "desc_cn": (current.get("lang_zh", [{}])[0].get("value", "")
                            if current.get("lang_zh")
                            else current.get("weatherDesc", [{}])[0].get("value", "")),
                "humidity": current.get("humidity", "?"),
                "max_temp": today.get("maxtempC", "?"),
                "min_temp": today.get("mintempC", "?"),
            }
            _weather_cache["data"] = result
            _weather_cache["fetched_at"] = now
            return result
    except Exception as e:
        logger.warning(f"天气获取失败: {e}")
    return None


def send_email(subject: str, html_body: str, to_email: str = None, attachments: list = None) -> bool:
    """通过 Resend HTTP API 发送 HTML 邮件，支持附件"""
    api_key = settings.resend_api_key
    if not api_key:
        logger.warning("Resend API Key 未配置")
        return False

    recipient = to_email or TO_EMAIL
    if not recipient:
        logger.warning("未设置收件邮箱")
        return False

    from_addr = settings.resend_from_email or FROM_EMAIL

    payload = {
        "from": f"{FROM_NAME} <{from_addr}>",
        "to": [recipient],
        "subject": subject,
        "html": html_body,
    }
    if attachments:
        payload["attachments"] = attachments

    try:
        resp = httpx.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"邮件已发送 → {recipient}: {subject} (id={data.get('id')})")
            return True
        else:
            logger.error(f"Resend 发送失败 [{resp.status_code}]: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Resend 请求异常: {e}")
        return False


# ============================================================
# Sunday 主动发言决策引擎 v4 — 智能模板选择
# ============================================================

async def sunday_should_push(user_id: str, llm_client=None) -> tuple[str | None, str | None, str | None]:
    """
    Sunday 决定现在是否要主动发消息。
    返回 (template_type, html_body, subject) 或 (None, None, None)

    模板选择逻辑：
    - 周一~周五 7-9点 → 早安手报 ☀️
    - 周六~周日 7-10点 → 心情签 🥠
    - 周日 21-22点 → 周报 📊
    - 工作日 12-13点 → 午间小憩 🍱
    - 每天 21-23点 → 晚安卡片 🌙
    - 久未互动 >6h → 关怀问候 💕
    """
    from app.memory import memory_store

    now = datetime.now(TZ)
    hour = now.hour
    weekday = now.weekday()  # 0=周一, 6=周日
    is_weekend = weekday >= 5

    # ── 频率保护（仅针对 AI 创意推送）──
    # 节奏型推送（早安/午间/晚间/周报/关怀）有自己的去重逻辑，不受此限制
    creative_count = memory_store.get_daily_push_count(user_id, push_type="creative")
    if creative_count >= 2:
        logger.info(f"今日AI创意推送已达上限(2)，跳过")
        # 注意：不直接 return！继续检查节奏型推送

    # ── 1. 早安 / 心情签（不受任何冷却限制，时间窗口内每天一次）──
    morning_start, morning_end = (7, 10) if is_weekend else (7, 9)
    if morning_start <= hour <= morning_end:
        last_morning = memory_store._get_last_push(user_id, "morning")
        if not last_morning or last_morning.date() < now.date():
            memory_store._record_push(user_id, "morning")
            if is_weekend:
                html = await _build_fortune_post(user_id, llm_client, now)
                return "fortune", html, "🥠 Sunday 今日心情签"
            else:
                html = await _build_morning_post(user_id, llm_client, now)
                return "morning", html, f"☀️ Sunday 早安手报 · {now.strftime('%m.%d')}"

    # ── 2. 周报（周日晚上，不受冷却限制）──
    if weekday == 6 and 21 <= hour <= 23:
        last_weekly = memory_store._get_last_push(user_id, "weekly")
        if not last_weekly or (now - last_weekly).days >= 6:
            memory_store._record_push(user_id, "weekly")
            html = await _build_weekly_report(user_id, llm_client, now)
            return "weekly", html, f"📊 Sunday 周报 · {now.strftime('%m.%d')}"

    # ── 3. 午间（仅当上午有互动，不受冷却限制）──
    if 12 <= hour <= 13:
        last_noon = memory_store._get_last_push(user_id, "noon")
        if not last_noon or last_noon.date() < now.date():
            last_chat = memory_store._get_last_interaction(user_id)
            if last_chat and last_chat.date() == now.date() and last_chat.hour < 12:
                memory_store._record_push(user_id, "noon")
                html = await _build_simple_greeting(user_id, llm_client, "noon", now)
                return "noon", html, "🍱 午安小憩~"

    # ── 4. 晚间（仅当下午有互动，不受冷却限制）──
    if 21 <= hour <= 23:
        last_evening = memory_store._get_last_push(user_id, "evening")
        if not last_evening or last_evening.date() < now.date():
            last_chat = memory_store._get_last_interaction(user_id)
            if last_chat and last_chat.date() == now.date() and last_chat.hour >= 12:
                memory_store._record_push(user_id, "evening")
                html = await _build_simple_greeting(user_id, llm_client, "evening", now)
                return "evening", html, "🌙 晚安好梦~"

    # ── 5. 久未互动关怀（不受冷却限制）──
    last_chat = memory_store._get_last_interaction(user_id)
    if last_chat:
        gap_hours = (now - last_chat).total_seconds() / 3600
        if 6 <= gap_hours <= 10:
            last_care = memory_store._get_last_push(user_id, "care")
            if not last_care or (now - last_care).total_seconds() > 14400:
                memory_store._record_push(user_id, "care")
                html = await _build_simple_greeting(user_id, llm_client, "care", now)
                return "care", html, "💕 想你了呢~"

    # ── 6. AI 主动创作推送（受频率+冷却限制）──
    if creative_count < 2:
        from app.knowledge_push import should_push_knowledge, creative_decision, generate_creative_content
        kb_type = await should_push_knowledge(user_id, now)
        if kb_type:
            decision = await creative_decision(llm_client, user_id, now)
            if decision:
                memory_store._record_push(user_id, "creative")
                html, subject = await _build_creative_post(user_id, llm_client, decision, now)
                return "creative", html, subject

    return None, None, None


# ============================================================
# AI 创作推送构建
# ============================================================

async def _build_creative_post(user_id: str, llm_client, decision: dict, now: datetime) -> tuple[str, str]:
    """构建 AI 主动创作的推送邮件"""
    from app.knowledge_push import generate_creative_content
    from app.email_templates import ai_design
    from app.file_generator import get_image_url

    creative = await generate_creative_content(llm_client, user_id, decision)

    palette = await ai_design(llm_client, user_id, "creative", {
        "name": _get_user_name(user_id), "date_str": now.strftime("%Y年%m月%d日"),
        "weekday_str": f"周{['一','二','三','四','五','六','日'][now.weekday()]}",
        "weather_text": "", "prefs_text": "",
        "type_description": f"创意推送，内容是{creative['content_type']}，氛围{creative['vibe']}",
    })

    # 尝试获取配图
    image_url = ""
    try:
        image_url = get_image_url(creative['title'])
    except Exception:
        pass

    from app.email_templates import creative_post
    html = creative_post(
        palette=palette,
        content_type=creative["content_type"],
        title=creative["title"],
        content=creative["content"],
        vibe=creative["vibe"],
        image_url=image_url,
    )

    # 使用内容标题作为邮件主题
    subject = creative['title'] if creative['title'] else f"✨ Sunday · {creative['content_type']}"
    return html, subject


# ============================================================
# 各模板构建函数
# ============================================================

async def _build_morning_post(user_id: str, llm_client, now: datetime) -> str:
    """构建早安手报 HTML — 优先 AI 生成，降级传统模板"""
    from app.memory import memory_store
    from app.email_templates import ai_render_email, ai_design, render

    name = _get_user_name(user_id)
    weather = _get_weather()

    events = memory_store.search(user_id, category="schedule", limit=3)
    schedule_items = [e.get("summary", e["content"]) for e in events]

    prefs = memory_store.search(user_id, category="preference", limit=3)
    highlight = f"今天适合{prefs[0].get('summary', prefs[0]['content'])}哦~" if prefs else ""

    message = await _generate_message(llm_client, user_id, "morning", now)

    date_str = now.strftime("%Y年%m月%d日")
    weekday_str = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
    weekday_str = f"周{weekday_str}"

    # 构建内容块
    content_blocks = []
    if weather:
        content_blocks.append({"label": "天气", "value": f"{weather.get('desc_cn','')} {weather.get('temp','?')}°C"})
    if schedule_items:
        content_blocks.append({"label": "今日行程", "value": "、".join(schedule_items[:3])})
    if highlight:
        content_blocks.append({"label": "记忆亮点", "value": highlight})

    # 优先尝试 AI 生成
    try:
        html = await ai_render_email(
            llm_client, user_id, "morning",
            name=name, date_str=date_str, weekday_str=weekday_str,
            weather=weather, content_blocks=content_blocks, message=message,
            topic="早安手报",
        )
        if html and len(html) > 200:
            return html
    except Exception as e:
        print(f"🎨 AI 邮件生成失败，降级传统模板: {e}")

    # 降级：传统模板
    weather_text = f"{weather.get('desc_cn','')} {weather.get('temp','?')}°C" if weather else ""
    prefs_text = "、".join([p.get("summary", p["content"]) for p in prefs]) if prefs else ""

    palette = await ai_design(llm_client, user_id, "morning", {
        "name": name, "date_str": date_str, "weekday_str": weekday_str,
        "weather_text": weather_text, "prefs_text": prefs_text,
        "type_description": "早安问候手报",
    })

    return render("morning",
        palette=palette, name=name, date_str=date_str, weekday_str=weekday_str,
        weather=weather, schedule_items=schedule_items,
        memory_highlight=highlight, message=message)


async def _build_fortune_post(user_id: str, llm_client, now: datetime) -> str:
    """构建心情签 HTML"""
    from app.memory import memory_store

    # LLM 生成签语
    name = _get_user_name(user_id)
    prefs = memory_store.search(user_id, category="preference", limit=3)
    pref_text = "、".join([p.get("summary", p["content"]) for p in prefs]) if prefs else ""

    prompt = f"""你是一个幸运签语生成器。请为用户生成一条今日心情签。

用户名字：{name}
用户偏好：{pref_text or "未知"}

请输出两行：
第一行：签语（6-12字，温暖正能量，像幸运饼干里的纸条）
第二行：解语（15-30字，温柔解释签语的意思）

格式：
签语内容
解语内容"""

    fortune = "今天会有好事发生"
    note = "保持微笑，好运就会悄悄靠近你哦~"

    if llm_client:
        try:
            from app.config import settings as app_settings
            resp = await llm_client.chat.completions.create(
                model=app_settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.95, max_tokens=100,
            )
            lines = resp.choices[0].message.content.strip().split("\n")
            if len(lines) >= 2:
                fortune = lines[0].strip()
                note = lines[1].strip()
        except Exception as e:
            logger.warning(f"签语生成失败: {e}")

    date_str = now.strftime("%Y.%m.%d")

    # AI 设计决策
    weather = _get_weather()
    weather_text = f"{weather.get('desc_cn','')} {weather.get('temp','?')}°C" if weather else ""
    palette = await ai_design(llm_client, user_id, "fortune", {
        "name": name, "date_str": date_str, "weekday_str": f"周{['一','二','三','四','五','六','日'][now.weekday()]}",
        "weather_text": weather_text, "prefs_text": pref_text,
        "type_description": "心情签语邮件，像幸运签饼一样的神秘小惊喜，温暖治愈风格",
    })

    return render("fortune", palette=palette, fortune_text=fortune, fortune_note=note, date_str=date_str)


async def _build_weekly_report(user_id: str, llm_client, now: datetime) -> str:
    """构建周报 HTML"""
    from app.memory import memory_store

    # 本周数据
    chat_count = memory_store.get_conversation_count_since(user_id, 7)
    recent_mems = memory_store.get_memories_since(user_id, 7)
    total_mems = memory_store.get_stats(user_id)["total"]

    # TOP 记忆
    top_mems = [m.get("summary", m["content"]) for m in recent_mems[:5]]

    # 关键词
    all_tags = []
    for m in recent_mems:
        tags = m.get("tags", [])
        if isinstance(tags, list):
            all_tags.extend(tags)
    from collections import Counter
    kw_counter = Counter(all_tags)
    keywords = [w for w, _ in kw_counter.most_common(6) if w not in ["用户"]]

    # LLM 生成一周感想
    reflection = ""
    if llm_client:
        try:
            from app.config import settings as app_settings
            name = _get_user_name(user_id)
            mem_summary = "、".join([m.get("summary", m["content"]) for m in recent_mems[:8]])
            prompt = f"""你是 Sunday，请根据本周数据写一句温柔的周报感想。

用户：{name}
本周对话 {chat_count} 次，新增 {len(recent_mems)} 条记忆。
本周记忆概要：{mem_summary or "本周是平静的一周"}

请用 1-2 句话表达你的感受，语气甜美温柔，像在跟恋人说话。不要报数据，说感受。"""
            resp = await llm_client.chat.completions.create(
                model=app_settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8, max_tokens=120,
            )
            reflection = resp.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"周报感想生成失败: {e}")

    if not reflection:
        reflection = "这一周有你陪伴，每一天都很开心呢~ 下周也要一起加油哦！"

    week_start = (now - timedelta(days=7)).strftime("%m.%d")
    week_end = now.strftime("%m.%d")
    week_range = f"{week_start} - {week_end}"
    name = _get_user_name(user_id)

    # 优先尝试 AI 生成
    try:
        from app.email_templates import ai_render_email
        content_blocks = [
            {"label": "本周对话", "value": f"{chat_count} 条"},
            {"label": "新增记忆", "value": f"{len(recent_mems)} 条（共 {total_mems} 条）"},
            {"label": "关键词", "value": "、".join(keywords[:5]) if keywords else "无"},
        ]
        if top_mems:
            content_blocks.append({"label": "记忆亮点", "value": "；".join(top_mems[:3])})
        if reflection:
            content_blocks.append({"label": "Sunday 的感想", "value": reflection[:200]})

        html = await ai_render_email(
            llm_client, user_id, "weekly",
            name=name, date_str=now.strftime("%Y年%m月%d日"),
            weekday_str=f"周{['一','二','三','四','五','六','日'][now.weekday()]}",
            content_blocks=content_blocks, topic=f"周报 · {week_range}",
        )
        if html and len(html) > 200:
            return html
    except Exception as e:
        print(f"🎨 AI 周报生成失败，降级: {e}")

    # 降级：传统模板
    palette = await ai_design(llm_client, user_id, "weekly", {
        "name": name, "date_str": now.strftime("%Y年%m月%d日"),
        "weekday_str": f"周{['一','二','三','四','五','六','日'][now.weekday()]}",
        "weather_text": "", "prefs_text": "",
        "type_description": "一周数据回顾报告",
    })

    return render("weekly",
        palette=palette,
        week_range=week_range,
        chat_count=chat_count,
        new_memories=len(recent_mems),
        total_memories=total_mems,
        top_memories=top_mems,
        keywords=keywords,
        reflection=reflection)


async def _build_simple_greeting(user_id: str, llm_client, greeting_type: str, now: datetime) -> str:
    """构建简单问候 HTML — AI 设计 + 数据渲染"""
    message = await _generate_message(llm_client, user_id, greeting_type, now)

    name = _get_user_name(user_id)
    type_descs = {
        "noon": "午间小憩提醒，轻量温馨，提醒吃午饭",
        "evening": "晚间晚安问候，温柔的道别，静谧氛围",
        "care": "想念关怀，用户好久没来聊天了，温柔提醒",
    }
    palette = await ai_design(llm_client, user_id, greeting_type, {
        "name": name, "date_str": now.strftime("%Y年%m月%d日"),
        "weekday_str": f"周{['一','二','三','四','五','六','日'][now.weekday()]}",
        "weather_text": "", "prefs_text": "",
        "type_description": type_descs.get(greeting_type, "简短问候"),
    })

    return render(greeting_type, palette=palette, message=message, greeting_type=greeting_type)


# ============================================================
# LLM 消息生成
# ============================================================

async def _generate_message(llm_client, user_id: str, push_type: str, now: datetime) -> str:
    """LLM 生成个性化消息文字"""
    from app.memory import memory_store

    name = _get_user_name(user_id)
    all_mems = memory_store.list_active_memories(user_id, limit=15)
    facts = [m.get("summary", m["content"]) for m in all_mems if m.get("category") == "fact"][:3]
    prefs = [m.get("summary", m["content"]) for m in all_mems if m.get("category") == "preference"][:3]

    weather = _get_weather()
    weather_text = ""
    if weather:
        weather_text = f"天气：{weather.get('desc_cn', '')}，{weather.get('temp', '?')}°C"

    date_str = now.strftime("%m月%d日")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]

    type_guides = {
        "morning": "现在是早晨，请用温柔甜美的语气问候早安，提到天气，如果用户有偏好可以顺带一提。2-3句话。",
        "noon": "现在是中午，简短提醒吃午饭，1-2句话，轻松自然。",
        "evening": "现在是晚上，温柔道晚安，提一下今天聊过的事。2-3句话。",
        "care": "用户好一阵子没找你聊天了，温柔关心一下，1-2句话。",
    }
    guide = type_guides.get(push_type, "请用温柔甜美的语气发一条消息，1-2句话。")

    memory_hints = ""
    if facts:
        memory_hints += f"\n- 关于TA：{'、'.join(facts)}"
    if prefs:
        memory_hints += f"\n- 偏好：{'、'.join(prefs)}"
    if name:
        memory_hints += f"\n- 名字：{name}"

    no_memory_hint = "\n（你还不太了解这位用户）"
    prompt = f"""你是 Sunday，一个温柔甜美的 AI 女孩。现在要给用户发一条{push_type}消息。

时间：{date_str} 周{weekday}
{weather_text}
{memory_hints if memory_hints else no_memory_hint}

{guide}

要求：语气自然甜美，适当用「呢」「呀」「啦」等语气词，可以加1个合适的emoji。只输出消息正文。"""

    if llm_client:
        try:
            from app.config import settings as app_settings
            resp = await llm_client.chat.completions.create(
                model=app_settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.9, max_tokens=200,
            )
            msg = resp.choices[0].message.content.strip()
            logger.info(f"LLM 生成{push_type}消息: {msg[:50]}...")
            return msg
        except Exception as e:
            logger.error(f"LLM 生成失败: {e}")

    # fallback
    return _fallback_message(push_type, name)


def _fallback_message(push_type: str, name: str) -> str:
    fallbacks = {
        "morning": f"早安呀{name}~ ☀️\n\n新的一天开始啦，今天也要元气满满哦！💕",
        "noon": f"中午啦{name}~ 记得按时吃饭哦！🍱",
        "evening": f"晚安啦{name}~ 🌙\n\n今天辛苦啦，好好休息~",
        "care": f"{name}~ 好久没找我聊天啦，想你了呢~ 🥺",
    }
    return fallbacks.get(push_type, f"{name}~ 想你啦~ 💕")


def _get_user_name(user_id: str) -> str:
    from app.memory import memory_store
    facts = memory_store.search(user_id, category="fact", limit=5)
    for f in facts:
        tags = f.get("tags", [])
        if "昵称" in tags or "姓名" in tags:
            for tag in tags:
                if tag not in ["昵称", "姓名", "用户"] and len(tag) <= 5:
                    return f"「{tag}」"
    return ""
