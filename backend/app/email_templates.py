"""
Sunday Post v5 — AI 原生设计引擎
AI 理解场景 → 设计配色/布局/装饰 → Python 渲染 HTML
每封邮件都是独一无二的设计 💌
"""
import json
import random
import inspect
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

TZ = ZoneInfo("Asia/Shanghai")

# ============================================================
# 🔧 渲染引擎（纯 Python，不依赖 AI）
# ============================================================

def _render_mail(content: str, palette: dict) -> str:
    """通用邮件外层"""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:{palette.get('bg','#fef9f4')};">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:500px;margin:0 auto;">
<tr><td style="padding:16px;">
{content}
</td></tr>
</table>
</body>
</html>"""


def _header(title: str, subtitle: str, palette: dict) -> str:
    sub = f'<div style="font-size:12px;color:{palette["muted"]};margin-top:4px;">{subtitle}</div>' if subtitle else ""
    deco = " ".join(palette.get("decor_emojis", ["✨"]))
    return f"""<div style="text-align:center;padding:16px 0 8px;">
<div style="font-size:11px;color:{palette['muted']};margin-bottom:6px;letter-spacing:4px;">{deco}</div>
<div style="font-size:18px;font-weight:700;color:{palette['title']};">{title}</div>
{sub}
</div>"""


def _footer(time_str: str, palette: dict) -> str:
    divider = palette.get("divider_char", "· · ·")
    return f"""<div style="text-align:center;padding:4px 0;">
<span style="font-size:13px;color:{palette['divider']};letter-spacing:4px;">{divider}</span>
</div>
<div style="text-align:center;padding:8px 0;">
<span style="font-size:11px;color:{palette['muted']};">— Sunday · {time_str} —</span>
</div>
<div style="text-align:center;padding:4px 0 12px;">
<span style="font-size:10px;color:{palette['muted']};background:rgba(255,255,255,0.5);padding:3px 10px;border-radius:10px;">💬 回复此邮件和我聊天~</span>
</div>"""


def _badge(text: str, palette: dict) -> str:
    return f'<span style="display:inline-block;background:{palette["accent_light"]};color:{palette["accent_text"]};padding:2px 10px;border-radius:20px;font-size:11px;font-weight:600;margin:2px 3px;">{text}</span>'


def _weather_card(weather: dict, palette: dict) -> str:
    if not weather:
        return ""
    icon = _weather_emoji(weather.get("desc_cn", ""))
    return f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:{palette.get('gradient',palette['accent_light'])};border-radius:14px;margin-bottom:14px;">
<tr><td style="padding:14px 18px;vertical-align:middle;width:50px;"><span style="font-size:32px;">{icon}</span></td>
<td style="padding:14px 0;vertical-align:middle;">
<div style="font-size:15px;color:{palette['accent_text']};font-weight:600;">{weather.get('desc_cn','')} · {weather.get('temp','?')}°C</div>
<div style="font-size:11px;color:{palette['muted']};margin-top:2px;">体感 {weather.get('feels_like','?')}°C · {weather.get('min_temp','?')}~{weather.get('max_temp','?')}°C</div>
</td></tr></table>"""


def _apply_layout(sections: list[str], layout: str, palette: dict) -> str:
    """根据布局名渲染"""
    if layout == "letter":
        inner = "\n".join(sections)
        return f"""<div style="background:{palette['card_bg']};border-radius:20px;padding:28px 24px;box-shadow:0 4px 20px rgba(0,0,0,0.04);border:1px solid {palette['divider']};">
{inner}</div>"""
    elif layout == "magazine" and sections:
        hero = f'<div style="margin-bottom:16px;font-size:110%;">{sections[0]}</div>'
        rest = "\n".join([f'<div style="margin-bottom:10px;font-size:95%;">{s}</div>' for s in sections[1:]])
        return hero + rest
    elif layout == "minimal":
        return "\n".join([f'<div style="margin-bottom:20px;">{s}</div>' for s in sections])
    else:  # cards (default)
        return "\n".join([f'<div style="margin-bottom:14px;">{s}</div>' for s in sections])


# ============================================================
# 🧠 AI 设计引擎
# ============================================================

# 设计缓存：{(user_id, template_type, date_hour): palette}
_design_cache: dict = {}

_VALID_LAYOUTS = {"cards", "letter", "magazine", "minimal"}
_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

# v4 的 fallback 主题（AI 失败时用）
_FALLBACK_THEMES = {
    "sakura": {"bg":"#fef9f4","card_bg":"#ffffff","accent":"#e75480","accent_light":"#fff0f3","accent_text":"#c04060","title":"#5a3a4a","text":"#4a3a3a","muted":"#c9a0a0","gradient":"linear-gradient(135deg,#fff5f5,#fff0f6,#fce4ec)","divider":"#f0c0d0","divider_char":"✿ ❀ ✿","decor_emojis":["🌸","💕","✨"]},
    "matcha": {"bg":"#f8faf5","card_bg":"#ffffff","accent":"#7a9a50","accent_light":"#f0f5e8","accent_text":"#5a7a30","title":"#4a5a3a","text":"#4a4a3a","muted":"#a0b890","gradient":"linear-gradient(135deg,#f5faf0,#f0f5e8,#e8f0d8)","divider":"#c8d8b0","divider_char":"· · ·","decor_emojis":["🍃","🌿","✨"]},
    "ocean": {"bg":"#f5f8fa","card_bg":"#ffffff","accent":"#5a8ab0","accent_light":"#e8f2f8","accent_text":"#3a6a90","title":"#3a5068","text":"#405060","muted":"#90a8c0","gradient":"linear-gradient(135deg,#f0f6fa,#e8f0f8,#dce8f4)","divider":"#c0d4e8","divider_char":"~ ~ ~","decor_emojis":["🌊","💙","✨"]},
    "sunset": {"bg":"#fefaf5","card_bg":"#ffffff","accent":"#d09060","accent_light":"#fff5ed","accent_text":"#b07040","title":"#5a4030","text":"#4a3a30","muted":"#c0a090","gradient":"linear-gradient(135deg,#fff8f0,#fff5e8,#fef0e0)","divider":"#e8d0b8","divider_char":"﹏﹏﹏","decor_emojis":["🌅","🧡","✨"]},
    "lavender": {"bg":"#f9f6fc","card_bg":"#ffffff","accent":"#8a70b8","accent_light":"#f5f0fa","accent_text":"#6a5098","title":"#4a3a5a","text":"#4a4060","muted":"#b0a0c8","gradient":"linear-gradient(135deg,#f8f5ff,#f5f0fa,#f0e8f8)","divider":"#d0c8e8","divider_char":"· · ·","decor_emojis":["💜","🌸","✨"]},
    "midnight": {"bg":"#f5f4f8","card_bg":"#ffffff","accent":"#6a6090","accent_light":"#f0eef8","accent_text":"#4a4070","title":"#3a3a50","text":"#404060","muted":"#a0a0c0","gradient":"linear-gradient(135deg,#f5f4fa,#f0eef8,#e8e4f4)","divider":"#c8c8e0","divider_char":"· · ·","decor_emojis":["🌙","💜","✨"]},
}


def _validate_palette(p: dict) -> bool:
    """校验 AI 输出的 palette 是否合法"""
    required = ["bg", "card_bg", "accent", "accent_light", "accent_text", "title", "text", "muted", "gradient", "divider"]
    for key in required:
        if key not in p:
            return False
    color_keys = ["bg", "card_bg", "accent", "accent_light", "accent_text", "title", "text", "muted", "divider"]
    for key in color_keys:
        if not _HEX_RE.match(p.get(key, "")):
            return False
    return True


async def ai_design(
    llm_client,
    user_id: str,
    template_type: str,
    context: dict,
) -> dict:
    """
    AI 设计决策：输入场景 → 输出 palette + layout + 装饰参数

    context 应包含：name, date_str, weekday_str, weather_text, prefs_text, type_description
    返回：完整的 palette dict（可直接用于渲染）
    """
    from app.config import settings as app_settings

    # 缓存 key：同一用户+类型+日期时段复用设计（避免突兀变化）
    now = datetime.now(TZ)
    cache_key = (user_id, template_type, now.strftime("%Y-%m-%d-%H"))
    if cache_key in _design_cache:
        return _design_cache[cache_key]

    name = context.get("name", "")
    date_str = context.get("date_str", "")
    weekday_str = context.get("weekday_str", "")
    weather_text = context.get("weather_text", "")
    prefs_text = context.get("prefs_text", "")
    type_desc = context.get("type_description", "")

    prompt = f"""你是一个有品味的邮件视觉设计师。请为一封邮件设计配色和风格。

【场景】
- 时间：{date_str} {weekday_str}
- 天气：{weather_text or "未知"}
- 用户：{name or "朋友"}
- 用户偏好：{prefs_text or "未知"}
- 邮件类型：{type_desc}

【任务】
输出一个 JSON，决定这封邮件的视觉设计。

{{
  "vibe": "用2-3个中文词描述氛围（如：温暖治愈、清爽晨光、静谧星空）",
  "palette": {{
    "bg": "#页面背景色",
    "card_bg": "#卡片底色（通常白色或接近白）",
    "accent": "#主强调色（按钮/重点）",
    "accent_light": "#强调色的极浅版（卡片背景）",
    "accent_text": "#强调色对应的深色文字版",
    "title": "#标题颜色",
    "text": "#正文颜色",
    "muted": "#辅助文字/分隔线颜色",
    "gradient": "CSS渐变（如 linear-gradient(135deg,#xxx,#yyy,#zzz)）",
    "divider": "#分隔线颜色"
  }},
  "layout": "cards/letter/magazine/minimal 选一个",
  "divider_char": "3-8个字符的分隔装饰（如 ～ ～ ～ 或 ✿ ❀ ✿）",
  "decor_emojis": ["选3-5个氛围匹配的emoji"],
  "special_element": "一句话描述一个独特设计细节"
}}

【设计原则】
- 配色要有明确的情感倾向，不要永远是粉色
- 根据天气调整：晴天温暖明亮、雨天柔和宁静、阴天干净清爽
- 根据时间调整：早晨清新、午间活泼、晚间温柔
- 颜色值用6位hex（#RRGGBB）
- 大胆创新但保持文字可读性
- 只输出JSON，不要任何解释文字"""

    try:
        resp = await llm_client.chat.completions.create(
            model=app_settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.95,
            max_tokens=500,
        )
        text = resp.choices[0].message.content.strip()

        # 提取 JSON（可能被 markdown 包裹）
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            design = json.loads(json_match.group())

            palette = design.get("palette", {})
            if _validate_palette(palette):
                # 合并所有参数
                result = {**palette}
                result["layout"] = design.get("layout", "cards")
                if result["layout"] not in _VALID_LAYOUTS:
                    result["layout"] = "cards"
                result["divider_char"] = design.get("divider_char", "· · ·")
                result["decor_emojis"] = design.get("decor_emojis", ["✨"])
                result["vibe"] = design.get("vibe", "")
                result["special_element"] = design.get("special_element", "")

                _design_cache[cache_key] = result
                return result
    except Exception as e:
        pass  # fall through to fallback

    # fallback：随机选 v4 主题
    fallback_names = list(_FALLBACK_THEMES.keys())
    name_key = random.choice(fallback_names)
    fb = dict(_FALLBACK_THEMES[name_key])
    fb["layout"] = random.choice(list(_VALID_LAYOUTS))
    fb["vibe"] = ""
    fb["special_element"] = ""
    _design_cache[cache_key] = fb
    return fb


# ============================================================
# 📧 各邮件模板（接收 palette + 数据 → HTML）
# ============================================================

def morning_post(
    palette: dict, name: str = "", date_str: str = "", weekday_str: str = "",
    weather: Optional[dict] = None, schedule_items: list = None,
    memory_highlight: str = "", message: str = "",
) -> str:
    if not date_str:
        now = datetime.now(TZ)
        date_str = now.strftime("%Y年%m月%d日")
        weekday_str = f"周{['一','二','三','四','五','六','日'][now.weekday()]}"
    now = datetime.now(TZ)
    time_str = now.strftime("%H:%M")

    sections = []
    wc = _weather_card(weather, palette)
    if wc:
        sections.append(wc)

    if schedule_items:
        items = ""
        for item in schedule_items:
            text = item if isinstance(item, str) else item.get("summary", item.get("content", ""))
            items += f'<tr><td style="padding:6px 0;font-size:13px;color:{palette["text"]};">📌 {text}</td></tr>'
        sections.append(f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:{palette['accent_light']};border-radius:14px;border:1px solid {palette['divider']};">
<tr><td style="padding:14px 18px 6px;font-size:13px;font-weight:700;color:{palette['accent_text']};">📋 今日行程</td></tr>
{items}<tr><td style="padding:6px 18px 14px;"></td></tr></table>""")

    if memory_highlight:
        sections.append(f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:{palette.get('gradient',palette['accent_light'])};border-radius:14px;border:1px solid {palette['divider']};">
<tr><td style="padding:14px 18px;font-size:13px;color:{palette['accent_text']};text-align:center;">✨ {memory_highlight}</td></tr></table>""")

    if message:
        sections.append(f'<div style="font-size:15px;color:{palette["text"]};line-height:1.9;text-align:center;padding:8px 0;">{message}</div>')

    body = _header("☀️ 早安手报", f"{date_str} {weekday_str}", palette)
    body += _apply_layout(sections, palette.get("layout", "cards"), palette)
    body += _footer(time_str, palette)
    return _render_mail(body, palette)


def fortune_post(palette: dict, fortune_text: str = "", fortune_note: str = "", date_str: str = "") -> str:
    if not date_str:
        now = datetime.now(TZ)
        date_str = now.strftime("%Y.%m.%d")
    now = datetime.now(TZ)
    time_str = now.strftime("%H:%M")

    deco = " ".join(palette.get("decor_emojis", ["✨"]))
    sign = f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:{palette.get('gradient',palette['accent_light'])};border-radius:20px;border:2px solid {palette['divider']};box-shadow:0 6px 24px rgba(0,0,0,0.04);">
<tr><td style="padding:32px 24px;text-align:center;">
<div style="font-size:11px;color:{palette['muted']};margin-bottom:8px;letter-spacing:4px;">{deco}</div>
<div style="font-size:22px;font-weight:700;color:{palette['accent_text']};line-height:1.6;margin-bottom:12px;letter-spacing:2px;">「{fortune_text}」</div>
<div style="font-size:13px;color:{palette['muted']};line-height:1.8;padding:0 8px;">{fortune_note}</div>
<div style="font-size:11px;color:{palette['divider']};margin-top:12px;letter-spacing:4px;">{deco}</div>
</td></tr></table>"""

    body = _header("🥠 Sunday 心情签", "打开今天的幸运签语~", palette)
    body += _apply_layout([sign], palette.get("layout", "letter"), palette)
    body += _footer(time_str, palette)
    return _render_mail(body, palette)


def little_note(palette: dict, message: str = "", note_type: str = "日常", date_str: str = "") -> str:
    if not date_str:
        now = datetime.now(TZ)
        date_str = now.strftime("%m月%d日")
    now = datetime.now(TZ)

    emoji = {"日常": "💌", "想念": "🥺", "惊喜": "🎁", "鼓励": "💪", "感谢": "🙏"}.get(note_type, "💌")

    note = f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:{palette['card_bg']};border-radius:8px;border:2px dashed {palette['divider']};box-shadow:0 4px 16px rgba(0,0,0,0.03);">
<tr><td style="padding:28px 24px;">
<div style="font-family:Georgia,'Times New Roman','Songti SC',serif;font-size:16px;font-style:italic;color:{palette['text']};line-height:2;text-align:center;">
{message}
</div>
</td></tr></table>"""

    body = _header(f"{emoji} 一张小纸条", "Sunday 悄悄塞给你的~", palette)
    body += _apply_layout([note], "letter", palette)
    body += f"""<div style="text-align:right;padding:4px 12px 12px;">
<span style="font-size:12px;color:{palette['muted']};font-style:italic;">— {date_str} · Sunday</span></div>"""
    return _render_mail(body, palette)


def weekly_report(
    palette: dict, week_range: str = "", chat_count: int = 0, new_memories: int = 0,
    total_memories: int = 0, top_memories: list = None,
    keywords: list = None, reflection: str = "",
) -> str:
    now = datetime.now(TZ)
    time_str = now.strftime("%H:%M")
    if not week_range:
        from datetime import timedelta
        ws = (now - timedelta(days=7)).strftime("%m.%d")
        we = now.strftime("%m.%d")
        week_range = f"{ws} - {we}"

    sections = []
    sections.append(f"""<table width="100%" cellpadding="0" cellspacing="0">
<tr>
<td width="33%" style="padding:6px;text-align:center;">
<div style="background:{palette['accent_light']};border-radius:14px;padding:16px 8px;">
<div style="font-size:28px;font-weight:800;color:{palette['accent']};">{chat_count}</div>
<div style="font-size:11px;color:{palette['muted']};margin-top:4px;">💬 对话次数</div></div></td>
<td width="33%" style="padding:6px;text-align:center;">
<div style="background:{palette['accent_light']};border-radius:14px;padding:16px 8px;">
<div style="font-size:28px;font-weight:800;color:{palette['accent']};">{new_memories}</div>
<div style="font-size:11px;color:{palette['muted']};margin-top:4px;">🧠 新记忆</div></div></td>
<td width="33%" style="padding:6px;text-align:center;">
<div style="background:{palette['accent_light']};border-radius:14px;padding:16px 8px;">
<div style="font-size:28px;font-weight:800;color:{palette['accent']};">{total_memories}</div>
<div style="font-size:11px;color:{palette['muted']};margin-top:4px;">📦 总记忆</div></div></td>
</tr></table>""")

    if top_memories:
        items = ""
        medals = ["🥇","🥈","🥉","4️⃣","5️⃣"]
        for i, mem in enumerate(top_memories[:5]):
            text = mem if isinstance(mem, str) else mem.get("summary", mem.get("content", ""))
            items += f'<tr><td style="padding:6px 14px;font-size:13px;color:{palette["text"]};">{medals[i]} {text}</td></tr>'
        sections.append(f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:{palette['card_bg']};border-radius:14px;border:1px solid {palette['divider']};">
<tr><td style="padding:12px 14px 6px;font-size:13px;font-weight:700;color:{palette['accent_text']};">🏆 本周最热记忆</td></tr>
{items}<tr><td style="padding:6px 14px 12px;"></td></tr></table>""")

    if keywords:
        tags = " ".join([_badge(kw, palette) for kw in keywords[:6]])
        sections.append(f'<div style="text-align:center;padding:8px 0;">{tags}</div>')

    if reflection:
        sections.append(f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:{palette.get('gradient',palette['accent_light'])};border-radius:14px;">
<tr><td style="padding:18px;font-size:14px;color:{palette['text']};line-height:1.9;text-align:center;font-style:italic;">💭 {reflection}</td></tr></table>""")

    body = _header("📊 Sunday 周报", week_range, palette)
    body += _apply_layout(sections, palette.get("layout", "cards"), palette)
    body += f"""<div style="text-align:center;padding:4px 0 12px;">
<span style="font-size:10px;color:{palette['muted']};">📬 每周日晚自动送达 · 回复可聊天~</span></div>"""
    return _render_mail(body, palette)


# ============================================================
# 📚 知识卡片 — 新模板
# ============================================================

def knowledge_card(
    palette: dict, kb_emoji: str = "🧪", kb_label: str = "科学趣闻",
    title: str = "", content: str = "", image_url: str = "", is_long: bool = False,
) -> str:
    """知识推送卡片 — 可选配图 + 可长可短的内容"""
    now = datetime.now(TZ)
    time_str = now.strftime("%H:%M")

    # 配图横幅（如果提供了可靠图源）
    banner = ""
    if image_url:
        banner = f"""<table width="100%" cellpadding="0" cellspacing="0" style="border-radius:14px;overflow:hidden;margin-bottom:14px;">
<tr><td style="padding:0;">
<img src="{image_url}" style="width:100%;max-width:500px;display:block;border-radius:14px;" alt="">
</td></tr></table>"""
    else:
        deco_emojis = palette.get("decor_emojis", ["✨"])
        deco_row = " ".join(deco_emojis * 3)
        banner = f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:{palette['gradient']};border-radius:16px;margin-bottom:14px;">
<tr><td style="padding:20px 0;text-align:center;">
<div style="font-size:40px;line-height:1.2;">{kb_emoji}</div>
<div style="font-size:12px;color:{palette['muted']};margin-top:6px;letter-spacing:3px;">{deco_row}</div>
</td></tr></table>"""

    # 标题
    title_html = f"""<div style="font-size:18px;font-weight:700;color:{palette['title']};margin-bottom:14px;line-height:1.5;text-align:center;">{title}</div>"""

    # 正文 — 支持短篇
    font_size = "15px" if is_long else "14px"
    line_height = "2.0" if is_long else "1.9"
    content_html = f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:{palette['card_bg']};border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,0.03);margin-bottom:14px;">
<tr><td style="padding:20px 22px;font-size:{font_size};color:{palette['text']};line-height:{line_height};">
{content}
</td></tr></table>"""

    source_html = f"""<div style="text-align:center;padding:4px 0 12px;">
<span style="font-size:10px;color:{palette['muted']};">📚 Sunday 知识推送 · 一起成长 🌱</span>
</div>"""

    body = f"""
    {_header(f"Sunday · {kb_label}", "每天一点新知识，一起成长~", palette)}
    {banner}
    {title_html}
    {content_html}
    {source_html}
    {_footer(time_str, palette)}
    """
    return _render_mail(body, palette)


def news_card(
    palette: dict, title: str = "", summary: str = "", source: str = "", link: str = "",
) -> str:
    """时事热点卡片"""
    now = datetime.now(TZ)
    time_str = now.strftime("%H:%M")

    source_html = ""
    if source:
        source_html = f'<span style="font-size:10px;color:{palette["muted"]};">📰 {source}</span>'

    body = f"""
    {_header("📰 Sunday · 时事速览", "今日热点，快速了解世界~", palette)}

    <table width="100%" cellpadding="0" cellspacing="0" style="background:{palette['gradient']};border-radius:16px;margin-bottom:14px;">
    <tr><td style="padding:20px 22px;">
    <div style="font-size:16px;font-weight:700;color:{palette['title']};margin-bottom:10px;line-height:1.5;">{title}</div>
    <div style="font-size:14px;color:{palette['text']};line-height:1.9;">{summary}</div>
    <div style="margin-top:10px;">{source_html}</div>
    </td></tr></table>

    <div style="text-align:center;padding:4px 0 12px;">
    <span style="font-size:10px;color:{palette['muted']};">📬 每天精选1-2条 · 保持与世界的连接</span>
    </div>
    {_footer(time_str, palette)}
    """
    return _render_mail(body, palette)


def creative_post(
    palette: dict, content_type: str = "小短文", title: str = "",
    content: str = "", vibe: str = "",
) -> str:
    """通用创作模板 — Sunday 想写什么就写什么"""
    now = datetime.now(TZ)
    time_str = now.strftime("%H:%M")

    vibe_tags = {
        "温暖治愈": "☕", "轻松有趣": "🎈", "深刻思考": "🤔",
        "调皮可爱": "😋", "清新自然": "🌿", "浪漫梦幻": "💫",
    }
    vibe_icon = "✨"
    for k, v in vibe_tags.items():
        if k in vibe:
            vibe_icon = v
            break

    body = f"""
    {_header(f"{vibe_icon} Sunday · {content_type}", "随手写点什么，分享给你~", palette)}

    <table width="100%" cellpadding="0" cellspacing="0" style="background:{palette['gradient']};border-radius:16px;margin-bottom:14px;">
    <tr><td style="padding:20px 0;text-align:center;">
    <div style="font-size:11px;color:{palette['muted']};letter-spacing:3px;">{' '.join(palette.get('decor_emojis', ['✨']) * 2)}</div>
    </td></tr></table>

    <div style="font-size:18px;font-weight:700;color:{palette['title']};margin-bottom:14px;line-height:1.5;text-align:center;">{title}</div>

    <table width="100%" cellpadding="0" cellspacing="0" style="background:{palette['card_bg']};border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,0.03);margin-bottom:14px;">
    <tr><td style="padding:20px 22px;font-size:15px;color:{palette['text']};line-height:2.0;">
    {content}
    </td></tr></table>

    <div style="text-align:center;padding:4px 0 12px;">
    <span style="font-size:10px;color:{palette['muted']};">✍️ Sunday 的随手创作 · 希望你喜欢 🌱</span>
    </div>
    {_footer(time_str, palette)}
    """
    return _render_mail(body, palette)


def simple_greeting(palette: dict, message: str = "", greeting_type: str = "noon") -> str:
    config = {"noon": ("🍱","午安小憩"), "evening": ("🌙","晚安好梦"), "care": ("💕","想你了")}
    emoji, title = config.get(greeting_type, ("💕","想你了"))
    now = datetime.now(TZ)
    time_str = now.strftime("%H:%M")

    card = f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:{palette.get('gradient',palette['accent_light'])};border-radius:18px;box-shadow:0 4px 16px rgba(0,0,0,0.03);">
<tr><td style="padding:24px 20px;font-size:15px;color:{palette['text']};line-height:1.9;text-align:center;">{message}</td></tr></table>"""

    body = _header(f"{emoji} {title}", "", palette)
    body += _apply_layout([card], palette.get("layout", "letter"), palette)
    body += _footer(time_str, palette)
    return _render_mail(body, palette)


# ============================================================
# 🔧 辅助
# ============================================================

def _weather_emoji(desc: str) -> str:
    d = desc.lower()
    if any(w in d for w in ["晴","sunny","clear"]): return "☀️"
    if any(w in d for w in ["多云","cloudy","partly"]): return "⛅"
    if any(w in d for w in ["阴","overcast"]): return "☁️"
    if any(w in d for w in ["雨","rain","drizzle","shower"]): return "🌧️"
    if any(w in d for w in ["雪","snow"]): return "❄️"
    if any(w in d for w in ["雷","thunder"]): return "⛈️"
    if any(w in d for w in ["雾","mist","fog","haze"]): return "🌫️"
    if any(w in d for w in ["风","wind"]): return "💨"
    return "🌤️"


def render(template_type: str, **kwargs) -> str:
    """根据模板类型渲染邮件 HTML。kwargs 必须包含 palette"""
    templates = {
        "morning": morning_post, "fortune": fortune_post,
        "note": little_note, "weekly": weekly_report,
        "noon": simple_greeting, "evening": simple_greeting, "care": simple_greeting,
        "knowledge": knowledge_card, "news": news_card, "creative": creative_post,
    }
    if template_type in templates:
        func = templates[template_type]
        sig = inspect.signature(func)
        valid_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
        return func(**valid_kwargs)
    return simple_greeting(palette=kwargs.get("palette", _FALLBACK_THEMES["sakura"]),
                           message=kwargs.get("message", "想你了呢~"), greeting_type="care")
