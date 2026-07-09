# Claude 对接 SundayOS 完整指南

> **目标**：让 Claude（或任何 AI 编程助手）能够完整接手 SundayOS 的开发、调试和部署。
> 
> **核心理念**：一份技术文档 + 一个 GitHub 仓库 + Railway CLI = AI 即可独立工作。

---

## 第一步：给 Claude 看技术文档

把这份文件直接发给 Claude：

> **`/workspace/SundayOS_技术文档.md`**（1544 行，涵盖全部架构、模块、API、数据库设计）

这份文档是专门为"AI 模型能理解"而写的，包含：
- 完整的架构图和数据流
- 每个模块的设计原理和代码示例
- 所有 API 端点的请求/响应格式
- 数据库表结构（DDL 级别）
- 设计哲学（为什么这样设计）

**用法**：直接把文件内容粘贴给 Claude，或上传为知识库文件。Claude 读完就能理解整个项目。

---

## 第二步：GitHub 仓库

### 当前状态

```
仓库：https://github.com/banana0712/Sunday-OS-2.0
分支：main
状态：已登录 (gh CLI)
```

### Claude 如何操作 GitHub

Claude 通过 `gh` CLI 工具操作，无需额外配置。常用命令：

```bash
# 克隆项目
git clone https://github.com/banana0712/Sunday-OS-2.0.git

# 查看状态
cd Sunday-OS-2.0 && git status

# 提交代码
git add .
git commit -m "描述你的改动"
git push

# 创建 PR
gh pr create --title "标题" --body "描述"

# 查看 PR
gh pr list
gh pr view <number>
```

**注意**：当前沙箱已经登录了 `banana0712` 账号，Claude 可以直接 push。

---

## 第三步：Railway 部署

### 当前状态

```
项目：sunday-os
环境：production
URL：https://sunday-os-production-1cd2.up.railway.app
Volume：sunday-os-volume (54 MB / 500 MB, 挂载到 /app/data)
区域：sfo (San Francisco)
```

### Claude 如何部署

Claude 通过 `railway` CLI 部署，**必须在 `backend/` 目录下运行**：

```bash
cd /path/to/Sunday-OS-2.0/backend

# 查看状态
railway status

# 部署（推送代码后自动触发，也可以手动）
railway up

# 查看日志
railway logs

# 查看环境变量
railway variables list

# 设置环境变量
railway variables set KEY=VALUE

# 查看服务状态
railway service
```

### 环境变量清单（已配置在 Railway 上，无需本地 .env）

| 变量 | 用途 | 是否已配 |
|------|------|----------|
| `LLM_API_KEY` | 豆包大模型 API Key | ✅ |
| `LLM_MODEL` | 聊天模型名称 | ✅ |
| `LLM_MODEL_PRO` | 专业模型名称 | ✅ |
| `LLM_TEMPERATURE` | LLM 温度 | ✅ |
| `LLM_MAX_TOKENS` | 最大 token 数 | ✅ |
| `RESEND_API_KEY` | 邮件发送 API Key | ✅ |
| `RESEND_FROM_EMAIL` | 发件邮箱 | ✅ |
| `PUSH_EMAIL` | 推送目标邮箱 | ✅ |
| `TELEGRAM_TOKEN` | Telegram Bot Token | ✅ |
| `IMAP_PASSWORD` | iCloud 应用密码 | ✅ |
| `SUNDAY_API_KEY` | API 认证密钥 | ✅ |

**Claude 不需要接触这些敏感值**，Railway 会自动注入到容器中。

---

## 第四步：对接其他服务

### 4.1 豆包大模型（火山引擎）

| 项目 | 信息 |
|------|------|
| 控制台 | https://console.volcengine.com/ark |
| API 地址 | `https://ark.cn-beijing.volces.com/api/v3` |
| 认证方式 | API Key（已配在 Railway 环境变量中） |
| 当前模型 | `ep-m-20260707225516-zws7x`（Endpoint ID） |

**Claude 如何调用**：通过 `AsyncOpenAI` 客户端，`base_url` 指向火山引擎。已在 `config.py` 中封装好，不需要额外配置。

### 4.2 Resend（邮件发送）

| 项目 | 信息 |
|------|------|
| 控制台 | https://resend.com |
| API Key | 已配在 Railway 环境变量中 |
| 发件地址 | `sunday@notifications.sundayos.app` |
| 用量 | 免费套餐 100 封/天 |

**注意**：Resend 需要验证域名。当前使用的是 Resend 默认域名，如果要用自定义域名需要 DNS 配置。

### 4.3 Telegram Bot

| 项目 | 信息 |
|------|------|
| Bot 管理 | https://t.me/BotFather |
| Token | 已配在 Railway 环境变量中 |
| Webhook/长轮询 | 使用 python-telegram-bot 的长轮询模式 |

**Claude 如何调试**：Telegram Bot 通过 `telegram_bot.py` 中的 `setup_bot()` 启动，使用 `application.run_polling()`。部署后自动运行。

### 4.4 iCloud 邮件（IMAP）

| 项目 | 信息 |
|------|------|
| 服务器 | `imap.mail.me.com:993` |
| 账号 | `sunday_os@icloud.com` |
| 应用密码 | 已配在 Railway 环境变量中 |
| 用途 | 监听用户邮件回复，自动回复 |

**获取 iCloud 应用密码**：https://appleid.apple.com → 登录 → 安全 → App 专用密码 → 生成。

### 4.5 火山引擎语音服务（待接入）

语音功能需要额外创建应用：

1. 访问 https://console.volcengine.com/speech/app
2. 创建「语音识别」应用 → 获取 APP Key + Access Key
3. 创建「语音合成」应用 → 获取 APP ID + Access Key
4. 上传 10-30 秒音频 → 克隆声音 → 获取 Speaker ID
5. 添加到 Railway 环境变量：

```bash
cd backend
railway variables set DOUBAO_ASR_APP_KEY=xxx
railway variables set DOUBAO_ASR_ACCESS_KEY=xxx
railway variables set DOUBAO_TTS_APP_ID=xxx
railway variables set DOUBAO_TTS_ACCESS_KEY=xxx
railway variables set DOUBAO_TTS_SPEAKER=S_xxxxxxxxx
```

---

## 第五步：本地开发环境

### 给 Claude 的快速启动命令

```bash
# 1. 克隆项目
git clone https://github.com/banana0712/Sunday-OS-2.0.git
cd Sunday-OS-2.0/backend

# 2. 安装依赖
pip install -r requirements.txt

# 3. 设置环境变量（从 Railway 获取，或手动设置）
# Claude 可以直接用 railway variables 命令获取：
export LLM_API_KEY=$(railway variables get LLM_API_KEY)
# ... 其他变量同理

# 4. 启动本地服务
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 5. 测试
curl http://localhost:8000/health
```

### 项目结构速查

```
Sunday-OS-2.0/
├── backend/
│   ├── Dockerfile              # 容器配置
│   ├── requirements.txt        # Python 依赖
│   ├── app/
│   │   ├── main.py             # ⭐ FastAPI 主应用 + LLMService
│   │   ├── telegram_bot.py     # ⭐ Telegram Bot
│   │   ├── memory.py           # ⭐ 记忆系统 (MemoryStore + 数据库)
│   │   ├── mailer.py           # 邮件推送引擎
│   │   ├── email_templates.py  # AI 邮件设计引擎
│   │   ├── knowledge_push.py   # 知识推送引擎
│   │   ├── search.py           # 联网搜索 (DuckDuckGo)
│   │   ├── logger.py           # 日志系统
│   │   ├── imap_listener.py    # IMAP 邮件监听
│   │   ├── file_generator.py   # 文件生成器
│   │   └── config.py           # 全局配置
│   └── test_llm_push.py        # 测试脚本
├── SundayOS_技术文档.md         # 📖 完整技术文档（必读）
├── CHANGELOG.md                 # 开发日志
└── Claude对接SundayOS指南.md    # 📖 本文件
```

---

## 第六步：常见操作速查

### 部署新版本

```bash
cd Sunday-OS-2.0/backend

# 提交代码
git add .
git commit -m "v3.x.x: 描述改动"

# 推送 + 部署
git push
railway up
```

### 查看运行日志

```bash
cd Sunday-OS-2.0/backend
railway logs --tail
```

### 调试记忆数据库

```bash
cd Sunday-OS-2.0/backend

# 查看数据库文件（部署环境）
railway run "sqlite3 /app/data/sunday_memory.db '.tables'"

# 查看记忆统计
railway run "sqlite3 /app/data/sunday_memory.db 'SELECT category, COUNT(*) FROM memories WHERE archived=0 GROUP BY category'"
```

### 重启服务

```bash
cd Sunday-OS-2.0/backend
railway service restart
```

### 添加新环境变量

```bash
cd Sunday-OS-2.0/backend
railway variables set NEW_KEY=new_value
# 需要重新部署才能生效
railway up
```

---

## 附录：AI 模型对接的关键提示词

如果你要把这个项目交给一个新的 AI 模型，直接把下面这段话发给他：

---

```
你正在接手 SundayOS 项目——一个个人 AI 助手系统。

请先阅读以下两份文件来理解项目：
1. /workspace/SundayOS_技术文档.md — 完整技术文档
2. /workspace/Claude对接SundayOS指南.md — 对接指南（你正在读的这份）

关键信息速览：
- 技术栈：FastAPI + 豆包大模型 + SQLite + Telegram Bot + Resend 邮件
- 部署平台：Railway (sfo区域)
- 代码仓库：https://github.com/banana0712/Sunday-OS-2.0
- 部署命令：cd backend && railway up
- 所有敏感信息已在 Railway 环境变量中，不需要本地 .env
- 记忆数据库位于 /app/data/sunday_memory.db (Railway Volume 持久化)

你的任务：基于以上理解，协助开发、调试、部署 SundayOS。
```

---

> **最后更新**：2026-07-09  
> **适用对象**：Claude、GPT、Gemini 等任何能读文件、执行命令的 AI 编程助手
