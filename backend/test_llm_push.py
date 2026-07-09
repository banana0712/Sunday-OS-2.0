import asyncio
import sys
sys.path.insert(0, "/app")
from app.mailer import _generate_with_llm
from app.main import llm_service
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

async def test():
    fake_now = datetime(2026, 7, 10, 8, 0, 0, tzinfo=TZ)
    msg = await _generate_with_llm(llm_service.client, "daily", "morning", fake_now)
    print("=== LLM 生成的早安消息 ===")
    print(msg)
    print("========================")

asyncio.run(test())
