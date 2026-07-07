"""
SundayOS 记忆路由
记忆的存储、搜索、管理和巩固
"""
from fastapi import APIRouter, Depends, HTTPException

from app.middleware.auth import verify_api_key
from app.models.memory import (
    MemorySearchRequest, MemorySearchResult,
    MemoryStoreRequest, MemoryConsolidationResult,
    MemoryImportance,
)
from app.services.memory_service import memory_service

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.post("/search", response_model=list[MemorySearchResult])
async def search_memories(
    request: MemorySearchRequest, _: str = Depends(verify_api_key)
):
    """语义搜索记忆"""
    results = await memory_service.search_memories(request)
    return results


@router.post("/store")
async def store_memory(
    request: MemoryStoreRequest, _: str = Depends(verify_api_key)
):
    """存储一条记忆"""
    memory = await memory_service.store_memory(request)
    return {"status": "stored", "memory_id": memory.memory_id, "content": memory.content}


@router.post("/store/batch")
async def store_memories_batch(
    requests: list[MemoryStoreRequest], _: str = Depends(verify_api_key)
):
    """批量存储记忆"""
    memories = await memory_service.store_memories_batch(requests)
    return {
        "status": "stored",
        "count": len(memories),
        "memory_ids": [m.memory_id for m in memories],
    }


@router.get("/recent/{user_id}")
async def get_recent_memories(
    user_id: str,
    days: int = 7,
    limit: int = 20,
    _: str = Depends(verify_api_key),
):
    """获取最近记忆"""
    memories = await memory_service.get_recent_memories(
        user_id=user_id, days=days, limit=limit
    )
    return {
        "user_id": user_id,
        "count": len(memories),
        "memories": [
            {
                "memory_id": m.memory_id,
                "content": m.content,
                "type": m.memory_type.value,
                "importance": m.importance.value,
                "tags": m.tags,
                "created_at": m.created_at.isoformat(),
                "effective_importance": round(m.effective_importance(), 3),
            }
            for m in memories
        ],
    }


@router.get("/context/{user_id}")
async def get_memory_context(
    user_id: str, query: str = "", _: str = Depends(verify_api_key)
):
    """获取记忆上下文（用于 LLM 系统提示）"""
    context = await memory_service.get_user_memories_context(user_id, query)
    return {"user_id": user_id, "context": context}


@router.post("/consolidate/{user_id}")
async def consolidate_memories(
    user_id: str, _: str = Depends(verify_api_key)
) -> MemoryConsolidationResult:
    """记忆巩固：合并相似记忆、归档旧记忆"""
    result = await memory_service.consolidate_memories(user_id)
    return result


@router.delete("/{user_id}/{memory_id}")
async def delete_memory(
    user_id: str, memory_id: str, _: str = Depends(verify_api_key)
):
    """删除一条记忆"""
    deleted = await memory_service.delete_memory(user_id, memory_id)
    if deleted:
        return {"status": "deleted", "memory_id": memory_id}
    raise HTTPException(status_code=404, detail="记忆不存在")


@router.get("/stats/{user_id}")
async def get_memory_stats(
    user_id: str, _: str = Depends(verify_api_key)
):
    """获取记忆统计信息"""
    stats = await memory_service.get_memory_stats(user_id)
    return stats
