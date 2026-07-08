"""
SundayOS 知识推送引擎
- 决策何时推送什么类型的知识
- LLM 搜索 + 生成知识点
- 知识卡片内容生成
"""
import logging
import random
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")

# 推送类型
KB_TYPES = {
    "science_fact": {"emoji": "🧪", "label": "科学趣闻", "desc": "最新科研发现或有趣的科学冷知识"},
    "daily_word":   {"emoji": "📚", "label": "今日词条", "desc": "一个有趣概念的精简解释"},
    "thought":      {"emoji": "💡", "label": "思维火花", "desc": "一个引人思考的问题或独特视角"},
    "inspiration":  {"emoji": "🎨", "label": "灵感碎片", "desc": "创意、设计、艺术类小知识"},
    "news_brief":   {"emoji": "📰", "label": "时事速览", "desc": "今日热点新闻精简摘要"},
}


async def should_push_knowledge(user_id: str, now: datetime) -> str | None:
    """
    判断现在是否应该推送知识。
    返回 kb_type 或 None。
    
    规则：
    - 每天最多 2 条
    - 早晨(8-10)优先科学趣闻/今日词条
    - 晚间(19-22)优先思维火花
    - 周末优先灵感碎片
    - 不打扰时段(23-7)不推送
    """
    from app.memory import memory_store

    hour = now.hour
    weekday = now.weekday()
    is_weekend = weekday >= 5

    # 不打扰时段
    if hour < 7 or hour >= 23:
        return None

    # 每天上限
    today_count = memory_store.get_today_knowledge_count(user_id)
    if today_count >= 2:
        return None

    # 冷却：至少间隔 3 小时
    last_kb = _get_last_knowledge_time(user_id)
    if last_kb and (now - last_kb).total_seconds() < 10800:
        return None

    # 根据时段选择类型
    if 8 <= hour <= 10:
        candidates = ["news_brief", "science_fact", "daily_word"]  # 早晨加新闻
    elif 12 <= hour <= 14:
        candidates = ["news_brief", "science_fact"]
    elif 19 <= hour <= 22:
        candidates = ["thought", "science_fact", "news_brief"]
    elif is_weekend:
        candidates = ["inspiration", "science_fact", "thought"]
    else:
        candidates = ["science_fact", "daily_word", "thought", "news_brief"]

    # 随机选一种（但不要重复今天的类型）
    today_types = _get_today_types(user_id)
    available = [c for c in candidates if c not in today_types]
    if not available:
        available = candidates

    return random.choice(available)


async def generate_knowledge(llm_client, user_id: str, kb_type: str) -> dict:
    """
    LLM 搜索 + 生成知识点（可长可短，有阅读价值的小短篇）。
    返回 {title, content, tags, source_url, is_long}
    """
    from app.config import settings as app_settings
    from app.search import search_web, format_search_results

    cfg = KB_TYPES.get(kb_type, KB_TYPES["science_fact"])
    model = app_settings.llm_model

    # 搜索相关话题
    search_query = _search_query_for_type(kb_type)
    results = search_web(search_query, max_results=5)
    search_text = format_search_results(results)

    # 根据类型决定内容长度
    is_long = kb_type in ("science_fact", "thought", "news_brief")
    length_guide = "200-400字，可以是一个有深度的小短篇" if is_long else "100-200字，精炼有趣"

    prompt = f"""你是一个知识渊博又有趣的分享者。请生成一条知识内容。

类型：{cfg['label']} — {cfg['desc']}

参考资料：
{search_text[:1500]}

请输出 JSON：
{{
  "title": "标题（10-25字，吸引人，让人想读下去）",
  "content": "正文（{length_guide}，自然流畅，像在给好朋友分享一个有趣的知识。可以有小标题分段，但不要太多。结尾可以加一句个人感受或思考问题）",
  "tags": ["2-3个标签"],
  "source": "信息来源简述（如：Nature期刊 / BBC News / 知乎）"
}}

要求：
- 内容有实质信息量，读完后能学到东西
- 语气轻松但不轻浮，像优质公众号文章的感觉
- 如果是新闻类，要有时效性和准确性
- 只输出 JSON"""

    resp = await llm_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.85, max_tokens=800,  # 支持更长输出
    )

    import json, re
    text = resp.choices[0].message.content.strip()
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        data = json.loads(json_match.group())
    else:
        data = {
            "title": "今日小知识",
            "content": "世界充满了有趣的事情，保持好奇心哦~ ✨",
            "tags": ["知识", "趣味"],
            "source": "Sunday",
        }

    # 保存到知识库（不再依赖外部图片 URL）
    from app.memory import memory_store
    source_url = results[0].get("href", "") if results else ""

    kb_id = memory_store.add_knowledge(
        user_id, kb_type, data["title"], data["content"],
        tags=data.get("tags", []), source_url=source_url, image_url="",
    )

    return {
        "id": kb_id,
        "type": kb_type,
        "emoji": cfg["emoji"],
        "label": cfg["label"],
        "title": data["title"],
        "content": data["content"],
        "tags": data.get("tags", []),
        "source": data.get("source", ""),
        "source_url": source_url,
        "is_long": is_long,
    }


def _search_query_for_type(kb_type: str) -> str:
    queries = {
        "science_fact": "interesting science discovery news 2025 2026",
        "daily_word": "interesting concept word explained simply",
        "thought": "thought provoking question philosophy science",
        "inspiration": "creative art design inspiration interesting",
        "news_brief": "top news today world technology science 2026",
    }
    return queries.get(kb_type, queries["science_fact"])


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


def _get_today_types(user_id: str) -> list:
    from app.memory import memory_store
    kbs = memory_store.get_knowledge(user_id, limit=5)
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    types = []
    for kb in kbs:
        pushed = kb.get("pushed_at", "")
        if pushed and pushed.startswith(today):
            types.append(kb.get("kb_type", ""))
    return types
