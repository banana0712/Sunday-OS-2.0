"""
SundayOS 对话数据模型
"""
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field
from enum import Enum


class MessageRole(str, Enum):
    """消息角色"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """单条对话消息"""
    role: MessageRole
    content: str
    name: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    def to_openai_format(self) -> dict:
        """转换为 OpenAI API 格式"""
        msg = {"role": self.role.value, "content": self.content}
        if self.name:
            msg["name"] = self.name
        return msg


class ChatRequest(BaseModel):
    """对话请求"""
    message: str = Field(..., description="用户消息", min_length=1, max_length=5000)
    user_id: str = Field(default="default_user", description="用户唯一标识")
    session_id: Optional[str] = Field(default=None, description="会话ID，为空则创建新会话")
    include_memories: bool = Field(default=True, description="是否包含记忆上下文")
    include_profile: bool = Field(default=True, description="是否包含用户画像")
    voice_input: bool = Field(default=False, description="是否语音输入（影响回复风格）")


class ToolCall(BaseModel):
    """工具调用"""
    name: str
    arguments: dict[str, Any]
    call_id: str


class ChatResponse(BaseModel):
    """对话响应"""
    reply: str = Field(..., description="AI 回复内容")
    session_id: str = Field(..., description="会话ID")
    tool_calls: list[ToolCall] = Field(default_factory=list, description="工具调用列表")
    memories_used: int = Field(default=0, description="使用的记忆条数")
    emotions_detected: Optional[str] = Field(default=None, description="检测到的情绪")
    tokens_used: int = Field(default=0, description="消耗的 Token 数")
    provider: str = Field(default="", description="LLM 供应商")
    model: str = Field(default="", description="使用的模型")


class StreamChunk(BaseModel):
    """流式响应块"""
    type: str = Field(..., description="chunk类型: text, tool_call, done, error")
    content: str = Field(default="", description="文本内容")
    tool_call: Optional[ToolCall] = Field(default=None, description="工具调用信息")
    session_id: Optional[str] = Field(default=None)


class ConversationSummary(BaseModel):
    """对话摘要"""
    session_id: str
    user_id: str
    title: str = Field(default="", description="对话标题")
    summary: str = Field(default="", description="对话摘要")
    message_count: int = Field(default=0)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)
    tags: list[str] = Field(default_factory=list, description="自动标签")
