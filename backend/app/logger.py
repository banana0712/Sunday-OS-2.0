"""
SundayOS 运行日志系统
记录所有关键事件：消息、记忆变更、错误、推送
"""
import json
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

TZ = ZoneInfo("Asia/Shanghai")
DB_PATH = Path("/app/data/sunday_memory.db")


def _get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_log_table():
    """初始化日志表（在 memory.init_db 中调用）"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sunday_logs (
            id TEXT PRIMARY KEY,
            log_type TEXT NOT NULL,
            user_id TEXT DEFAULT '',
            source TEXT DEFAULT '',
            summary TEXT DEFAULT '',
            detail TEXT DEFAULT '',
            status TEXT DEFAULT 'ok',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_logs_type_time ON sunday_logs(log_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_logs_user ON sunday_logs(user_id);
    """)
    conn.commit()
    conn.close()


def log(log_type: str, user_id: str = "", source: str = "", 
        summary: str = "", detail: str = "", status: str = "ok"):
    """写入一条日志"""
    conn = _get_conn()
    now = datetime.now(TZ).isoformat()
    log_id = f"log_{uuid.uuid4().hex[:10]}"
    
    # 截断过长的 detail
    if detail and len(detail) > 2000:
        detail = detail[:2000] + "..."
    
    conn.execute(
        """INSERT INTO sunday_logs (id, log_type, user_id, source, summary, detail, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (log_id, log_type, user_id, source, summary, detail, status, now),
    )
    conn.commit()
    conn.close()


def query(log_type: str = "", user_id: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
    """查询日志"""
    conn = _get_conn()
    conditions = []
    params = []
    
    if log_type:
        conditions.append("log_type = ?")
        params.append(log_type)
    if user_id:
        conditions.append("user_id = ?")
        params.append(user_id)
    
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM sunday_logs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def stats(user_id: str = "") -> dict:
    """获取日志统计"""
    conn = _get_conn()
    
    user_filter = "WHERE user_id = ?" if user_id else ""
    params = [user_id] if user_id else []
    
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    
    # 总日志数
    total = conn.execute(f"SELECT COUNT(*) FROM sunday_logs {user_filter}", params).fetchone()[0]
    
    # 按类型统计
    by_type = {}
    rows = conn.execute(
        f"SELECT log_type, COUNT(*) as cnt FROM sunday_logs {user_filter} GROUP BY log_type", params
    ).fetchall()
    for r in rows:
        by_type[r["log_type"]] = r["cnt"]
    
    # 今日统计
    today_params = params + [f"{today}%"]
    today_total = conn.execute(
        f"SELECT COUNT(*) FROM sunday_logs {user_filter} {'AND' if user_filter else 'WHERE'} created_at LIKE ?", 
        today_params
    ).fetchone()[0]
    
    # 今日错误
    today_error = conn.execute(
        f"SELECT COUNT(*) FROM sunday_logs {user_filter} {'AND' if user_filter else 'WHERE'} log_type = 'error' AND created_at LIKE ?",
        today_params
    ).fetchone()[0]
    
    # 最近错误
    recent_errors = conn.execute(
        f"SELECT summary, created_at FROM sunday_logs {user_filter} {'AND' if user_filter else 'WHERE'} log_type = 'error' ORDER BY created_at DESC LIMIT 5",
        params
    ).fetchall()
    
    conn.close()
    
    return {
        "total": total,
        "by_type": by_type,
        "today": {"total": today_total, "errors": today_error},
        "recent_errors": [dict(r) for r in recent_errors],
    }
