"""
SundayOS 记忆系统 v3 — LLM智能分类 + 深度自动提取 + 去重 + 关联
"""
import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
from pathlib import Path
from typing import Optional

DB_PATH = Path("/app/data/sunday_memory.db")


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'fact',
            content TEXT NOT NULL,
            summary TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            importance TEXT DEFAULT 'medium',
            source TEXT DEFAULT 'manual',
            access_count INTEGER DEFAULT 0,
            decay_factor REAL DEFAULT 1.0,
            related_to TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_accessed TEXT,
            archived INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id, status);
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

        CREATE TABLE IF NOT EXISTS memory_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            memory_id_a TEXT NOT NULL,
            memory_id_b TEXT NOT NULL,
            relation TEXT DEFAULT 'related',
            created_at TEXT NOT NULL,
            UNIQUE(memory_id_a, memory_id_b)
        );

        CREATE TABLE IF NOT EXISTS conversation_flow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tokens_used INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_flow_user_time ON conversation_flow(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS push_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            push_type TEXT NOT NULL,
            message TEXT DEFAULT '',
            pushed_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_push_user_type ON push_log(user_id, push_type, pushed_at DESC);

        CREATE TABLE IF NOT EXISTS knowledge_base (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            kb_type TEXT NOT NULL DEFAULT 'science_fact',
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT DEFAULT '[]',
            source_url TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            pushed_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_kb_user ON knowledge_base(user_id, pushed_at DESC);

        CREATE TABLE IF NOT EXISTS feedback (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            fb_type TEXT NOT NULL DEFAULT 'improvement',
            title TEXT NOT NULL,
            detail TEXT DEFAULT '',
            source TEXT DEFAULT 'telegram',
            status TEXT DEFAULT 'open',
            ai_category TEXT DEFAULT '',
            priority TEXT DEFAULT 'medium',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id, status);
    """)

    # 自动迁移：为新列添加缺失的列
    _migrate(conn)

    conn.commit()
    conn.close()

    # 初始化日志表
    from app.logger import init_log_table
    init_log_table()


def _migrate(conn: sqlite3.Connection):
    """自动检测并添加缺失的列"""
    # memories 表迁移
    existing = {row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()}
    migrations = {
        "summary": "TEXT DEFAULT ''",
        "related_to": "TEXT DEFAULT ''",
        "status": "TEXT DEFAULT 'active'",
    }
    for col, col_type in migrations.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE memories ADD COLUMN {col} {col_type}")

    # feedback 表迁移
    fb_existing = {row[1] for row in conn.execute("PRAGMA table_info(feedback)").fetchall()}
    fb_migrations = {
        "ai_category": "TEXT DEFAULT ''",
        "priority": "TEXT DEFAULT 'medium'",
    }
    for col, col_type in fb_migrations.items():
        if col not in fb_existing:
            conn.execute(f"ALTER TABLE feedback ADD COLUMN {col} {col_type}")


# ============================================================
# 记忆类别（扩展版）
# ============================================================
MEMORY_CATEGORIES = {
    "fact":           "📋 事实",          # "我是iOS开发者" "我住在北京"
    "preference":     "💝 偏好",          # "喜欢美式咖啡" "讨厌下雨天"
    "event":          "📅 行程",          # "明天下午3点面试" "下周去上海"
    "relationship":   "👥 关系",          # "女朋友叫小红" "同事老王"
    "goal":           "🎯 目标",          # "今年想学钢琴" "计划买房"
    "habit":          "🔄 习惯",          # "每天7点起床" "每周健身3次"
    "project":        "💼 项目",          # "正在做电商App" "负责公司CRM系统"
    "research":       "🔬 科研",          # "研究方向是NLP" "在写论文"
    "learning":       "📚 学习",          # "在学SwiftUI" "读完了设计模式"
    "note":           "📝 笔记",          # 通用笔记、临时备忘
    "health":         "❤️ 健康",          # "过敏花粉" "血压偏高"
    "finance":        "💰 财务",          # "每月房贷8000" "买了比特币"
}

IMPORTANCE_LEVELS = {
    "low":      {"score": 0.3, "label": "⭐ 一般"},
    "medium":   {"score": 0.5, "label": "⭐⭐ 重要"},
    "high":     {"score": 0.7, "label": "⭐⭐⭐ 很重要"},
    "critical": {"score": 1.0, "label": "💎 核心记忆"},
}

# 记忆提取提示词
MEMORY_EXTRACTION_PROMPT = """你是 Sunday 的记忆系统。分析用户的消息，提取值得长期记住的信息。你要像一个关心朋友的女孩一样，判断什么该记住、什么只是闲聊。

## 记忆类别
- fact: 个人事实（姓名、职业、住址、学历、技能等）
- preference: 喜好偏好（喜欢/讨厌的食物、音乐、颜色、品牌等）
- event: 行程安排（会议、约会、旅行、面试、deadline、纪念日等）
- relationship: 人际关系（家人、朋友、同事、伴侣的名字和关系）
- goal: 目标计划（学习计划、职业目标、人生规划、想做的事）
- habit: 生活习惯（作息、饮食、运动、工作习惯等）
- project: 工作项目（正在做的项目、负责的任务、技术栈、进度等）
- research: 科研学术（研究方向、论文、实验、学术兴趣、导师等）
- learning: 学习成长（在学的技能、课程、书籍、学习心得、考证等）
- note: 值得记住的其他信息
- health: 健康信息（过敏、病史、运动数据、饮食限制等）
- finance: 财务信息（收入、支出、投资、贷款、资产等）

## 重要性判断
- critical: 核心身份信息（姓名、伴侣、住址）、重要健康信息
- high: 职业、学历、长期目标、重要项目、过敏信息
- medium: 日常偏好、一般行程、短期计划、普通关系
- low: 临时笔记、一次性事件

## 提取原则（极其重要！）
1. **只提取真正有价值的信息**。闲聊、情绪表达、玩笑、临时话题不要提取
2. **用户自称的名字/昵称要记**，但必须是用户明确说"我叫XX"或"你可以叫我XX"，不要从上下文猜测
3. **不要提取模糊/不完整的信息**：
   - 错误："昵称是啥"（这不是信息，是问题）
   - 错误："用户称Sunday为…？"（不完整，有问号）
   - 错误："你想叫我啥"（这不是事实，是反问）
4. 每条记忆用一句简洁完整的话概括（不要照搬原话，不要带问号）
5. tags 是关键词标签，用于未来检索（用中文）
6. 如果一句话包含多个独立信息，拆成多条记忆
7. 如果消息不包含任何可记忆内容，返回空数组 []
8. **质量检查**：如果 summary 里有问号、省略号、或者明显是不完整的句子，不要提取

## 输入
用户消息: {message}

## 输出格式（只返回 JSON 数组）
[
  {{"category": "preference", "summary": "喜欢喝美式咖啡，每天两杯", "tags": ["咖啡", "美式"], "importance": "medium"}},
  {{"category": "fact", "summary": "职业是iOS开发者", "tags": ["iOS", "开发者"], "importance": "high"}}
]

如果没有可提取的记忆，返回: []"""


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
        summary: str = "",
        tags: list[str] = None,
        importance: str = "medium",
        source: str = "manual",
        related_to: str = "",
    ) -> dict:
        """存储一条记忆，自动去重"""
        # 先去重
        existing = self._find_duplicate(user_id, summary or content, category)
        if existing:
            # 更新已存在的记忆
            return self._refresh_existing(existing["id"], content, summary, tags)

        now = datetime.now(TZ).isoformat()
        mem_id = f"mem_{uuid.uuid4().hex[:12]}"
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        conn = get_db()
        conn.execute(
            """INSERT INTO memories (id, user_id, category, content, summary, tags, importance, source, related_to, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mem_id, user_id, category, content, summary or content, tags_json, importance, source, related_to, now, now),
        )

        for tag in (tags or []):
            conn.execute(
                """INSERT INTO memory_tags (user_id, tag, count) VALUES (?, ?, 1)
                   ON CONFLICT(user_id, tag) DO UPDATE SET count = count + 1""",
                (user_id, tag),
            )

        conn.commit()
        conn.close()

        # 自动关联：找到与新记忆标签匹配的已有记忆
        if tags:
            self._auto_link(user_id, mem_id, tags)

        return self.get(mem_id)

    def _auto_link(self, user_id: str, new_mem_id: str, tags: list[str]):
        """自动关联：基于标签匹配找到相关的已有记忆"""
        if not tags:
            return
        conn = get_db()
        # 查找标签重叠的已有记忆
        placeholders = ",".join(["?" for _ in tags])
        rows = conn.execute(
            f"""SELECT DISTINCT m.id FROM memories m
                WHERE m.user_id = ? AND m.id != ? AND m.archived = 0
                AND m.id IN (
                    SELECT memory_id_a FROM memory_links WHERE user_id = ?
                    UNION SELECT memory_id_b FROM memory_links WHERE user_id = ?
                ) = 0
                ORDER BY m.created_at DESC LIMIT 5""",
            (user_id, new_mem_id, user_id, user_id),
        ).fetchall()
        conn.close()

        # 通过标签匹配
        for row in rows:
            existing = self.get(row["id"])
            if existing and set(tags) & set(existing.get("tags", [])):
                self.link_memories(user_id, new_mem_id, row["id"], "auto")

    def _find_duplicate(self, user_id: str, content: str, category: str) -> Optional[dict]:
        """查找相似记忆（简单去重）"""
        conn = get_db()
        # 同分类下找内容高度相似的
        row = conn.execute(
            """SELECT * FROM memories WHERE user_id = ? AND category = ? AND archived = 0
               ORDER BY created_at DESC LIMIT 5""",
            (user_id, category),
        ).fetchall()
        conn.close()

        content_short = content[:30]
        for r in row:
            d = dict(r)
            existing = (d.get("summary", "") or d.get("content", ""))[:30]
            if content_short == existing:
                return d
        return None

    def _refresh_existing(self, mem_id: str, content: str, summary: str, tags: list[str]) -> dict:
        """刷新已存在的记忆（更新时间、增加访问计数）"""
        conn = get_db()
        now = datetime.now(TZ).isoformat()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        conn.execute(
            """UPDATE memories SET content = ?, summary = ?, tags = ?, updated_at = ?,
               access_count = access_count + 1 WHERE id = ?""",
            (content, summary or content, tags_json, now, mem_id),
        )
        conn.commit()
        conn.close()
        return self.get(mem_id)

    def get(self, mem_id: str) -> Optional[dict]:
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
        status: str = "active",
        limit: int = 20,
        offset: int = 0,
        include_archived: bool = False,
    ) -> list[dict]:
        conn = get_db()
        conditions = ["user_id = ?"]
        params = [user_id]

        if not include_archived:
            conditions.append("archived = 0")
        
        if status:
            conditions.append("status = ?")
            params.append(status)

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

        if query and results:
            query_lower = query.lower()
            scored = []
            for r in results:
                score = 0
                text = (r["summary"] + " " + r["content"]).lower()
                for word in query_lower.split():
                    if word in text:
                        score += 2
                for tag in r["tags"]:
                    if tag.lower() in query_lower:
                        score += 3
                score *= IMPORTANCE_LEVELS.get(r["importance"], {"score": 0.5})["score"] * 2
                score *= (1 + 0.05 * r["access_count"])
                scored.append((score, r))
            scored.sort(key=lambda x: x[0], reverse=True)
            results = [r for _, r in scored]

        # 记录访问
        for r in results:
            self.record_access(r["id"])

        return results

    def get_context(self, user_id: str, limit: int = 15, message: str = "") -> str:
        """获取给 LLM 用的记忆上下文，按相关性排序，高重要性优先"""
        if message:
            mems = self.search(user_id, query=message, limit=limit)
        else:
            mems = self.search(user_id, limit=limit)

        if not mems:
            return "暂无关于用户的记忆"

        # 按分类分组，每类最多取3条
        grouped = {}
        for m in mems:
            cat = m["category"]
            if cat not in grouped:
                grouped[cat] = []
            if len(grouped[cat]) < 3:
                grouped[cat].append(m)

        # 重要类别优先排序
        priority_order = ["fact", "preference", "event", "project", "relationship", "goal", "habit", "research", "learning", "health", "finance", "note"]
        sorted_cats = sorted(grouped.keys(), key=lambda c: priority_order.index(c) if c in priority_order else 99)

        lines = []
        for cat in sorted_cats:
            cat_label = MEMORY_CATEGORIES.get(cat, cat)
            for m in grouped[cat]:
                imp = IMPORTANCE_LEVELS.get(m["importance"], {}).get("label", "")
                summary = m.get("summary") or m["content"]
                lines.append(f"[{cat_label} | {imp}] {summary}")

        return "\n".join(lines)

    def update(self, mem_id: str, **kwargs) -> Optional[dict]:
        conn = get_db()
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (mem_id,)).fetchone()
        if not row:
            conn.close()
            return None

        allowed = ["content", "summary", "category", "importance", "tags", "related_to"]
        updates = {}
        for k in allowed:
            if k in kwargs:
                if k == "tags":
                    updates[k] = json.dumps(kwargs[k], ensure_ascii=False)
                else:
                    updates[k] = kwargs[k]

        if updates:
            updates["updated_at"] = datetime.now(TZ).isoformat()
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE memories SET {set_clause} WHERE id = ?", list(updates.values()) + [mem_id])
            conn.commit()

        conn.close()
        return self.get(mem_id)

    def delete(self, mem_id: str) -> bool:
        conn = get_db()
        conn.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
        conn.execute("DELETE FROM memory_links WHERE memory_id_a = ? OR memory_id_b = ?", (mem_id, mem_id))
        deleted = conn.total_changes > 0
        conn.commit()
        conn.close()
        return deleted

    def archive(self, mem_id: str) -> bool:
        return self.update(mem_id, archived=1) is not None

    def unarchive(self, mem_id: str) -> bool:
        return self.update(mem_id, archived=0) is not None

    def record_access(self, mem_id: str):
        conn = get_db()
        conn.execute(
            "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
            (datetime.now(TZ).isoformat(), mem_id),
        )
        conn.commit()
        conn.close()

    def link_memories(self, user_id: str, mem_id_a: str, mem_id_b: str, relation: str = "related"):
        """关联两条记忆"""
        conn = get_db()
        now = datetime.now(TZ).isoformat()
        conn.execute(
            """INSERT OR IGNORE INTO memory_links (user_id, memory_id_a, memory_id_b, relation, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, mem_id_a, mem_id_b, relation, now),
        )
        conn.commit()
        conn.close()

    def get_linked(self, mem_id: str) -> list[dict]:
        """获取与某条记忆关联的其他记忆"""
        conn = get_db()
        rows = conn.execute(
            """SELECT m.* FROM memories m
               JOIN memory_links l ON (l.memory_id_b = m.id)
               WHERE l.memory_id_a = ? AND m.archived = 0
               UNION
               SELECT m.* FROM memories m
               JOIN memory_links l ON (l.memory_id_a = m.id)
               WHERE l.memory_id_b = ? AND m.archived = 0""",
            (mem_id, mem_id),
        ).fetchall()
        conn.close()
        return [self._row_to_dict(r) for r in rows]

    def get_stats(self, user_id: str) -> dict:
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
            by_category[r["category"]] = {"count": r["cnt"], "label": MEMORY_CATEGORIES.get(r["category"], r["category"])}

        by_importance = {}
        rows = conn.execute(
            "SELECT importance, COUNT(*) as cnt FROM memories WHERE user_id = ? AND archived = 0 GROUP BY importance",
            (user_id,),
        ).fetchall()
        for r in rows:
            by_importance[r["importance"]] = r["cnt"]

        tags = conn.execute(
            "SELECT tag, count FROM memory_tags WHERE user_id = ? ORDER BY count DESC LIMIT 15",
            (user_id,),
        ).fetchall()

        # 最近添加的
        recent = conn.execute(
            "SELECT id, category, summary, content, importance, created_at FROM memories WHERE user_id = ? AND archived = 0 ORDER BY created_at DESC LIMIT 5",
            (user_id,),
        ).fetchall()

        conn.close()

        return {
            "total": total,
            "archived": archived,
            "by_category": by_category,
            "by_importance": by_importance,
            "top_tags": [{"tag": t["tag"], "count": t["count"]} for t in tags],
            "recent": [self._row_to_dict(r) for r in recent],
            "categories": MEMORY_CATEGORIES,
            "importance_levels": IMPORTANCE_LEVELS,
        }

    def apply_decay(self, user_id: str, days: int = 30):
        conn = get_db()
        threshold = (datetime.now(TZ) - timedelta(days=days)).isoformat()
        conn.execute(
            """UPDATE memories SET decay_factor = decay_factor * 0.9
               WHERE user_id = ? AND created_at < ? AND importance IN ('low', 'medium')
               AND access_count < 3 AND archived = 0""",
            (user_id, threshold),
        )
        conn.commit()
        conn.close()

    def export(self, user_id: str) -> list[dict]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM memories WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ).fetchall()
        conn.close()
        return [self._row_to_dict(r) for r in rows]

    # ============================================================
    # 对话流（短期工作记忆）
    # ============================================================
    def add_conversation(self, user_id: str, role: str, content: str, tokens: int = 0):
        """记录一条对话到对话流"""
        conn = get_db()
        now = datetime.now(TZ).isoformat()
        conn.execute(
            "INSERT INTO conversation_flow (user_id, role, content, tokens_used, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, role, content, tokens, now),
        )
        conn.commit()
        conn.close()

    def get_conversation_context(self, user_id: str, max_turns: int = 10) -> str:
        """获取对话流上下文，两级衰减：
           🔥 24h内：完整对话（最近10轮）
           🌤 24-72h：每轮压缩为一句摘要
           ❄️ >72h：不注入（重要信息已在长期记忆中）
        """
        conn = get_db()
        now = datetime.now(TZ)
        hot_cutoff = (now - timedelta(hours=24)).isoformat()
        warm_cutoff = (now - timedelta(hours=72)).isoformat()

        # 🔥 热记忆：24h内完整对话
        hot_rows = conn.execute(
            """SELECT role, content FROM conversation_flow
               WHERE user_id = ? AND created_at > ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, hot_cutoff, max_turns * 2),
        ).fetchall()

        # 🌤 温记忆：24-72h，压缩为摘要
        warm_rows = conn.execute(
            """SELECT role, content, created_at FROM conversation_flow
               WHERE user_id = ? AND created_at > ? AND created_at <= ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, warm_cutoff, hot_cutoff, max_turns * 2),
        ).fetchall()

        conn.close()

        parts = []

        # 热记忆：完整展示
        if hot_rows:
            hot_rows = list(reversed(hot_rows))
            lines = []
            for r in hot_rows:
                role_label = "👤" if r["role"] == "user" else "💕Sunday"
                content = r["content"]
                if len(content) > 120:
                    content = content[:120] + "..."
                lines.append(f"{role_label}: {content}")
            parts.append("## 最近的对话\n" + "\n".join(lines))

        # 温记忆：压缩摘要
        if warm_rows:
            warm_rows = list(reversed(warm_rows))
            summaries = []
            # 按轮次分组（user+assistant交替）
            i = 0
            while i < len(warm_rows):
                user_msg = ""
                sunday_msg = ""
                if i < len(warm_rows) and warm_rows[i]["role"] == "user":
                    user_msg = warm_rows[i]["content"][:60]
                    i += 1
                if i < len(warm_rows) and warm_rows[i]["role"] == "assistant":
                    sunday_msg = warm_rows[i]["content"][:60]
                    i += 1
                if user_msg:
                    summaries.append(f"用户提到了「{user_msg}」")
                if sunday_msg:
                    summaries.append(f"Sunday回应了「{sunday_msg}」")
            if summaries:
                parts.append("## 之前的对话（记忆模糊）\n" + "\n".join(summaries[-6:]))

        return "\n\n".join(parts) if parts else ""

    def cleanup_old_conversations(self, user_id: str, keep_hours: int = 72):
        """清理超过指定时间的对话流"""
        conn = get_db()
        cutoff = (datetime.now(TZ) - timedelta(hours=keep_hours)).isoformat()
        conn.execute("DELETE FROM conversation_flow WHERE user_id = ? AND created_at < ?", (user_id, cutoff))
        deleted = conn.total_changes
        conn.commit()
        conn.close()
        return deleted

    # ============================================================
    # 推送追踪（避免重复推送）
    # ============================================================
    def _get_last_push(self, user_id: str, push_type: str) -> datetime | None:
        """获取上次推送时间"""
        conn = get_db()
        row = conn.execute(
            "SELECT pushed_at FROM push_log WHERE user_id = ? AND push_type = ? ORDER BY pushed_at DESC LIMIT 1",
            (user_id, push_type),
        ).fetchone()
        conn.close()
        if row:
            try:
                return datetime.fromisoformat(row["pushed_at"])
            except Exception:
                return None
        return None

    def _record_push(self, user_id: str, push_type: str, message: str = ""):
        """记录一次推送"""
        conn = get_db()
        now = datetime.now(TZ).isoformat()
        conn.execute(
            "INSERT INTO push_log (user_id, push_type, message, pushed_at) VALUES (?, ?, ?, ?)",
            (user_id, push_type, message, now),
        )
        conn.commit()
        conn.close()

    def _get_last_interaction(self, user_id: str) -> datetime | None:
        """获取用户最后一次互动时间"""
        conn = get_db()
        row = conn.execute(
            "SELECT created_at FROM conversation_flow WHERE user_id = ? AND role = 'user' ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        conn.close()
        if row:
            try:
                return datetime.fromisoformat(row["created_at"])
            except Exception:
                return None
        return None

    def get_daily_push_count(self, user_id: str) -> int:
        """获取今日已推送次数"""
        conn = get_db()
        today = datetime.now(TZ).strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM push_log WHERE user_id = ? AND pushed_at >= ?",
            (user_id, today),
        ).fetchone()
        conn.close()
        return row["cnt"] if row else 0

    def get_memories_since(self, user_id: str, since_days: int = 7) -> list[dict]:
        """获取指定天数内的记忆（用于周报等）"""
        conn = get_db()
        since_date = (datetime.now(TZ) - timedelta(days=since_days)).isoformat()
        rows = conn.execute(
            "SELECT * FROM memories WHERE user_id = ? AND created_at >= ? ORDER BY access_count DESC",
            (user_id, since_date),
        ).fetchall()
        conn.close()
        return [self._row_to_dict(r) for r in rows]

    def get_conversation_count_since(self, user_id: str, since_days: int = 7) -> int:
        """获取指定天数内的对话轮数"""
        conn = get_db()
        since_date = (datetime.now(TZ) - timedelta(days=since_days)).isoformat()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM conversation_flow WHERE user_id = ? AND role = 'user' AND created_at >= ?",
            (user_id, since_date),
        ).fetchone()
        conn.close()
        return row["cnt"] if row else 0

    # ============================================================
    # 知识库
    # ============================================================
    def add_knowledge(self, user_id: str, kb_type: str, title: str, content: str,
                      tags: list = None, source_url: str = "", image_url: str = "") -> str:
        """添加一条知识到知识库"""
        conn = get_db()
        now = datetime.now(TZ).isoformat()
        kb_id = f"kb_{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO knowledge_base (id, user_id, kb_type, title, content, tags, source_url, image_url, pushed_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kb_id, user_id, kb_type, title, content,
             json.dumps(tags or [], ensure_ascii=False), source_url, image_url, now, now),
        )
        conn.commit()
        conn.close()
        return kb_id

    def get_knowledge(self, user_id: str, kb_type: str = None, limit: int = 10) -> list[dict]:
        """获取知识库条目"""
        conn = get_db()
        if kb_type:
            rows = conn.execute(
                "SELECT * FROM knowledge_base WHERE user_id = ? AND kb_type = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, kb_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM knowledge_base WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d.get("tags", "[]"))
            result.append(d)
        return result

    def get_today_knowledge_count(self, user_id: str) -> int:
        """获取今日已推送知识条数"""
        conn = get_db()
        today = datetime.now(TZ).strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge_base WHERE user_id = ? AND pushed_at >= ?",
            (user_id, today),
        ).fetchone()
        conn.close()
        return row["cnt"] if row else 0

    # ============================================================
    # 改进反馈系统
    # ============================================================
    def add_feedback(self, user_id: str, fb_type: str, title: str, detail: str = "",
                     source: str = "telegram", ai_category: str = "", priority: str = "medium") -> str:
        """添加一条改进反馈"""
        conn = get_db()
        now = datetime.now(TZ).isoformat()
        fb_id = f"fb_{uuid.uuid4().hex[:8]}"
        conn.execute(
            """INSERT INTO feedback (id, user_id, fb_type, title, detail, source, status, ai_category, priority, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
            (fb_id, user_id, fb_type, title, detail, source, ai_category, priority, now, now),
        )
        conn.commit()
        conn.close()
        return fb_id

    def get_feedback(self, user_id: str, fb_type: str = "", status: str = "open", limit: int = 20) -> list[dict]:
        """查询改进反馈"""
        conn = get_db()
        conditions = ["user_id = ?"]
        params = [user_id]
        if fb_type:
            conditions.append("fb_type = ?")
            params.append(fb_type)
        if status:
            conditions.append("status = ?")
            params.append(status)
        
        rows = conn.execute(
            f"SELECT * FROM feedback WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_feedback(self, fb_id: str, **kwargs) -> bool:
        """更新反馈状态"""
        conn = get_db()
        allowed = ["status", "title", "detail", "fb_type", "ai_category", "priority"]
        updates = {k: kwargs[k] for k in allowed if k in kwargs}
        if not updates:
            conn.close()
            return False
        updates["updated_at"] = datetime.now(TZ).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE feedback SET {set_clause} WHERE id = ?", list(updates.values()) + [fb_id])
        conn.commit()
        conn.close()
        return True

    # ============================================================
    # 记忆状态管理
    # ============================================================
    def set_memory_status(self, mem_id: str, status: str) -> bool:
        """修改记忆状态: active / archived"""
        if status not in ("active", "archived"):
            return False
        conn = get_db()
        now = datetime.now(TZ).isoformat()
        conn.execute(
            "UPDATE memories SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, mem_id),
        )
        updated = conn.total_changes > 0
        conn.commit()
        conn.close()
        return updated

    def list_active_memories(self, user_id: str, limit: int = 20) -> list[dict]:
        """列出所有 active 记忆，按分类分组"""
        return self.search(user_id, status="active", limit=limit)

    def list_archived_memories(self, user_id: str, limit: int = 20) -> list[dict]:
        """列出所有 archived 记忆"""
        return self.search(user_id, status="archived", limit=limit)

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["tags"] = json.loads(d.get("tags", "[]"))
        d["archived"] = bool(d.get("archived", 0))
        return d


# 全局单例
memory_store = MemoryStore()
