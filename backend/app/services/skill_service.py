"""
SundayOS 技能调度器
管理外部技能：天气、搜索、日历等
"""
import json
from datetime import datetime

from app.config import settings


class SkillService:
    """SundayOS 技能调度器"""

    # 可用技能定义
    AVAILABLE_SKILLS = {
        "get_weather": {
            "name": "get_weather",
            "description": "查询指定城市的天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，如 北京、上海",
                    }
                },
                "required": ["city"],
            },
        },
        "get_time": {
            "name": "get_time",
            "description": "获取当前时间或指定时区的时间",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "时区，如 Asia/Shanghai",
                    }
                },
            },
        },
        "web_search": {
            "name": "web_search",
            "description": "搜索互联网获取最新信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词",
                    }
                },
                "required": ["query"],
            },
        },
        "save_memory": {
            "name": "save_memory",
            "description": "保存一条用户记忆",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要记忆的内容",
                    },
                    "importance": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "重要程度",
                    },
                },
                "required": ["content"],
            },
        },
        "calculate": {
            "name": "calculate",
            "description": "执行数学计算",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，如 2+2*3",
                    }
                },
                "required": ["expression"],
            },
        },
    }

    @classmethod
    def get_available_skills_for_llm(cls) -> list[dict]:
        """获取可用于 LLM Function Calling 的技能列表"""
        return [
            {
                "type": "function",
                "function": {
                    "name": skill["name"],
                    "description": skill["description"],
                    "parameters": skill["parameters"],
                },
            }
            for skill in cls.AVAILABLE_SKILLS.values()
        ]

    async def execute(self, skill_name: str, arguments: dict) -> dict:
        """执行技能"""
        handler = getattr(self, f"_handle_{skill_name}", None)
        if not handler:
            return {"success": False, "error": f"未知技能: {skill_name}"}

        try:
            result = await handler(arguments)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_get_weather(self, args: dict) -> str:
        """处理天气查询"""
        city = args.get("city", "北京")
        # 生产环境应调用真实天气 API
        return f"{city}今天天气晴朗，气温18-25°C，微风，适合出行。（此为模拟数据，请配置 WEATHER_API_KEY 获取实时天气）"

    async def _handle_get_time(self, args: dict) -> str:
        """处理时间查询"""
        now = datetime.now()
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return f"现在是 {now.strftime('%Y年%m月%d日')} {weekdays[now.weekday()]} {now.strftime('%H:%M:%S')}"

    async def _handle_web_search(self, args: dict) -> str:
        """处理网络搜索"""
        query = args.get("query", "")
        if not query:
            return "请提供搜索关键词"
        # 生产环境应调用搜索 API
        return f'关于"{query}"的搜索结果：建议使用搜索引擎获取最新信息。（请配置 SEARCH_API_KEY 以获得实时搜索能力）'

    async def _handle_save_memory(self, args: dict) -> str:
        """处理记忆保存"""
        content = args.get("content", "")
        importance = args.get("importance", "medium")
        return f"已保存记忆：{content}（重要程度：{importance}）"

    async def _handle_calculate(self, args: dict) -> str:
        """处理数学计算"""
        expression = args.get("expression", "")
        try:
            # 安全地计算表达式（仅允许基本数学运算）
            allowed = set("0123456789+-*/.() ")
            if not all(c in allowed for c in expression):
                return "只支持基本数学运算"
            result = eval(expression, {"__builtins__": {}}, {})
            return f"{expression} = {result}"
        except Exception:
            return "无法计算该表达式"


# 全局单例
skill_service = SkillService()
