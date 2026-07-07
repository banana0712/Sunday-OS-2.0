"""
SundayOS 网络搜索模块 — 实时信息收集与智能整理
"""
from ddgs import DDGS


async def search_web(query: str, max_results: int = 5) -> list[dict]:
    """执行网络搜索，返回结果列表"""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return [
                {
                    "title": r.get("title", ""),
                    "body": r.get("body", ""),
                    "href": r.get("href", ""),
                }
                for r in results
            ]
    except Exception as e:
        return [{"title": "搜索失败", "body": str(e), "href": ""}]


def format_search_results(results: list[dict]) -> str:
    """将搜索结果格式化为 LLM 可读的文本"""
    if not results:
        return "未找到相关结果。"

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "无标题")
        body = r.get("body", "")
        href = r.get("href", "")
        lines.append(f"{i}. **{title}**\n   {body[:200]}\n   来源: {href}")

    return "\n\n".join(lines)


# 搜索触发关键词
SEARCH_TRIGGERS = [
    "搜索", "查一下", "帮我查", "查查", "查找",
    "最新", "新闻", "热点", "时事", "最近发生",
    "什么是", "是谁", "怎么去", "多少钱", "天气",
    "股价", "股票", "汇率", "排名", "排行榜",
]


def should_search(message: str) -> bool:
    """判断消息是否需要联网搜索"""
    msg_lower = message.lower()
    for kw in SEARCH_TRIGGERS:
        if kw in msg_lower:
            return True
    return False
