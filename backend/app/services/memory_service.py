"""
SundayOS 深度记忆系统
实现四层记忆架构：工作记忆 → 情景记忆 → 语义记忆 → 程序性记忆
基于 Mem0 + ChromaDB + PostgreSQL
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

from app.config import settings
from app.models.memory import (
    Memory, MemoryType, MemoryImportance,
    MemorySearchRequest, MemorySearchResult,
    MemoryStoreRequest, MemoryConsolidationResult,
)


class MemoryService:
    """
    SundayOS 深度记忆服务

    四层记忆架构：
    - L1 工作记忆：当前对话上下文（内存中，Redis 可选）
    - L2 情景记忆：结构化事件（PostgreSQL）
    - L3 语义记忆：长期偏好、知识（ChromaDB 向量搜索）
    - L4 程序性记忆：工作流、习惯（后期实现）
    """

    def __init__(self):
        # 工作记忆缓存（内存中，生产环境应使用 Redis）
        self._working_memory: dict[str, list[Memory]] = {}
        # 情景记忆存储（内存中，生产环境应使用 PostgreSQL）
        self._episodic_memory: dict[str, list[Memory]] = {}
        # 语义记忆存储（简化版向量存储，生产环境应使用 ChromaDB）
        self._semantic_memory: dict[str, list[Memory]] = {}
        # 简单的词汇向量化（生产环境应使用 embedding API）
        self._vocab_vectors: dict[str, np.ndarray] = {}

    def _simple_embed(self, text: str) -> np.ndarray:
        """
        简易文本向量化（基于字符 n-gram）
        生产环境应替换为 OpenAI Embeddings API 或本地模型
        """
        text = text.lower()
        n = 3
        grams = [text[i:i + n] for i in range(max(1, len(text) - n + 1))]

        if not grams:
            return np.zeros(128)

        vector = np.zeros(128)
        for gram in grams:
            hash_val = int(hashlib.md5(gram.encode()).hexdigest(), 16) % 128
            vector[hash_val] += 1

        # 归一化
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm

        return vector

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """计算余弦相似度"""
        return float(np.dot(a, b))

    def _generate_memory_id(self) -> str:
        """生成记忆ID"""
        return f"mem_{uuid.uuid4().hex[:12]}"

    # ========== 工作记忆 (L1) ==========

    def get_working_memory(
        self, user_id: str, session_id: str, limit: int = 10
    ) -> list[Memory]:
        """获取当前会话的工作记忆（最近对话）"""
        key = f"{user_id}:{session_id}"
        memories = self._working_memory.get(key, [])
        return sorted(memories, key=lambda m: m.created_at, reverse=True)[:limit]

    def add_working_memory(self, memory: Memory):
        """添加工作记忆"""
        key = f"{memory.user_id}:{memory.session_id}"
        if key not in self._working_memory:
            self._working_memory[key] = []
        self._working_memory[key].append(memory)
        # 限制工作记忆大小
        if len(self._working_memory[key]) > 50:
            self._working_memory[key] = self._working_memory[key][-50:]

    def clear_working_memory(self, user_id: str, session_id: str):
        """清除会话工作记忆"""
        key = f"{user_id}:{session_id}"
        self._working_memory.pop(key, None)

    # ========== 情景记忆 (L2) ==========

    async def store_memory(self, request: MemoryStoreRequest) -> Memory:
        """存储记忆"""
        memory = Memory(
            memory_id=self._generate_memory_id(),
            user_id=request.user_id,
            content=request.content,
            memory_type=request.memory_type,
            importance=request.importance,
            tags=request.tags,
            source=request.source,
            related_entities=request.related_entities,
        )

        # 生成向量嵌入
        memory.embedding = self._simple_embed(request.content).tolist()

        # 按类型存储
        if memory.memory_type == MemoryType.EPISODIC:
            storage = self._episodic_memory
        elif memory.memory_type == MemoryType.SEMANTIC:
            storage = self._semantic_memory
        else:
            storage = self._episodic_memory  # 默认情景

        if request.user_id not in storage:
            storage[request.user_id] = []
        storage[request.user_id].append(memory)

        return memory

    async def store_memories_batch(
        self, memories: list[MemoryStoreRequest]
    ) -> list[Memory]:
        """批量存储记忆"""
        results = []
        for req in memories:
            memory = await self.store_memory(req)
            results.append(memory)
        return results

    async def search_memories(
        self, request: MemorySearchRequest
    ) -> list[MemorySearchResult]:
        """搜索记忆（语义搜索 + 标签匹配）"""
        results = []

        # 收集所有相关记忆
        all_memories = []
        if MemoryType.EPISODIC in request.memory_types:
            all_memories.extend(self._episodic_memory.get(request.user_id, []))
        if MemoryType.SEMANTIC in request.memory_types:
            all_memories.extend(self._semantic_memory.get(request.user_id, []))

        if not all_memories:
            return results

        # 生成查询向量
        query_vec = self._simple_embed(request.query)

        # 计算相似度
        scored = []
        for memory in all_memories:
            # 时间过滤
            if request.time_range_days:
                cutoff = datetime.utcnow() - timedelta(days=request.time_range_days)
                if memory.created_at < cutoff:
                    continue

            # 重要度过滤
            if request.min_importance:
                imp_order = ["low", "medium", "high", "critical"]
                if imp_order.index(memory.importance.value) < imp_order.index(
                    request.min_importance.value
                ):
                    continue

            # 语义相似度
            if memory.embedding:
                mem_vec = np.array(memory.embedding)
                semantic_score = self._cosine_similarity(query_vec, mem_vec)
            else:
                semantic_score = 0.0

            # 标签匹配加分
            tag_score = 0.0
            query_lower = request.query.lower()
            for tag in memory.tags:
                if tag.lower() in query_lower or query_lower in tag.lower():
                    tag_score += 0.2

            # 有效重要度
            importance_score = memory.effective_importance()

            # 综合得分
            final_score = (
                semantic_score * 0.5
                + tag_score * 0.2
                + importance_score * 0.3
            )

            scored.append((memory, final_score))

        # 排序并返回
        scored.sort(key=lambda x: -x[1])
        for memory, score in scored[: request.limit]:
            # 更新访问计数
            memory.access_count += 1
            memory.last_accessed = datetime.utcnow()
            results.append(MemorySearchResult(memory=memory, relevance_score=round(score, 4)))

        return results

    async def get_recent_memories(
        self, user_id: str, days: int = 7, limit: int = 20
    ) -> list[Memory]:
        """获取最近记忆"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        all_memories = (
            self._episodic_memory.get(user_id, [])
            + self._semantic_memory.get(user_id, [])
        )
        recent = [m for m in all_memories if m.created_at >= cutoff]
        recent.sort(key=lambda m: m.effective_importance(), reverse=True)
        return recent[:limit]

    async def get_user_memories_context(self, user_id: str, query: str = "") -> str:
        """获取用户记忆上下文（用于系统提示）"""
        if query:
            search_req = MemorySearchRequest(
                user_id=user_id,
                query=query,
                limit=5,
                min_importance=MemoryImportance.MEDIUM,
            )
            search_results = await self.search_memories(search_req)
            memories = [r.memory for r in search_results]
        else:
            memories = await self.get_recent_memories(user_id, days=30, limit=10)

        if not memories:
            return "暂无相关记忆"

        lines = ["以下是关于用户的记忆："]
        for i, mem in enumerate(memories, 1):
            imp_icon = {"low": "📌", "medium": "📎", "high": "⭐", "critical": "🔴"}[
                mem.importance.value
            ]
            lines.append(f"{i}. {imp_icon} [{mem.memory_type.value}] {mem.content}")
            if mem.tags:
                lines.append(f"   标签：{', '.join(mem.tags)}")

        return "\n".join(lines)

    async def consolidate_memories(
        self, user_id: str
    ) -> MemoryConsolidationResult:
        """记忆巩固：合并相似记忆，归档旧记忆"""
        result = MemoryConsolidationResult()

        # 获取所有情景记忆
        episodic = self._episodic_memory.get(user_id, [])
        if len(episodic) < 2:
            return result

        # 合并相似记忆（简化版：基于标签重叠和语义相似度）
        merged = set()
        for i, mem1 in enumerate(episodic):
            if mem1.memory_id in merged:
                continue
            for j, mem2 in enumerate(episodic):
                if i >= j or mem2.memory_id in merged:
                    continue
                # 计算相似度
                if mem1.embedding and mem2.embedding:
                    sim = self._cosine_similarity(
                        np.array(mem1.embedding), np.array(mem2.embedding)
                    )
                    tag_overlap = len(set(mem1.tags) & set(mem2.tags))
                    if sim > 0.8 or (sim > 0.5 and tag_overlap > 2):
                        # 合并记忆
                        merged.add(mem2.memory_id)
                        result.merged_memories.append(mem2.content[:50])
                        # 提升保留记忆的重要度
                        if mem2.importance.value > mem1.importance.value:
                            mem1.importance = mem2.importance
                        mem1.tags = list(set(mem1.tags + mem2.tags))
                        mem1.access_count += mem2.access_count

        # 归档低重要度的旧记忆
        cutoff = datetime.utcnow() - timedelta(days=settings.memory_decay_days)
        for memory in episodic:
            if (
                memory.created_at < cutoff
                and memory.effective_importance() < settings.memory_importance_threshold
                and memory.importance != MemoryImportance.CRITICAL
            ):
                result.archived_memories.append(memory.content[:50])

        # 清理已合并的记忆
        self._episodic_memory[user_id] = [
            m for m in episodic if m.memory_id not in merged
        ]

        result.consolidated_count = len(merged) + len(result.archived_memories)
        return result

    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """删除记忆"""
        for storage in [self._episodic_memory, self._semantic_memory]:
            if user_id in storage:
                original_len = len(storage[user_id])
                storage[user_id] = [
                    m for m in storage[user_id] if m.memory_id != memory_id
                ]
                if len(storage[user_id]) < original_len:
                    return True
        return False

    async def get_memory_stats(self, user_id: str) -> dict:
        """获取记忆统计"""
        episodic = self._episodic_memory.get(user_id, [])
        semantic = self._semantic_memory.get(user_id, [])

        def count_by_importance(memories):
            counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
            for m in memories:
                counts[m.importance.value] += 1
            return counts

        return {
            "total_memories": len(episodic) + len(semantic),
            "episodic_count": len(episodic),
            "semantic_count": len(semantic),
            "importance_distribution": count_by_importance(episodic + semantic),
            "oldest_memory": min(
                (m.created_at for m in episodic + semantic), default=None
            ),
            "newest_memory": max(
                (m.created_at for m in episodic + semantic), default=None
            ),
        }


# 全局单例
memory_service = MemoryService()
