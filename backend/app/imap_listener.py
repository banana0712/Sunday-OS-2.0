"""
SundayOS IMAP 邮件监听模块
连接 iCloud 邮箱，定时检查新邮件并自动回复
"""
import asyncio
import logging
import re
import threading
import time
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header
from zoneinfo import ZoneInfo

from app.config import settings
from app.mailer import send_email
from app.memory import memory_store

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")

# iCloud IMAP 配置
IMAP_HOST = "imap.mail.me.com"
IMAP_PORT = 993
IMAP_USER = settings.push_email
IMAP_PASSWORD = settings.imap_password

# 已处理邮件 UID
PROCESSED_UIDS = set()


def _decode_subject(subject_bytes):
    """解码邮件主题"""
    if not subject_bytes:
        return ""
    try:
        parts = decode_header(subject_bytes)
        result = ""
        for part, charset in parts:
            if isinstance(part, bytes):
                result += part.decode(charset or "utf-8", errors="replace")
            else:
                result += part
        return result
    except Exception:
        return str(subject_bytes)


def _get_email_body(msg):
    """提取邮件正文"""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                    break
                except Exception:
                    continue
            elif content_type == "text/html" and not body:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
        except Exception:
            pass
    return body


def _clean_reply_body(body: str) -> str:
    """清理邮件回复中的引用内容"""
    separators = [
        "\n\nOn ",
        "\n\n> ",
        "\n---\n",
        "\n_________________",
        "发件人：",
        "From: Sunday",
        "— Sunday ·",
        "在 ",
        "<div dir=\"ltr\">",
    ]
    for sep in separators:
        if sep in body:
            body = body.split(sep)[0]
            break
    
    # 移除 HTML 标签
    body = re.sub(r'<[^>]+>', '', body)
    # 移除多余空白
    body = ' '.join(body.split())
    return body.strip()


def _is_sunday_email(subject: str) -> bool:
    """判断是否是回复 Sunday 的邮件"""
    return any(kw in subject.lower() for kw in [
        "sunday", "早安", "晚安", "测试邮件", "推送", "回复",
    ])


async def _process_email(uid: int, subject: str, body: str, from_addr: str):
    """处理一封用户回复的邮件"""
    logger.info(f"📧 收到邮件回复 [UID:{uid}] from {from_addr}: {subject[:50]}")
    
    clean_body = _clean_reply_body(body)
    if not clean_body or len(clean_body) < 3:
        logger.info(f"邮件正文为空或太短，跳过 [UID:{uid}]")
        return
    
    user_id = "iphone-daily"
    
    # 记录到对话流
    memory_store.add_conversation(user_id, "user", clean_body)
    
    # 调用 LLM 生成回复
    from app.main import llm_service, select_model, SUNDAY_SYSTEM_PROMPT
    
    model_id, chat_mode = select_model(clean_body)
    
    memories = memory_store.get_context(user_id, message=clean_body)
    profile = _build_user_profile(user_id)
    flow = memory_store.get_conversation_context(user_id, max_turns=10)
    
    system_prompt = SUNDAY_SYSTEM_PROMPT.format(
        current_time=datetime.now(TZ).strftime("%Y年%m月%d日 %H:%M，周%u"),
        user_profile=profile,
        conversation_flow=flow or "（这是你们第一次对话呢~）",
        memories=memories,
        chat_mode=chat_mode,
    )
    
    try:
        response = await llm_service.client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": clean_body},
            ],
            temperature=llm_service.temperature,
            max_tokens=400 if "聊天模式" in chat_mode else llm_service.max_tokens,
        )
        
        reply = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        
        memory_store.add_conversation(user_id, "assistant", reply, tokens)
        
        # 提取记忆
        from app.main import extract_memories_from_message, _force_extract_info
        await extract_memories_from_message(llm_service.client, clean_body, user_id)
        _force_extract_info(clean_body, user_id)
        
        # 发邮件回复
        subject_reply = f"Re: {subject}" if not subject.startswith("Re:") else subject
        if not _is_sunday_email(subject):
            subject_reply = "Sunday 回复你啦~ 💕"
        
        send_email(subject=subject_reply, body=reply)
        
        logger.info(f"✅ 已回复邮件 [UID:{uid}]，tokens: {tokens}")
        
    except Exception as e:
        logger.error(f"处理邮件回复失败 [UID:{uid}]: {e}")


def _build_user_profile(user_id: str) -> str:
    """构建用户画像"""
    stats = memory_store.get_stats(user_id)
    if stats["total"] == 0:
        return "这是一位新朋友，还不太了解呢~"
    
    parts = []
    facts = memory_store.search(user_id, category="fact", limit=3)
    for f in facts:
        parts.append(f.get("summary", f["content"]))
    
    prefs = memory_store.search(user_id, category="preference", limit=3)
    for p in prefs:
        parts.append(p.get("summary", p["content"]))
    
    return "、".join(parts) if parts else f"已存储 {stats['total']} 条记忆"


def _check_emails_once():
    """单次检查邮件"""
    print("📬 _check_emails_once() 被调用")
    
    try:
        import imaplib
        print("📬 imaplib 导入成功")
    except Exception as e:
        print(f"📬 imaplib 导入失败: {e}")
        return
    
    if not IMAP_USER or not IMAP_PASSWORD:
        print("📬 IMAP 未配置，跳过")
        return
    
    print(f"📬 连接 IMAP: {IMAP_HOST}:{IMAP_PORT}")
    
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=30)
        print("📬 IMAP SSL 连接成功")
        
        mail.login(IMAP_USER, IMAP_PASSWORD)
        print("📬 IMAP 登录成功")
        
        mail.select("INBOX")
        print("📬 选择 INBOX 成功")
        
        # 搜索未读邮件
        _, data = mail.search(None, "UNSEEN")
        print(f"📬 搜索未读邮件结果: {data}")
        
        if data and data[0]:
            uids = data[0].split()
        else:
            uids = []
        
        print(f"📬 找到 {len(uids)} 封未读邮件")
        
        for uid in uids:
            uid_str = str(uid.decode() if isinstance(uid, bytes) else uid)
            print(f"📬 处理邮件 UID: {uid_str}")
            if uid_str in PROCESSED_UIDS:
                print(f"📬 跳过已处理邮件: {uid_str}")
                continue
            
            try:
                _, msg_data = mail.fetch(uid, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue
                raw_email = msg_data[0][1]
                msg = message_from_bytes(raw_email)
                
                subject = _decode_subject(msg.get("Subject", ""))
                from_addr = msg.get("From", "")
                body = _get_email_body(msg)
                
                print(f"📬 邮件: {subject[:50]} from {from_addr}")
                
                # 只处理回复 Sunday 的邮件
                if _is_sunday_email(subject) or "sunday" in from_addr.lower():
                    PROCESSED_UIDS.add(uid_str)
                    # 标记为已读
                    mail.store(uid, '+FLAGS', '\\Seen')
                    # 异步处理
                    asyncio.create_task(_process_email(int(uid_str), subject, body, from_addr))
                else:
                    print(f"📬 跳过非 Sunday 邮件")
            except Exception as e:
                print(f"📬 处理单封邮件失败 [UID:{uid_str}]: {e}")
        
        mail.close()
        mail.logout()
        print("📬 IMAP 连接关闭")
        
    except Exception as e:
        print(f"📬 IMAP 连接失败: {e}")
        import traceback
        traceback.print_exc()


async def email_polling_loop():
    """邮件轮询循环：每 15 秒检查一次新邮件"""
    print(f"📬 email_polling_loop 开始, IMAP_USER={IMAP_USER}, IMAP_PASSWORD={'有' if IMAP_PASSWORD else '无'}")
    
    if not IMAP_USER or not IMAP_PASSWORD:
        print("📬 IMAP 未配置，邮件监听退出")
        return
    
    print(f"📬 启动邮件轮询: {IMAP_USER} (每15秒)")
    
    while True:
        print("📬 开始新一轮邮件检查...")
        try:
            _check_emails_once()
        except Exception as e:
            print(f"📬 邮件轮询异常: {e}")
            import traceback
            traceback.print_exc()
        
        print("📬 等待15秒...")
        await asyncio.sleep(15)


def start_email_listener():
    """在后台线程中启动邮件监听"""
    print("📬 start_email_listener() 被调用")
    
    if not IMAP_USER or not IMAP_PASSWORD:
        print(f"📬 IMAP 未配置: user={IMAP_USER}, pass={'有' if IMAP_PASSWORD else '无'}")
        return
    
    def run_loop():
        print("📬 邮件监听线程启动中...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(email_polling_loop())
    
    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    print("📬 邮件监听线程已启动")
