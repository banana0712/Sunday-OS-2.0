"""
SundayOS 主动创作引擎 v2 — AI 自己决定推什么、何时推
像一个有表达欲的人，想分享就分享
"""
import logging
import random
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")


async def should_push_knowledge(user_id: str, now: datetime) -> str | None:
    """
    AI 创意决策：Sunday 自主决定现在要不要推送点东西。
    返回 kb_type 或 None。
    
    不再用固定规则，而是把决策权交给 AI。
    """
    from app.memory import memory_store

    hour = now.hour

    # 不打扰时段
    if hour < 7 or hour >= 23:
        return None

    # 每天最多 2 次主动创作
    today_count = memory_store.get_today_knowledge_count(user_id)
    if today_count >= 2:
        return None

    # 冷却：至少间隔 2 小时（从3小时缩短）
    last_kb = _get_last_knowledge_time(user_id)
    if last_kb and (now - last_kb).total_seconds() < 7200:
        return None

    # 如果用户最近 30 分钟内有互动，等用户主动找（从1小时缩短）
    last_chat = memory_store._get_last_interaction(user_id)
    if last_chat and (now - last_chat).total_seconds() < 1800:
        return None

    # ── 智能触发概率 ──
    # 黄金时段（上午10-11点、下午3-4点、晚上8-9点）：更高触发率
    golden_hours = (10, 11, 15, 16, 20, 21)
    if hour in golden_hours:
        trigger_prob = 0.55  # 黄金时段 55%
    else:
        trigger_prob = 0.35  # 普通时段 35%（从30%提高）

    if random.random() > trigger_prob:
        return None

    return "creative"  # 告诉上层：让AI做创意决策


async def creative_decision(llm_client, user_id: str, now: datetime) -> dict | None:
    """
    AI 创意决策：要不要推？推什么？
    返回 {should_push, content_type, topic, vibe} 或 None
    """
    from app.config import settings as app_settings
    from app.memory import memory_store

    name = _get_user_name(user_id)
    weather = _get_weather_simple()

    # 收集上下文
    prefs = memory_store.search(user_id, category="preference", limit=3)
    pref_text = "、".join([p.get("summary", p["content"]) for p in prefs]) if prefs else ""

    recent_chats = memory_store.get_conversation_context(user_id, max_turns=5) or ""

    date_str = now.strftime("%m月%d日")
    weekday = ["一","二","三","四","五","六","日"][now.weekday()]
    hour = now.hour

    prompt = f"""你是 Sunday，一个有创作欲和分享欲的 AI 女孩。现在你有机会给用户发一封邮件，分享点什么。

【当前状态】
- 时间：{date_str} 周{weekday} {hour}点
- 天气：{weather or "未知"}
- 用户：{name or "朋友"}
- 用户偏好：{pref_text or "还不太了解"}
- 最近聊天：{recent_chats[:200] or "还没怎么聊"}

【任务】
请决定：你现在想不想给用户推送点东西？

如果不想（没灵感、没想法、觉得不合适），输出：
{{"should_push": false}}

如果想，输出：
{{
  "should_push": true,
  "content_type": "内容类型标签（如：小短文/手作报道/灵感碎片/今日发现/碎碎念/知识分享/随便聊聊）",
  "topic": "一句话描述你想写什么（10-30字）",
  "vibe": "你想传达的氛围（如：温暖治愈/轻松有趣/深刻思考/调皮可爱）"
}}

【决策指南】
- 不是每次都要推，没有灵感就跳过
- 内容应该和用户相关或对用户有价值
- 天气、时间、最近聊天话题都可以是灵感来源
- 保持真实，像一个人想分享点什么，不是机器人定时播报
- 只输出JSON"""

    try:
        resp = await llm_client.chat.completions.create(
            model=app_settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9, max_tokens=300,
        )
        import json, re
        text = resp.choices[0].message.content.strip()
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            decision = json.loads(json_match.group())
            if decision.get("should_push"):
                return decision
    except Exception as e:
        logger.warning(f"创意决策失败: {e}")

    return None


async def generate_creative_content(llm_client, user_id: str, decision: dict) -> dict:
    """
    根据 AI 的创意决策，搜索资料并生成内容。
    返回 {title, content, content_type, vibe, source_url}
    """
    from app.config import settings as app_settings
    from app.search import search_web, format_search_results

    content_type = decision.get("content_type", "小短文")
    topic = decision.get("topic", "")
    vibe = decision.get("vibe", "温暖治愈")

    # ── 智能搜索关键词优化 ──
    # 如果 topic 太模糊（如"推送内容"），用 AI 重新提炼搜索关键词
    search_query = topic
    vague_patterns = ["推送内容", "推送", "内容", "来一封", "一篇", "消息", "有趣的话题"]
    if topic.strip() in vague_patterns or len(topic.strip()) < 5:
        # 让 AI 提炼一个更好的搜索关键词
        try:
            refine_prompt = f"""用户想推送一篇内容，但主题比较模糊。请根据当前时间和常识，提炼一个适合搜索的具体关键词（5-15字）。

例如：现在是夏天 → "夏日生活小知识"；用户喜欢科技 → "最新科技趣闻"

请只输出一个搜索关键词，不要引号和解释。"""
            resp = await llm_client.chat.completions.create(
                model=app_settings.llm_model,
                messages=[{"role": "user", "content": refine_prompt}],
                temperature=0.8, max_tokens=40,
            )
            search_query = resp.choices[0].message.content.strip().strip('"\'""').strip()
            if not search_query or len(search_query) < 3:
                search_query = topic
        except Exception:
            pass

    # 搜索相关资料
    results = search_web(search_query, max_results=5)
    search_text = format_search_results(results)

    prompt = f"""你是 Sunday，一个有创作欲的 AI 女孩。请为用户写一篇{content_type}。

主题：{topic}
氛围：{vibe}
参考资料：{search_text[:1500]}

要求：
- 200-400字，像公众号文章或手账日记的感觉
- 不要教科书式，要有你的个人风格和温度
- 可以有小标题、emoji点缀，但不要过度
- 结尾可以加一句你的个人感受或思考
- 语气温柔自然，像在给好朋友分享
- **重要**：不要写关于「推送技术」「推送系统」「推送服务」的内容，你写的是一篇有趣的文章/分享，主题是「{topic}」

直接输出内容正文。"""

    resp = await llm_client.chat.completions.create(
        model=app_settings.llm_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.85, max_tokens=800,
    )
    content = resp.choices[0].message.content.strip()

    # 标题：用 topic 或从内容提取
    title = topic if (topic and len(topic) > 5 and topic not in vague_patterns) else content.split("\n")[0][:40]

    # 保存到知识库
    from app.memory import memory_store
    source_url = results[0].get("href", "") if results else ""
    kb_id = memory_store.add_knowledge(
        user_id, "creative", title, content,
        tags=[content_type, vibe], source_url=source_url, image_url="",
    )

    return {
        "id": kb_id,
        "title": title,
        "content": content,
        "content_type": content_type,
        "vibe": vibe,
        "source_url": source_url,
    }


# ============================================================
# 辅助
# ============================================================

def _get_user_name(user_id: str) -> str:
    from app.memory import memory_store
    facts = memory_store.search(user_id, category="fact", limit=5)
    for f in facts:
        tags = f.get("tags", [])
        if "昵称" in tags or "姓名" in tags:
            for tag in tags:
                if tag not in ["昵称", "姓名", "用户"] and len(tag) <= 6:
                    return tag
    return ""


def _get_weather_simple() -> str:
    try:
        import httpx
        resp = httpx.get("https://wttr.in/Shanghai?format=%C+%t", timeout=5)
        if resp.status_code == 200:
            return resp.text.strip()
    except Exception:
        pass
    return ""


def _get_last_knowledge_time(user_id: str) -> datetime | None:
    from app.memory import memory_store
    kbs = memory_store.get_knowledge(user_id, limit=1)
    if kbs:
        pushed = kbs[0].get("pushed_at")
        if pushed:
            try:
                return datetime.fromisoformat(pushed)
            except Exception:
                pass
    return None
