"""
SundayOS 记忆系统 — 持久化存储、分类管理、智能检索
"""
import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


DB_PATH = Path("/app/data/sunday_memory.db")


def get_db() -> sqlite3.Connection:
    """获取数据库连接"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'fact',
            content TEXT NOT NULL,
            tags TEXT DEFAULT '[]',
            importance TEXT DEFAULT 'medium',
            source TEXT DEFAULT 'manual',
            access_count INTEGER DEFAULT 0,
            decay_factor REAL DEFAULT 1.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_accessed TEXT,
            archived INTEGER DEFAULT 0
        );
        
        CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id, archived);
        CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(user_id, category);
        CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(user_id, importance);
        CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC);
        
        CREATE TABLE IF NOT EXISTS memory_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            count INTEGER DEFAULT 1,
            UNIQUE(user_id, tag)
        );
    """)
    conn.commit()
    conn.close()


# ============================================================
# 记忆类别
# ============================================================
MEMORY_CATEGORIES = {
    "fact":       "📋 事实",       # 客观事实（小明住在北京）
    "preference": "💝 偏好",       # 喜好（喜欢美式咖啡）
    "event":      "📅 行程",       # 日程事件（明天下午3点面试）
    "relationship": "👥 关系",     # 人际关系（女朋友叫小红）
    "goal":       "🎯 目标",       # 目标计划（今年想学钢琴）
    "note":       "📝 笔记",       # 通用笔记
    "habit":      "🔄 习惯",       # 生活习惯（每天7点起床）
}

IMPORTANCE_LEVELS = {
    "low":      {"score": 0.3, "label": "⭐ 一般"},
    "medium":   {"score": 0.5, "label": "⭐⭐ 重要"},
    "high":     {"score": 0.7, "label": "⭐⭐⭐ 很重要"},
    "critical": {"score": 1.0, "label": "💎 核心记忆"},
}


# ============================================================
# 记忆存储
# ============================================================
class MemoryStore:
    def __init__(self):
        init_db()

    def store(
        self,
        user_id: str,
        content: str,
        category: str = "fact",
        tags: list[str] = None,
        importance: str = "medium",
        source: str = "manual",
    ) -> dict:
        """存储一条记忆"""
        now = datetime.now().isoformat()
        mem_id = f"mem_{uuid.uuid4().hex[:12]}"
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        conn = get_db()
        conn.execute(
            """INSERT INTO memories (id, user_id, category, content, tags, importance, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mem_id, user_id, category, content, tags_json, importance, source, now, now),
        )

        # 更新标签计数
        for tag in (tags or []):
            conn.execute(
                """INSERT INTO memory_tags (user_id, tag, count) VALUES (?, ?, 1)
                   ON CONFLICT(user_id, tag) DO UPDATE SET count = count + 1""",
                (user_id, tag),
            )

        conn.commit()
        conn.close()

        return self.get(mem_id)

    def get(self, mem_id: str) -> Optional[dict]:
        """获取单条记忆"""
        conn = get_db()
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (mem_id,)).fetchone()
        conn.close()
        if row:
            return self._row_to_dict(row)
        return None

    def search(
        self,
        user_id: str,
        query: str = "",
        category: str = "",
        tags: list[str] = None,
        importance: str = "",
        limit: int = 20,
        offset: int = 0,
        include_archived: bool = False,
    ) -> list[dict]:
        """搜索记忆"""
        conn = get_db()
        conditions = ["user_id = ?"]
        params = [user_id]

        if not include_archived:
            conditions.append("archived = 0")

        if category:
            conditions.append("category = ?")
            params.append(category)

        if importance:
            conditions.append("importance = ?")
            params.append(importance)

        sql = f"SELECT * FROM memories WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()
        conn.close()

        results = [self._row_to_dict(r) for r in rows]

        # 如果有查询词，做关键词匹配排序
        if query and results:
            query_lower = query.lower()
            scored = []
            for r in results:
                score = 0
                content_lower = r["content"].lower()
                for word in query_lower.split():
                    if word in content_lower:
                        score += 1
                # 标签匹配加分
                for tag in r["tags"]:
                    if tag.lower() in query_lower:
                        score += 2
                # 重要性加权
                score *= IMPORTANCE_LEVELS.get(r["importance"], {"score": 0.5})["score"] * 2
                # 访问频次加权
                score *= (1 + 0.05 * r["access_count"])
                scored.append((score, r))
            scored.sort(key=lambda x: x[0], reverse=True)
            results = [r for _, r in scored]

        return results

    def update(self, mem_id: str, **kwargs) -> Optional[dict]:
        """更新记忆"""
        conn = get_db()
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (mem_id,)).fetchone()
        if not row:
            conn.close()
            return None

        allowed = ["content", "category", "importance", "tags"]
        updates = {}
        for k in allowed:
            if k in kwargs:
                if k == "tags":
                    updates[k] = json.dumps(kwargs[k], ensure_ascii=False)
                else:
                    updates[k] = kwargs[k]

        if updates:
            updates["updated_at"] = datetime.now().isoformat()
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE memories SET {set_clause} WHERE id = ?", list(updates.values()) + [mem_id])
            conn.commit()

        conn.close()
        return self.get(mem_id)

    def delete(self, mem_id: str) -> bool:
        """删除记忆"""
        conn = get_db()
        conn.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
        deleted = conn.total_changes > 0
        conn.commit()
        conn.close()
        return deleted

    def archive(self, mem_id: str) -> bool:
        """归档记忆"""
        return self.update(mem_id, archived=1) is not None

    def unarchive(self, mem_id: str) -> bool:
        """取消归档"""
        return self.update(mem_id, archived=0) is not None

    def record_access(self, mem_id: str):
        """记录访问"""
        conn = get_db()
        conn.execute(
            "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
            (datetime.now().isoformat(), mem_id),
        )
        conn.commit()
        conn.close()

    def get_context(self, user_id: str, limit: int = 10, category: str = "") -> str:
        """获取给 LLM 用的记忆上下文"""
        mems = self.search(user_id, limit=limit, category=category)
        if not mems:
            return "暂无关于用户的记忆"

        lines = []
        for m in mems:
            cat_label = MEMORY_CATEGORIES.get(m["category"], m["category"])
            lines.append(f"[{cat_label}] {m['content']}")

        return "\n".join(lines)

    def get_stats(self, user_id: str) -> dict:
        """获取记忆统计"""
        conn = get_db()
        total = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE user_id = ? AND archived = 0", (user_id,)
        ).fetchone()[0]
        archived = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE user_id = ? AND archived = 1", (user_id,)
        ).fetchone()[0]

        by_category = {}
        rows = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM memories WHERE user_id = ? AND archived = 0 GROUP BY category",
            (user_id,),
        ).fetchall()
        for r in rows:
            by_category[r["category"]] = r["cnt"]

        by_importance = {}
        rows = conn.execute(
            "SELECT importance, COUNT(*) as cnt FROM memories WHERE user_id = ? AND archived = 0 GROUP BY importance",
            (user_id,),
        ).fetchall()
        for r in rows:
            by_importance[r["importance"]] = r["cnt"]

        # 热门标签
        tags = conn.execute(
            "SELECT tag, count FROM memory_tags WHERE user_id = ? ORDER BY count DESC LIMIT 10",
            (user_id,),
        ).fetchall()

        conn.close()

        return {
            "total": total,
            "archived": archived,
            "by_category": by_category,
            "by_importance": by_importance,
            "top_tags": [{"tag": t["tag"], "count": t["count"]} for t in tags],
            "categories": MEMORY_CATEGORIES,
            "importance_levels": IMPORTANCE_LEVELS,
        }

    def apply_decay(self, user_id: str, days: int = 30):
        """应用记忆衰减 — 旧且不重要的记忆自动降权"""
        conn = get_db()
        threshold = (datetime.now() - timedelta(days=days)).isoformat()
        conn.execute(
            """UPDATE memories SET decay_factor = decay_factor * 0.9
               WHERE user_id = ? AND created_at < ? AND importance IN ('low', 'medium')
               AND access_count < 3 AND archived = 0""",
            (user_id, threshold),
        )
        conn.commit()
        conn.close()

    def export(self, user_id: str) -> list[dict]:
        """导出所有记忆为 JSON"""
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM memories WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ).fetchall()
        conn.close()
        return [self._row_to_dict(r) for r in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """将数据库行转为字典"""
        d = dict(row)
        d["tags"] = json.loads(d.get("tags", "[]"))
        d["archived"] = bool(d.get("archived", 0))
        return d


# 全局单例
memory_store = MemoryStore()
