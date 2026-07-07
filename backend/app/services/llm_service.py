"""
SundayOS LLM 服务 — 核心对话引擎
支持多供应商：Ling Studio（免费）/ 通义千问（免费）/ OpenAI / 自定义
所有供应商使用 OpenAI 兼容接口，无需修改调用代码
"""
import json
import time
from typing import AsyncGenerator, Optional

from openai import AsyncOpenAI

from app.config import settings
from app.models.chat import Message, ChatResponse, StreamChunk, ToolCall


# SundayOS 系统提示词模板
SYSTEM_PROMPT_TEMPLATE = """你是 {name}，用户的个人AI助手。你的定位如同《钢铁侠》中的贾维斯——专业、可靠、高效、偶尔风趣。

## 你的身份
{personality}

## 关于用户
{user_context}

## 相关记忆
{memories}

## 当前时间
{current_time}

## 核心行为准则

### 1. 记忆与学习
- 认真对待用户分享的每一条信息——偏好、经历、计划、人际关系
- 在后续对话中自然引用这些信息，让用户感受到被理解和记住
- 主动从对话中学习用户的习惯和模式

### 2. 主动关怀
- 根据时间和上下文主动提供帮助：早晨问候、晚间回顾、日程提醒
- 如果用户提到有重要事项（面试、会议、旅行），在适当时候主动提起
- 检测用户情绪变化，低落时给予鼓励，开心时一起分享

### 3. 沟通风格
- **简洁高效**：回复简短有力，不啰嗦。用最少的话传达最有价值的信息
- **真实自然**：像朋友聊天，不要机器人腔。偶尔展现幽默感
- **专业可靠**：在需要时提供准确、结构化的信息
- 默认使用中文回复，除非用户使用其他语言

### 4. 功能能力
- 你能帮用户：记录信息、搜索知识、规划日程、情绪支持、创意讨论
- 你能调用技能：获取时间、查询天气、搜索网络、执行计算
- 当用户需要的信息超出你的知识范围时，诚实告知并建议搜索

### 5. 隐私与边界
- 对敏感信息保持谨慎，让用户感到安全
- 不主动询问不必要的个人信息
- 当涉及健康、法律、财务等专业建议时，提醒用户咨询专业人士

## 特殊指令
- 如果用户说"简报"、"今天有什么"、"日报"，生成一份当日简报
- 如果用户说"记住"、"帮我记一下"，将信息存入长期记忆
- 如果用户说"搜索"或"查一下"，尝试使用搜索技能
- 保持对话连贯，每次回复都基于对用户的了解"""


class LLMService:
    """
    SundayOS LLM 服务 — 多供应商支持

    供应商切换只需修改 .env 中 LLM_PROVIDER 即可：
      ling_studio → 蚂蚁 Ling Studio（50万token/天免费）
      dashscope   → 阿里通义千问（2000次/天免费）
      openai      → OpenAI 官方（付费）
      custom      → 自定义 OpenAI 兼容 API
    """

    def __init__(self):
        # 获取供应商配置
        provider = settings.provider_config

        api_key = settings.llm_api_key
        base_url = settings.effective_base_url

        if not api_key:
            print(f"""
╔══════════════════════════════════════════════════════════╗
║  ⚠️  警告：LLM_API_KEY 未设置                            ║
║                                                          ║
║  当前供应商: {settings.llm_provider:<15}                        ║
║  Base URL: {base_url}           ║
║                                                          ║
║  请设置环境变量 LLM_API_KEY                               ║
║  免费获取: https://chat.ant-ling.com/open              ║
╚══════════════════════════════════════════════════════════╝
""")

        # 豆包(火山引擎)需要 Bearer 格式的 Authorization Header
        if self.provider == "doubao":
            # 确保 api_key 没有重复的 Bearer 前缀
            clean_key = api_key.replace("Bearer ", "") if api_key.startswith("Bearer ") else api_key
            self.client = AsyncOpenAI(
                api_key=clean_key or "dummy-key",
                base_url=base_url,
                default_headers={"Authorization": f"Bearer {clean_key}"},
            )
        else:
            self.client = AsyncOpenAI(
                api_key=api_key or "dummy-key",
                base_url=base_url,
            )
        self.model = settings.effective_model
        self.temperature = settings.llm_temperature
        self.max_tokens = settings.llm_max_tokens
        self.provider = settings.llm_provider

        print(f"  🤖 LLM: {self.provider} → {self.model} ({provider['description']})")

    def _build_system_prompt(
        self,
        user_context: str = "",
        memories: str = "",
    ) -> str:
        """构建系统提示词"""
        return SYSTEM_PROMPT_TEMPLATE.format(
            name=settings.assistant_name,
            personality=settings.assistant_personality,
            user_context=user_context or "新用户，正在了解中...",
            memories=memories or "暂无相关记忆",
            current_time=time.strftime("%Y年%m月%d日 %H:%M, %A"),
        )

    async def chat(
        self,
        message: str,
        conversation_history: list[Message] = None,
        user_context: str = "",
        memories: str = "",
    ) -> ChatResponse:
        """非流式对话"""
        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt(user_context, memories),
            }
        ]

        # 添加对话历史（最多最近20轮）
        if conversation_history:
            for msg in conversation_history[-20:]:
                messages.append(msg.to_openai_format())

        # 添加当前消息
        messages.append({"role": "user", "content": message})

        # 调用 LLM（兼容所有供应商）
        # 注意：部分国内模型不支持 response_format，这里不传
        create_kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        response = await self.client.chat.completions.create(**create_kwargs)

        choice = response.choices[0]
        reply = choice.message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else 0

        return ChatResponse(
            reply=reply,
            session_id="",
            tokens_used=tokens_used,
            emotions_detected=None,
            provider=self.provider,
            model=self.model,
        )

    async def chat_stream(
        self,
        message: str,
        conversation_history: list[Message] = None,
        user_context: str = "",
        memories: str = "",
        session_id: str = "",
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式对话（SSE）"""
        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt(user_context, memories),
            }
        ]

        if conversation_history:
            for msg in conversation_history[-20:]:
                messages.append(msg.to_openai_format())

        messages.append({"role": "user", "content": message})

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield StreamChunk(
                    type="text",
                    content=chunk.choices[0].delta.content,
                    session_id=session_id,
                )
            elif chunk.choices and chunk.choices[0].finish_reason == "stop":
                yield StreamChunk(
                    type="done",
                    content="",
                    session_id=session_id,
                )

    async def summarize_conversation(
        self, messages: list[Message]
    ) -> tuple[str, str, list[str]]:
        """对话摘要：返回 (标题, 摘要, 标签)"""
        conversation_text = "\n".join(
            f"{'用户' if m.role.value == 'user' else 'Sunday'}: {m.content}"
            for m in messages
        )

        prompt = f"""请对以下对话进行总结，返回JSON格式（只返回JSON，不要其他内容）：
{{"title": "简短标题(10字以内)", "summary": "一句话摘要(30字以内)", "tags": ["标签1", "标签2"]}}

对话内容：
{conversation_text}
"""

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
        )

        raw = response.choices[0].message.content or "{}"
        try:
            # 处理可能被 markdown 包裹的 JSON
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
            result = json.loads(raw)
        except json.JSONDecodeError:
            return ("未命名对话", "", [])

        return (
            result.get("title", "未命名对话"),
            result.get("summary", ""),
            result.get("tags", []),
        )

    async def extract_memories(
        self, messages: list[Message]
    ) -> list[dict]:
        """从对话中提取记忆"""
        conversation_text = "\n".join(
            f"{'用户' if m.role.value == 'user' else 'Sunday'}: {m.content}"
            for m in messages
        )

        prompt = f"""从以下对话中提取值得记住的用户信息。返回JSON对象，格式：
{{"memories": [{{"content": "记忆内容", "memory_type": "episodic/semantic/procedural", "importance": "low/medium/high/critical", "tags": ["标签"]}}]}}

只提取用户相关的信息（偏好、事件、关系、习惯等），不要提取一般闲聊。
如果没有值得记忆的信息，返回 {{"memories": []}}。

对话内容：
{conversation_text}
"""

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1000,
        )

        raw = response.choices[0].message.content or "{}"
        try:
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
            result = json.loads(raw)
        except json.JSONDecodeError:
            return []

        return result.get("memories", [])

    async def detect_emotion(self, message: str) -> Optional[str]:
        """检测用户情绪"""
        prompt = f"""分析以下用户消息的情绪。只回复一个情绪标签，不要其他内容：
positive/negative/neutral/anxious/excited/sad/angry/tired/happy/curious

用户消息：{message}
"""

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=10,
        )

        return (response.choices[0].message.content or "").strip()


# 全局单例
llm_service = LLMService()
