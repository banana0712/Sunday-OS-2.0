"""
SundayOS API 鉴权中间件
"""
from fastapi import Request, HTTPException, status
from app.config import settings


async def verify_api_key(request: Request):
    """验证 API Key"""
    # 从 Header 或 Query 参数获取 API Key
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 API Key，请在 X-API-Key Header 或 api_key 参数中提供",
        )

    if api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无效的 API Key",
        )

    return api_key
