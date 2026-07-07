"""
SundayOS 技能路由
执行天气、搜索、时间等外部技能
"""
from fastapi import APIRouter, Depends

from app.middleware.auth import verify_api_key
from app.services.skill_service import skill_service

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("/available")
async def list_available_skills(_: str = Depends(verify_api_key)):
    """列出所有可用技能"""
    return {
        "skills": [
            {"name": s["name"], "description": s["description"]}
            for s in skill_service.AVAILABLE_SKILLS.values()
        ]
    }


@router.post("/execute")
async def execute_skill(
    request: dict, _: str = Depends(verify_api_key)
):
    """执行技能"""
    skill_name = request.get("skill")
    arguments = request.get("arguments", {})

    if not skill_name:
        return {"success": False, "error": "请指定技能名称"}

    result = await skill_service.execute(skill_name, arguments)
    return result


@router.get("/weather/{city}")
async def get_weather(city: str, _: str = Depends(verify_api_key)):
    """查询天气（快捷方式）"""
    result = await skill_service.execute("get_weather", {"city": city})
    return result


@router.get("/time")
async def get_time(timezone: str = "Asia/Shanghai", _: str = Depends(verify_api_key)):
    """获取当前时间（快捷方式）"""
    result = await skill_service.execute("get_time", {"timezone": timezone})
    return result
