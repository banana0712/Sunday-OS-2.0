# 🌸 SundayOS

> 你的温柔甜心AI助手 — 不只是工具，而是真正了解你、陪伴你的伙伴

---

## 🎯 是什么

SundayOS 是一个个人 AI 助手后端服务，专为 iPhone 设计。通过 iOS 快捷指令调用，实现语音/文字交互。她拥有**持久记忆系统**和**甜美人格**，能记住你的喜好、行程、项目、习惯，越用越懂你。

```
你 → iOS快捷指令 → SundayOS → 豆包大模型 → 甜美回复
                         ↓
                    SQLite 记忆系统
```

---

## ✨ 核心能力

| 能力 | 说明 |
|------|------|
| 🧠 **LLM 智能记忆** | 自动分析每句话，提取有价值的信息并分类存储 |
| 📋 **12 类记忆分类** | 事实/偏好/行程/关系/目标/习惯/项目/科研/学习/笔记/健康/财务 |
| 🔗 **深度上下文联动** | 聊天时主动联想相关记忆，像老朋友一样自然 |
| 👤 **动态用户画像** | 自动构建你的个人画像，每次对话都带上下文 |
| 🎭 **智能模型切换** | 日常聊天用 Character 模型，专业话题自动切 Pro |
| 💕 **甜美人格** | 温柔、体贴、活泼、偶尔撒娇的 AI 女孩 |
| 💾 **持久化存储** | Railway Volume 挂载，重启不丢数据 |
| 🔄 **自动去重** | 同内容不重复存储，自动更新 |

---

## 🏗️ 技术架构

```
sundayos/
├── backend/
│   ├── Dockerfile          # Docker 镜像定义
│   ├── requirements.txt    # Python 依赖
│   └── app/
│       ├── config.py       # 配置管理（环境变量）
│       ├── main.py         # FastAPI 主应用 + 聊天 API
│       └── memory.py       # SQLite 记忆系统（核心）
└── README.md
```

- **框架**: FastAPI + Uvicorn
- **LLM**: 字节跳动豆包（Character + Pro 双模型）
- **存储**: SQLite + Railway Volume
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
  "session_id": "iphone-xiaoming"
}
```

响应：
```json
{
  "reply": "小明你好呀～很高兴认识你呢！✨",
  "session_id": "iphone-xiaoming",
  "tokens_used": 350,
  "model": "ep-m-20260707225516-zws7x",
  "memories_stored": 1
}
```

### 记忆管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/memory/stats?user_id=xxx` | GET | 记忆统计（按分类/重要性/标签） |
| `/api/memory?user_id=xxx` | GET | 列出记忆（支持分类/重要性筛选） |
| `/api/memory` | POST | 手动添加记忆 |
| `/api/memory/search` | POST | 关键词搜索记忆 |
| `/api/memory/{id}` | PUT | 更新记忆 |
| `/api/memory/{id}` | DELETE | 删除记忆 |
| `/api/memory/{id}/archive` | POST | 归档记忆 |
| `/api/memory/{id}/linked` | GET | 查看关联记忆 |
| `/api/memory/link` | POST | 手动关联两条记忆 |
| `/api/memory/export?user_id=xxx` | GET | 导出所有记忆 |
| `/api/memory/decay?user_id=xxx` | POST | 触发记忆衰减 |

### 健康检查

```bash
GET /health
```

---

## 📲 iOS 快捷指令配置

### 步骤

1. 新建快捷指令 → 添加「听写文本」或「要求输入」
2. 添加「获取 URL 内容」：
   - URL: `https://sunday-os-production-1cd2.up.railway.app/api/chat`
   - 方法: `POST`
   - 头部: `X-API-Key` = `sunday-2026`
   - 头部: `Content-Type` = `application/json`
   - 请求体: `{"message":"[输入的文本]","session_id":"iphone-你的名字"}`
   - 超时: 30 秒
3. 添加「获取字典值」：键 = `reply`
4. 添加「显示结果」和「朗读文本」

---

## 🔧 部署

### 环境变量

| 变量 | 说明 |
|------|------|
| `SUNDAY_API_KEY` | API 认证密钥 |
| `LLM_API_KEY` | 豆包 API Key |
| `LLM_MODEL` | 聊天模型 endpoint ID |
| `LLM_MODEL_PRO` | 专业模型 endpoint ID |
| `LLM_TEMPERATURE` | 生成温度 (0.0-1.0) |
| `LLM_MAX_TOKENS` | 最大输出 token 数 |

### 一键部署

```bash
cd backend
railway up --detach
```

---

## 📊 记忆系统详解

详见 [`ARCHITECTURE.md`](./ARCHITECTURE.md) — 包含完整的数据库 Schema、数据流、检索算法说明。

---

## 🎨 设计理念

详见 [`DESIGN.md`](./DESIGN.md) — Sunday 的人格设计、交互哲学和成长愿景。

---

**SundayOS v2.0** — 你的外置大脑，你的甜心伙伴 💕
