"""
SundayOS 用户画像服务
管理用户个人信息、偏好、兴趣、关系的全生命周期
"""
from datetime import datetime
from typing import Optional

from app.config import settings
from app.models.user import (
    UserProfile, PersonalInfo, Interest, Routine,
    Relationship, Preference,
)


class UserService:
    """SundayOS 用户画像服务"""

    def __init__(self):
        # 用户画像存储（内存中，生产环境应使用 PostgreSQL）
        self._profiles: dict[str, UserProfile] = {}

    async def get_profile(self, user_id: str) -> UserProfile:
        """获取用户画像，不存在则创建默认画像"""
        if user_id not in self._profiles:
            self._profiles[user_id] = UserProfile(user_id=user_id)
        return self._profiles[user_id]

    async def update_profile(
        self, user_id: str, updates: dict
    ) -> UserProfile:
        """更新用户画像"""
        profile = await self.get_profile(user_id)

        if "personal_info" in updates:
            for key, value in updates["personal_info"].items():
                if hasattr(profile.personal_info, key):
                    setattr(profile.personal_info, key, value)

        if "preferences" in updates:
            for key, value in updates["preferences"].items():
                if hasattr(profile.preferences, key):
                    setattr(profile.preferences, key, value)

        profile.updated_at = datetime.utcnow()
        profile.interaction_count += 1

        return profile

    async def add_interest(
        self, user_id: str, category: str, name: str, level: float = 0.5
    ) -> Interest:
        """添加或更新兴趣"""
        profile = await self.get_profile(user_id)

        # 检查是否已存在
        for interest in profile.interests:
            if interest.name.lower() == name.lower():
                interest.level = min(1.0, interest.level + 0.1)
                interest.last_mentioned = datetime.utcnow()
                return interest

        # 新增
        new_interest = Interest(
            category=category, name=name, level=level
        )
        profile.interests.append(new_interest)
        profile.updated_at = datetime.utcnow()
        return new_interest

    async def add_relationship(
        self, user_id: str, name: str, relation: str, importance: float = 0.5
    ) -> Relationship:
        """添加或更新人际关系"""
        profile = await self.get_profile(user_id)

        for rel in profile.relationships:
            if rel.name == name:
                rel.relation = relation
                rel.importance = importance
                rel.last_interaction = datetime.utcnow()
                return rel

        new_rel = Relationship(
            name=name,
            relation=relation,
            importance=importance,
            last_interaction=datetime.utcnow(),
        )
        profile.relationships.append(new_rel)
        profile.updated_at = datetime.utcnow()
        return new_rel

    async def add_routine(
        self, user_id: str, routine: Routine
    ) -> Routine:
        """添加日常规律"""
        profile = await self.get_profile(user_id)

        # 检查同一天是否已有规律
        for existing in profile.routines:
            if existing.weekday == routine.weekday:
                # 更新
                for key, value in routine.model_dump(exclude={"weekday"}).items():
                    if value is not None:
                        setattr(existing, key, value)
                return existing

        profile.routines.append(routine)
        profile.updated_at = datetime.utcnow()
        return routine

    async def add_knowledge_domain(self, user_id: str, domain: str):
        """添加知识领域"""
        profile = await self.get_profile(user_id)
        if domain not in profile.knowledge_domains:
            profile.knowledge_domains.append(domain)
            if len(profile.knowledge_domains) > 20:
                profile.knowledge_domains = profile.knowledge_domains[-20:]

    async def add_location(self, user_id: str, location: str):
        """添加常去地点"""
        profile = await self.get_profile(user_id)
        if location not in profile.frequent_locations:
            profile.frequent_locations.append(location)
            if len(profile.frequent_locations) > 10:
                profile.frequent_locations = profile.frequent_locations[-10:]

    async def get_context_for_llm(self, user_id: str) -> str:
        """获取用于 LLM 系统提示的用户上下文"""
        profile = await self.get_profile(user_id)
        return profile.to_system_context()

    async def update_from_conversation(
        self, user_id: str, extracted_info: dict
    ):
        """从对话中提取信息并更新画像"""
        profile = await self.get_profile(user_id)

        # 处理提取到的信息
        if "name" in extracted_info:
            if not profile.personal_info.name:
                profile.personal_info.name = extracted_info["name"]
                profile.personal_info.preferred_name = extracted_info["name"]

        if "occupation" in extracted_info:
            profile.personal_info.occupation = extracted_info["occupation"]

        if "interests" in extracted_info:
            for interest_data in extracted_info["interests"]:
                await self.add_interest(
                    user_id,
                    interest_data.get("category", "general"),
                    interest_data["name"],
                    interest_data.get("level", 0.5),
                )

        if "relationships" in extracted_info:
            for rel_data in extracted_info["relationships"]:
                await self.add_relationship(
                    user_id,
                    rel_data["name"],
                    rel_data.get("relation", "unknown"),
                    rel_data.get("importance", 0.5),
                )

        profile.updated_at = datetime.utcnow()
        profile.interaction_count += 1

    async def delete_profile(self, user_id: str) -> bool:
        """删除用户画像（隐私保护）"""
        if user_id in self._profiles:
            del self._profiles[user_id]
            return True
        return False


# 全局单例
user_service = UserService()
