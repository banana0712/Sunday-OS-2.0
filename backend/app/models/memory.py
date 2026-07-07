"""
SundayOS 记忆系统数据模型
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


class MemoryType(str, Enum):
    """记忆类型"""
    EPISODIC = "episodic"       # 情景记忆：具体事件
    SEMANTIC = "semantic"       # 语义记忆：知识、偏好
    PROCEDURAL = "procedural"   # 程序性记忆：工作流、习惯
    WORKING = "working"         # 工作记忆：当前对话上下文


class MemoryImportance(str, Enum):
    """记忆重要程度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Memory(BaseModel):
    """记忆条目"""
    memory_id: Optional[str] = None
    user_id: str
    content: str = Field(..., description="记忆内容")
    memory_type: MemoryType = Field(default=MemoryType.EPISODIC)
    importance: MemoryImportance = Field(default=MemoryImportance.MEDIUM)
    tags: list[str] = Field(default_factory=list)
    source: str = Field(default="conversation", description="记忆来源")
    related_entities: list[str] = Field(default_factory=list, description="相关实体")
    embedding: Optional[list[float]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_accessed: datetime = Field(default_factory=datetime.utcnow)
    access_count: int = Field(default=0)
    decay_factor: float = Field(default=1.0, description="衰减因子 (0-1)")
    session_id: Optional[str] = None

    def effective_importance(self) -> float:
        """计算有效重要度（考虑衰减）"""
        days_since = (datetime.utcnow() - self.created_at).days
        decay = self.decay_factor ** (days_since / 30)  # 30天半衰期
        importance_score = {
            MemoryImportance.LOW: 0.25,
            MemoryImportance.MEDIUM: 0.5,
            MemoryImportance.HIGH: 0.75,
            MemoryImportance.CRITICAL: 1.0,
        }[self.importance]
        return importance_score * decay * (1 + 0.1 * min(self.access_count, 10))


class MemorySearchRequest(BaseModel):
    """记忆搜索请求"""
    user_id: str
    query: str = Field(..., description="搜索查询")
    memory_types: list[MemoryType] = Field(default_factory=lambda: list(MemoryType))
    limit: int = Field(default=10, ge=1, le=50)
    min_importance: Optional[MemoryImportance] = None
    time_range_days: Optional[int] = Field(default=None, description="时间范围（天）")


class MemorySearchResult(BaseModel):
    """记忆搜索结果"""
    memory: Memory
    relevance_score: float = Field(..., description="相关度分数")


class MemoryStoreRequest(BaseModel):
    """记忆存储请求"""
    user_id: str
    content: str
    memory_type: MemoryType = MemoryType.EPISODIC
    importance: MemoryImportance = MemoryImportance.MEDIUM
    tags: list[str] = Field(default_factory=list)
    source: str = "manual"
    related_entities: list[str] = Field(default_factory=list)


class MemoryConsolidationResult(BaseModel):
    """记忆巩固结果"""
    consolidated_count: int = Field(default=0)
    merged_memories: list[str] = Field(default_factory=list)
    archived_memories: list[str] = Field(default_factory=list)
