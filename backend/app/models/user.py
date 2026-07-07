"""
SundayOS 用户画像数据模型
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class PersonalInfo(BaseModel):
    """个人信息"""
    name: str = Field(default="", description="用户称呼")
    preferred_name: str = Field(default="", description="偏好称呼")
    timezone: str = Field(default="Asia/Shanghai")
    language: str = Field(default="zh-CN")
    occupation: str = Field(default="")
    birthday: Optional[str] = None


class Interest(BaseModel):
    """兴趣爱好"""
    category: str = Field(..., description="兴趣类别")
    name: str = Field(..., description="兴趣名称")
    level: float = Field(default=0.5, description="兴趣程度 0-1")
    last_mentioned: datetime = Field(default_factory=datetime.utcnow)


class Routine(BaseModel):
    """日常规律"""
    weekday: int = Field(..., ge=0, le=6, description="星期几 (0=周一)")
    wake_up_time: Optional[str] = None
    commute_time: Optional[str] = None
    work_start: Optional[str] = None
    work_end: Optional[str] = None
    sleep_time: Optional[str] = None
    habits: list[str] = Field(default_factory=list, description="日常习惯")


class Relationship(BaseModel):
    """人际关系"""
    name: str
    relation: str = Field(..., description="关系类型")
    importance: float = Field(default=0.5, description="重要程度 0-1")
    notes: str = Field(default="", description="备注")
    last_interaction: Optional[datetime] = None


class Preference(BaseModel):
    """用户偏好"""
    reply_style: str = Field(default="concise", description="回复风格: concise/detailed/casual")
    proactive_level: float = Field(default=0.5, description="主动程度 0-1")
    humor_level: float = Field(default=0.5, description="幽默程度 0-1")
    privacy_boundary: str = Field(default="moderate", description="隐私边界: low/moderate/high")
    voice_speed: str = Field(default="normal", description="语速偏好")


class UserProfile(BaseModel):
    """用户完整画像"""
    user_id: str
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    interests: list[Interest] = Field(default_factory=list)
    routines: list[Routine] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    preferences: Preference = Field(default_factory=Preference)
    knowledge_domains: list[str] = Field(default_factory=list, description="知识领域")
    frequent_locations: list[str] = Field(default_factory=list, description="常去地点")
    common_tools: list[str] = Field(default_factory=list, description="常用工具/应用")
    conversation_style_notes: str = Field(default="", description="对话风格备注")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    interaction_count: int = Field(default=0)

    def to_system_context(self) -> str:
        """转换为系统提示上下文"""
        parts = []
        if self.personal_info.name:
            parts.append(f"用户称呼：{self.personal_info.preferred_name or self.personal_info.name}")
        if self.personal_info.occupation:
            parts.append(f"职业：{self.personal_info.occupation}")
        if self.interests:
            interests_str = "、".join(
                f"{i.name}({i.category})" for i in sorted(self.interests, key=lambda x: -x.level)[:5]
            )
            parts.append(f"兴趣爱好：{interests_str}")
        if self.preferences.reply_style:
            parts.append(f"偏好回复风格：{self.preferences.reply_style}")
        if self.knowledge_domains:
            parts.append(f"关注领域：{'、'.join(self.knowledge_domains[:5])}")
        if self.conversation_style_notes:
            parts.append(f"对话风格备注：{self.conversation_style_notes}")
        return "\n".join(parts)
