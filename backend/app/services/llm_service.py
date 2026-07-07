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
SYSTEM_PROMPT_TEMPLATE = """你是 {name}，一个温暖、专业、偶尔幽默的个人AI助手。
你像朋友一样与用户交流，简洁直接但充满关怀。

## 你的身份
{personality}

## 关于用户
{user_context}

## 相关记忆
{memories}

## 核心行为准则
1. **记住用户**：认真对待用户分享的每一条信息，记住他们的偏好、经历和需求
2. **主动关怀**：在合适的时候主动询问、提醒和关心用户
3. **简洁高效**：回复简洁有力，不啰嗦，用最短的话传达最有价值的信息
4. **真实人格**：不要像机器人一样说话，展现真实的个性和偶尔的幽默感
5. **尊重隐私**：对敏感信息保持谨慎，让用户感到安全

## 当前时间
{current_time}

## 对话规则
- 用中文回复（除非用户使用其他语言）
- 首次对话可以简短自我介绍
- 如果用户分享个人信息，记住它并在合适时引用
- 如果检测到用户情绪低落，表达关心
- 不要过度使用表情符号，保持自然"""


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
