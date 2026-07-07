"""
SundayOS — 你的 iPhone 外置大脑

一个拥有记忆和人格的个人 AI 助手系统。
通过快捷指令调用 AI，实现语音/文字指令 → AI 处理 → 个性化回传。
像钢铁侠的贾维斯一样，从工具进化为真正的数字伙伴。

启动方式:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import chat_router, memory_router, user_router, skills_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    provider_info = settings.provider_config
    print(f"""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   🧠  SundayOS v{settings.app_version}                                  ║
║   你的 iPhone 外置大脑                                  ║
║                                                          ║
║   📡 API 文档: http://localhost:8000/docs                ║
║   🔍 ReDoc:    http://localhost:8000/redoc               ║
║   ❤️  健康检查:  http://localhost:8000/health             ║
║                                                          ║
║   👤 助手名称: {settings.assistant_name}                                  ║
║   🏭 LLM 供应商: {settings.llm_provider}                       ║
║   🤖 模型: {settings.effective_model}                       ║
║   💰 费用: {provider_info['description']}     ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
    """)
    yield
    print("\n👋 SundayOS 正在关闭...")


# 创建 FastAPI 应用
app = FastAPI(
    title="SundayOS API",
    description="""
## SundayOS — 你的 iPhone 外置大脑

像钢铁侠的贾维斯一样，SundayOS 是一个拥有记忆和人格的个人 AI 助手。

### 核心特性

- **🧠 深度记忆系统**：四层记忆架构，记住你的偏好、经历和习惯
- **👤 用户画像引擎**：自动学习和更新你的个人画像
- **🔧 技能调度**：天气、搜索、时间等实用技能
- **💬 流式对话**：SSE 流式响应，打字机效果
- **📱 iPhone 集成**：通过快捷指令无缝调用

### 使用方式

1. 配置环境变量（.env 文件）
2. 在 iPhone 快捷指令中配置 API 地址
3. 通过 Siri 或快捷指令开始对话
    """,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 配置（允许快捷指令调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求计时中间件
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(round(process_time, 3))
    response.headers["X-SundayOS-Version"] = settings.app_version
    return response


# 注册路由
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(user_router)
app.include_router(skills_router)


# ========== 基础端点 ==========

@app.get("/", tags=["root"])
async def root():
    """根路径"""
    return {
        "name": "SundayOS",
        "version": settings.app_version,
        "description": "你的 iPhone 外置大脑",
        "assistant": settings.assistant_name,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["health"])
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "assistant": settings.assistant_name,
        "provider": settings.llm_provider,
        "model": settings.effective_model,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/daily-brief/{user_id}", tags=["brief"])
async def daily_brief(user_id: str):
    """
    每日简报

    生成个性化每日简报：天气 + 时间 + 个性化问候
    可在 iPhone 快捷指令中设置为每天早上自动触发
    """
    from app.services.user_service import user_service
    from app.services.memory_service import memory_service

    profile = await user_service.get_profile(user_id)
    memories = await memory_service.get_recent_memories(user_id, days=1, limit=5)

    now = time.strftime("%Y年%m月%d日 %A")
    greeting = f"早上好"
    if profile.personal_info.preferred_name:
        greeting = f"早上好，{profile.personal_info.preferred_name}"
    elif profile.personal_info.name:
        greeting = f"早上好，{profile.personal_info.name}"

    brief = {
        "greeting": greeting,
        "date": now,
        "weather": "请配置 WEATHER_API_KEY 获取实时天气",
        "quote": "",
        "memories_today": len(memories),
        "recent_highlights": [m.content[:100] for m in memories[:3]],
    }

    return brief
