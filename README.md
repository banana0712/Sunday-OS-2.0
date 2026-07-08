# 🌸 SundayOS

> 你的温柔甜心AI助手 — 不只是工具，而是真正了解你、陪伴你的伙伴

---

## 🎯 是什么

SundayOS 是一个个人 AI 助手后端服务，专为 iPhone 设计。通过 iOS 快捷指令 + Telegram Bot + 邮件推送，实现多通道交互。她拥有**记忆系统**、**AI 设计引擎**、**知识推送**和**甜美人格**，能记住你的喜好、帮你写报告、推送知识、像真人一样分段聊天。

```
你 → iOS快捷指令 / Telegram / 邮件 → SundayOS → 豆包大模型 → 甜美回复
                         ├── SQLite 记忆系统（质量过滤）
                         ├── DuckDuckGo 网络搜索
                         ├── AI 原生邮件设计引擎
                         ├── Word 报告生成（python-docx）
                         ├── 知识推送（科学/时事/词条）
                         └── 对话流上下文 + 智能分段
```

---

## ✨ 核心能力

| 能力 | 说明 |
|------|------|
| 🧠 **LLM 智能记忆** | 自动分析每句话，质量过滤，提取有价值的信息并分类存储 |
| 📋 **12 类记忆分类** | 事实/偏好/行程/关系/目标/习惯/项目/科研/学习/笔记/健康/财务 |
| 🎨 **AI 邮件设计引擎** | 每封邮件由 LLM 自由创作配色/布局/装饰，独一无二 |
| 📝 **Word 报告生成** | 学术/简洁双风格，LLM 搜索+大纲+逐章撰写 |
| 📚 **知识推送** | 科学趣闻/今日词条/思维火花/灵感碎片/时事速览 |
| 💬 **智能分段聊天** | AI 自主判断何时分多条消息，有呼吸感 |
| 🔗 **深度上下文联动** | 聊天时主动联想相关记忆，像老朋友一样自然 |
| 👤 **动态用户画像** | 自动构建你的个人画像，每次对话都带上下文 |
| 🌐 **网络搜索** | DuckDuckGo 实时搜索 + LLM 智能整理 |
| 🎭 **智能模型切换** | 日常聊天用 Character 模型，专业话题自动切 Pro |
| 💕 **甜美人格** | 温柔、体贴、活泼、偶尔撒娇的 AI 女孩 |
| 💾 **持久化存储** | Railway Volume 挂载，重启不丢数据 |
| 🔄 **自动去重** | 同内容不重复存储，自动更新 |
| ⏳ **记忆衰减** | 低重要性旧记忆自动降权 |
| 🛡️ **记忆质量过滤** | 自动过滤反问句/不完整/垃圾信息 |
| 📊 **周报自动生成** | 每周日晚推送数据报告 |
| 🤖 **Telegram Bot** | 实时聊天 + 文件发送 + 命令系统 |
| ✉️ **邮件推送** | 精美 HTML 邮件 + 附件 + IMAP 监听 |

---

## 🏗️ 技术架构

```
sundayos/
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── CHANGELOG.md          # 开发日志
│   └── app/
│       ├── config.py          # 配置管理
│       ├── main.py            # FastAPI 主应用 + 聊天 API
│       ├── memory.py          # SQLite 记忆系统（核心）
│       ├── search.py          # DuckDuckGo 网络搜索
│       ├── mailer.py          # 邮件推送引擎（Resend API）
│       ├── imap_listener.py   # iCloud IMAP 邮件监听
│       ├── telegram_bot.py    # Telegram Bot
│       ├── email_templates.py # AI 邮件设计引擎
│       ├── file_generator.py  # Word/图表生成
│       ├── knowledge_push.py  # 知识推送系统
│       └── logger.py          # 日志系统
├── README.md
├── ARCHITECTURE.md
├── DESIGN.md
└── CHANGELOG.md
```

- **框架**: FastAPI + Uvicorn (Python 3.11)
- **LLM**: 字节跳动豆包（Character + Pro 双模型）
- **存储**: SQLite + Railway Volume
- **搜索**: DuckDuckGo（免费，无需 API Key）
- **邮件**: Resend HTTP API + iCloud IMAP
- **聊天**: python-telegram-bot
- **文档**: python-docx
- **部署**: Railway（美国西部 sfo 区域）

---

## 🚀 API 文档

### 基础信息

| 项目 | 值 |
|------|-----|
| **域名** | `https://sunday-os-production-1cd2.up.railway.app` |
| **认证** | Header `X-API-Key: sunday-2026` |
| **格式** | JSON |

### 聊天

```bash
POST /api/chat
Content-Type: application/json
X-API-Key: sunday-2026

{
  "message": "你好呀，我叫小明",
  "session_id": "iphone-daily"
}
```

### 健康检查

```bash
GET /health
```

### 记忆管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/memory?user_id=xxx` | GET | 列出记忆 |
| `/api/memory` | POST | 手动添加记忆 |
| `/api/memory/{id}` | DELETE | 删除记忆 |
| `/api/memory/{id}/archive` | POST | 归档/恢复记忆 |
| `/api/memory/export?user_id=xxx` | GET | 导出 JSON |
| `/api/memory/export/csv?user_id=xxx` | GET | 导出 CSV |

### 推送

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/push/pending?user_id=xxx` | GET | 检查是否有待推送消息 |
| `/api/push/send` | POST | 手动触发推送 |
| `/api/push/test-llm` | POST | 测试 LLM 推送生成 |

### 报告

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/generate/report` | POST | 生成 Word 报告 |

### Dashboard

| 端点 | 方法 | 说明 |
|------|------|------|
| `/dashboard?key=xxx&tab=logs` | GET | 运行日志 |
| `/dashboard?key=xxx&tab=feedback` | GET | 改进计划 |
| `/dashboard?key=xxx&tab=memory` | GET | 记忆管理 |

---

## 📲 多通道交互

| 通道 | 方式 | 说明 |
|------|------|------|
| 📱 **快捷指令** | `POST /api/chat` | iOS 语音/文字输入 |
| 🤖 **Telegram** | `@Sunday_OS_bot` | 实时聊天 + `/report` + `/memory` |
| ✉️ **邮件** | `sunday_os@icloud.com` | 精美推送 + 回复对话 |

---

## 🔧 部署

```bash
cd backend
railway up --service sunday-os --environment production
```

---

**SundayOS v3.0** — 你的外置大脑，你的甜心伙伴 💕
