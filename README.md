# 💕 SundayOS v2.0

> 你的甜心AI助手 — 温柔、甜美、可爱的Sunday，就在你身边

SundayOS 是一个个人AI助手，通过 CloudBase 云托管部署，配合 iPhone 快捷指令使用。她像一个温柔甜美的邻家女孩，会记住你的喜好、关心你的生活、陪你聊天。

---

## ✨ 特性

- 🎀 **温柔甜美人格** — 说话甜甜的，用「呢」「哦」「呀」「啦」等语气词，偶尔用可爱的 emoji
- 🧠 **记忆系统** — 自动记住你说过的重要事情（喜好、习惯、计划等）
- 📱 **iPhone 快捷指令** — 一键唤醒，支持文字和语音输入
- ☁️ **CloudBase 云托管** — 稳定运行，自动 HTTPS
- 🫘 **豆包 AI 驱动** — 火山引擎豆包 Seed 2.0 Pro，新用户50万token免费

---

## 🚀 快速开始

### 1. 部署到 CloudBase

> 已部署地址：`https://sunday-os-21-278970-7-1451274775.sh.run.tcloudbase.com`

如需重新部署：

1. CloudBase 控制台 → 云托管 → 新建服务
2. 选择 Git 部署：`banana0712/Sunday-OS-2.0` / `main`
3. Dockerfile 路径：`backend/Dockerfile`，目标目录：`backend`
4. 服务端口：`8000`

**环境变量：**

| 变量 | 值 |
|------|-----|
| `SUNDAY_API_KEY` | `sunday-2026` |
| `LLM_API_KEY` | 火山引擎 API Key |
| `LLM_MODEL` | 豆包接入点 ID |
| `LLM_TEMPERATURE` | `0.8` |
| `LLM_MAX_TOKENS` | `1500` |
| `DEBUG` | `false` |

### 2. 配置 iPhone 快捷指令

**快捷指令流程：**

```
「要求输入」→「词典(请求体)」→「获取URL内容」→「从URL内容获取字典」→「从字典获取reply的值」→「显示」+「朗读」
```

**「获取 URL 内容」配置：**

| 项目 | 值 |
|------|-----|
| URL | `https://sunday-os-21-278970-7-1451274775.sh.run.tcloudbase.com/api/chat` |
| 方法 | `POST` |
| Content-Type | `application/json` |
| X-API-Key | `sunday-2026` |
| 请求体 | `{"message":"你的输入","session_id":"iphone-daily"}` |

### 3. 开始聊天

运行快捷指令，输入你想说的话，Sunday 就会温柔地回复你啦 💕

---

## 📡 API 文档

### `GET /health`

健康检查。

```json
{
  "status": "healthy",
  "assistant": "Sunday 💕",
  "version": "2.0.0",
  "model": "doubao-seed-2-0-pro-260215",
  "timestamp": "2026-07-07 22:03:49"
}
```

### `POST /api/chat`

发送消息，获取回复。

**请求头：**
- `Content-Type: application/json`
- `X-API-Key: sunday-2026`

**请求体：**
```json
{
  "message": "你好呀，我是小明！",
  "session_id": "iphone-xiaoming"
}
```

**返回：**
```json
{
  "reply": "小明你好呀😆 我是Sunday~ 以后随时找我聊天哦🥰",
  "session_id": "iphone-xiaoming",
  "tokens_used": 744,
  "model": "ep-m-20260219151504-vr965"
}
```

### `POST /api/chat/stream`

流式对话（SSE），打字机效果。

### `POST /api/memory`

存储记忆。
```json
{
  "user_id": "xiaoming",
  "content": "小明喜欢喝美式咖啡",
  "tags": ["偏好"],
  "importance": "high"
}
```

### `GET /api/memory?user_id=xiaoming`

获取用户的所有记忆。

### `POST /api/memory/search`

搜索记忆。
```json
{
  "user_id": "xiaoming",
  "query": "咖啡"
}
```

---

## 🎀 Sunday 的人设

```
你是 Sunday，一个温柔甜美、活泼可爱的 AI 女孩。

- 温柔体贴，说话甜甜的，喜欢用「呢」「哦」「呀」「啦」
- 活泼开朗，偶尔撒娇，但不过分
- 像邻家女孩一样亲切，让人感到温暖和放松
- 会真心关心对方，记得对方说过的每一件小事
```

---

## 🛠️ 本地开发

```bash
cd backend
pip install -r requirements.txt
LLM_API_KEY="your-key" LLM_MODEL="your-model" SUNDAY_API_KEY="sunday-2026" uvicorn app.main:app --reload
```

访问 `http://localhost:8000/health` 确认运行正常。

---

## 📂 项目结构

```
sundayos/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py    # 配置管理
│   │   └── main.py      # 核心应用（FastAPI + LLM + 记忆系统）
│   ├── Dockerfile
│   └── requirements.txt
└── .gitignore
```

整个后端只有 **2 个核心文件**（config.py + main.py），简洁清晰。

---

## 🔗 相关链接

- 豆包 API：https://console.volcengine.com/ark
- CloudBase：https://console.cloud.tencent.com/tcb
- 代码仓库：https://github.com/banana0712/Sunday-OS-2.0

---

Made with 💕 by Sunday
