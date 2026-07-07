"""
SundayOS 用户画像路由
管理用户个人信息、偏好、兴趣
"""
from fastapi import APIRouter, Depends, HTTPException

from app.middleware.auth import verify_api_key
from app.models.user import UserProfile, Routine, Interest, Relationship
from app.services.user_service import user_service

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/profile/{user_id}", response_model=UserProfile)
async def get_profile(user_id: str, _: str = Depends(verify_api_key)):
    """获取用户完整画像"""
    return await user_service.get_profile(user_id)


@router.put("/profile/{user_id}")
async def update_profile(
    user_id: str, updates: dict, _: str = Depends(verify_api_key)
):
    """更新用户画像"""
    profile = await user_service.update_profile(user_id, updates)
    return {
        "status": "updated",
        "user_id": user_id,
        "profile": profile.model_dump(),
    }


@router.post("/profile/{user_id}/interests")
async def add_interest(
    user_id: str, interest: Interest, _: str = Depends(verify_api_key)
):
    """添加兴趣"""
    result = await user_service.add_interest(
        user_id, interest.category, interest.name, interest.level
    )
    return {"status": "added", "interest": result.model_dump()}


@router.post("/profile/{user_id}/relationships")
async def add_relationship(
    user_id: str, relationship: Relationship, _: str = Depends(verify_api_key)
):
    """添加人际关系"""
    result = await user_service.add_relationship(
        user_id, relationship.name, relationship.relation, relationship.importance
    )
    return {"status": "added", "relationship": result.model_dump()}


@router.post("/profile/{user_id}/routines")
async def add_routine(
    user_id: str, routine: Routine, _: str = Depends(verify_api_key)
):
    """添加日常规律"""
    result = await user_service.add_routine(user_id, routine)
    return {"status": "added", "routine": result.model_dump()}


@router.delete("/profile/{user_id}")
async def delete_profile(user_id: str, _: str = Depends(verify_api_key)):
    """删除用户画像（隐私保护）"""
    deleted = await user_service.delete_profile(user_id)
    if deleted:
        return {"status": "deleted", "user_id": user_id}
    raise HTTPException(status_code=404, detail="用户不存在")
