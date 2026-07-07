"""
SundayOS 对话路由
处理用户对话的核心 API
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.middleware.auth import verify_api_key
from app.models.chat import (
    ChatRequest, ChatResponse, Message, MessageRole, StreamChunk,
)
from app.services.llm_service import llm_service
from app.services.memory_service import memory_service
from app.services.user_service import user_service

router = APIRouter(prefix="/api", tags=["chat"])

# 会话存储（内存中，生产环境应使用 Redis/PostgreSQL）
conversations: dict[str, list[Message]] = {}


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _: str = Depends(verify_api_key)):
    """
    主对话接口

    接收用户消息，返回 AI 回复。
    自动整合用户画像和记忆上下文。
    """
    # 创建或获取会话
    session_id = request.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    if session_id not in conversations:
        conversations[session_id] = []

    # 获取用户画像上下文
    user_context = ""
    if request.include_profile:
        user_context = await user_service.get_context_for_llm(request.user_id)

    # 获取记忆上下文
    memories = ""
    if request.include_memories:
        memories = await memory_service.get_user_memories_context(
            request.user_id, request.message
        )

    # 获取对话历史
    history = conversations.get(session_id, [])

    # 调用 LLM
    response = await llm_service.chat(
        message=request.message,
        conversation_history=history,
        user_context=user_context,
        memories=memories,
    )

    # 保存对话
    user_msg = Message(role=MessageRole.USER, content=request.message)
    assistant_msg = Message(role=MessageRole.ASSISTANT, content=response.reply)
    conversations[session_id].append(user_msg)
    conversations[session_id].append(assistant_msg)

    # 限制对话历史长度
    if len(conversations[session_id]) > 40:  # 20轮
        conversations[session_id] = conversations[session_id][-40:]

    # 更新会话ID
    response.session_id = session_id

    # 检测情绪
    emotion = await llm_service.detect_emotion(request.message)
    response.emotions_detected = emotion

    # 异步保存记忆（不阻塞回复）
    try:
        from app.models.memory import MemoryStoreRequest, MemoryImportance, MemoryType

        # 判断是否需要保存为记忆
        if len(request.message) > 20:  # 有一定信息量的消息
            memory_req = MemoryStoreRequest(
                user_id=request.user_id,
                content=f"用户说：{request.message}",
                memory_type=MemoryType.EPISODIC,
                importance=MemoryImportance.MEDIUM,
                source="conversation",
            )
            await memory_service.store_memory(memory_req)

        # 保存AI回复中的重要信息
        if len(response.reply) > 30:
            memory_req = MemoryStoreRequest(
                user_id=request.user_id,
                content=f"Sunday回复：{response.reply[:200]}",
                memory_type=MemoryType.EPISODIC,
                importance=MemoryImportance.LOW,
                source="conversation",
            )
            await memory_service.store_memory(memory_req)
    except Exception:
        pass  # 记忆保存失败不影响主流程

    return response


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, _: str = Depends(verify_api_key)):
    """
    流式对话接口（SSE）

    使用 Server-Sent Events 实现打字机效果
    """
    session_id = request.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    if session_id not in conversations:
        conversations[session_id] = []

    # 获取上下文
    user_context = ""
    if request.include_profile:
        user_context = await user_service.get_context_for_llm(request.user_id)

    memories = ""
    if request.include_memories:
        memories = await memory_service.get_user_memories_context(
            request.user_id, request.message
        )

    history = conversations.get(session_id, [])

    # 保存用户消息
    user_msg = Message(role=MessageRole.USER, content=request.message)
    conversations[session_id].append(user_msg)

    full_reply = []

    async def event_generator():
        try:
            async for chunk in llm_service.chat_stream(
                message=request.message,
                conversation_history=history,
                user_context=user_context,
                memories=memories,
                session_id=session_id,
            ):
                if chunk.type == "text":
                    full_reply.append(chunk.content)
                    yield f"data: {chunk.model_dump_json()}\n\n"
                elif chunk.type == "done":
                    # 保存完整回复
                    assistant_msg = Message(
                        role=MessageRole.ASSISTANT, content="".join(full_reply)
                    )
                    conversations[session_id].append(assistant_msg)

                    if len(conversations[session_id]) > 40:
                        conversations[session_id] = conversations[session_id][-40:]

                    yield f"data: {chunk.model_dump_json()}\n\n"
                    yield "data: [DONE]\n\n"
        except Exception as e:
            error_chunk = StreamChunk(
                type="error",
                content=str(e),
                session_id=session_id,
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/history/{session_id}")
async def get_chat_history(
    session_id: str, _: str = Depends(verify_api_key)
):
    """获取对话历史"""
    history = conversations.get(session_id, [])
    return {
        "session_id": session_id,
        "message_count": len(history),
        "messages": [
            {
                "role": m.role.value,
                "content": m.content,
                "timestamp": m.timestamp.isoformat(),
            }
            for m in history
        ],
    }


@router.delete("/chat/history/{session_id}")
async def clear_chat_history(
    session_id: str, _: str = Depends(verify_api_key)
):
    """清除对话历史"""
    if session_id in conversations:
        del conversations[session_id]
        return {"status": "deleted", "session_id": session_id}
    return {"status": "not_found", "session_id": session_id}


@router.get("/chat/sessions")
async def list_sessions(_: str = Depends(verify_api_key)):
    """列出所有会话"""
    return {
        "sessions": [
            {
                "session_id": sid,
                "message_count": len(msgs),
                "last_message": msgs[-1].content[:100] if msgs else "",
                "last_active": msgs[-1].timestamp.isoformat() if msgs else "",
            }
            for sid, msgs in conversations.items()
        ]
    }
