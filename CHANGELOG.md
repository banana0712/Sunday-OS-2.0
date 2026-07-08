# SundayOS 开发日志

> 记录每个版本的改动、功能、代码变更。每次部署前必须更新。

## 格式规范

```markdown
## [版本号] - YYYY-MM-DD HH:MM

### 新增功能
- 功能名：简述
- 影响文件：`file1.py`, `file2.py`

### 修复
- 问题描述 → 修复方式
- 影响文件：`file.py`

### 优化
- 优化点
- 影响文件：`file.py`

### 已知问题
- 问题描述

### 下次计划
- 计划内容
```

---

## v3.1.0 - 2026-07-09 05:30

### 新增功能
- **AI 主动创作推送**：Sunday 自主决定推送什么、何时推送。不再固定类型，可以是小短文/手作报道/灵感碎片/碎碎念/任何形式
  - 影响文件：`app/knowledge_push.py`（重写）, `app/email_templates.py`, `app/mailer.py`
- **AI 创意决策引擎**：LLM 根据天气/时间/记忆/聊天话题决定"要不要推？推什么？"
  - 30%概率触发（节省token），每天最多2次
- **通用创作模板** `creative_post`：适配任意内容类型
  - 影响文件：`app/email_templates.py`

### 优化
- 旧知识推送类型合并为统一"创意推送"模式
- 不打扰时段(23-7)不推，用户刚聊天(1h内)不推

---

## v3.0.0 - 2026-07-09 05:00

### 新增功能
- **AI 原生设计引擎**：邮件配色/布局/装饰由 LLM 自主设计，不再依赖预设模板
  - 影响文件：`app/email_templates.py`, `app/mailer.py`
- **Word 报告生成**：支持学术/简洁两种风格，LLM 搜索+大纲+逐章撰写
  - 影响文件：`app/file_generator.py`（新建）
- **数据图表生成**：matplotlib 渲染 PNG
  - 影响文件：`app/file_generator.py`
- **知识推送系统**：科学趣闻/今日词条/思维火花/灵感碎片/时事速览，每天1-2条
  - 影响文件：`app/knowledge_push.py`（新建）
- **AI 意图判断**：Telegram 聊天中自动识别报告/文件生成请求
  - 影响文件：`app/telegram_bot.py`
- **自动分段聊天**：AI 自主决定何时分多条消息发送
  - 影响文件：`app/telegram_bot.py`, `app/main.py`（System Prompt）
- **邮件附件发送**：Resend API 支持 base64 附件
  - 影响文件：`app/mailer.py`
- **周报自动生成**：每周日晚自动推送数据报告
  - 影响文件：`app/mailer.py`, `app/memory.py`

### 修复
- **记忆质量过滤**：加入 `_is_quality_memory()`，过滤带问号/省略号/反问的垃圾记忆
  - 影响文件：`app/main.py`, `app/memory.py`（MEMORY_EXTRACTION_PROMPT）
- **称谓自然化**：System Prompt 明确指导 Sunday 不要每条消息都带称呼
  - 影响文件：`app/main.py`（SUNDAY_SYSTEM_PROMPT）
- **反馈质量检查**：加入 `_is_quality_feedback()`，防止闲聊误触发改进计划
  - 影响文件：`app/telegram_bot.py`
- **Telegram 中文命令崩溃**：`CommandHandler("记忆")` 导致 Bot 启动失败，改为仅英文命令
  - 影响文件：`app/telegram_bot.py`
- **邮件图片乱码**：Unsplash Source 不稳定，改为 LoremFlickr + CSS 装饰 fallback
  - 影响文件：`app/file_generator.py`, `app/email_templates.py`
- **邮件主题优化**：知识推送邮件主题改为文章标题而非固定"Sunday 知识小卡片"
  - 影响文件：`app/mailer.py`

### 优化
- **推送频率保护**：每天最多5条推送（含节奏型+事件型+知识型）
  - 影响文件：`app/mailer.py`, `app/memory.py`
- **天气缓存**：wttr.in API 结果缓存30分钟
  - 影响文件：`app/mailer.py`
- **LLM 模型统一**：所有模块使用同一模型配置，避免 hardcode "deepseek-chat"
  - 影响文件：`app/mailer.py`

### 已知问题
- 邮件外部图片在部分客户端仍可能加载缓慢（依赖 LoremFlickr 响应速度）
- 长文本回复的 token 消耗较高（800-2000 tokens）

### 下次计划
- 开发日志自动化：每次部署自动提取 git diff 生成日志
- 记忆系统 AI 辅助管理：自动归档低质量/过期记忆
- 快捷指令端优化：支持语音输入、图片识别

---

## v2.5.0 - 2026-07-09 02:00

### 新增功能
- **CSV 记忆导出**：`GET /api/memory/export/csv` 返回 UTF-8-BOM 编码的 CSV
  - 影响文件：`app/main.py`
- **Dashboard 记忆标签页**：显示状态/分类/摘要/重要性/访问次数/ID
  - 影响文件：`app/main.py`（dashboard HTML）
- **记忆状态管理**：`active`（参与上下文）vs `archived`（历史记录）
  - 影响文件：`app/memory.py`
- **改进计划自动检测**：聊天中识别 `改进:` / `bug:` / `TODO:` 自动记录
  - 影响文件：`app/telegram_bot.py`, `app/memory.py`
- **Dashboard 多标签页**：日志 / 改进计划 / 记忆 三页切换
  - 影响文件：`app/main.py`（dashboard HTML）

### 修复
- **时区错误**：`datetime.now()` 改为 `datetime.now(ZoneInfo("Asia/Shanghai"))`
  - 影响文件：`app/memory.py`, `app/main.py`
- **Telegram 与快捷指令记忆不统一**：统一 user_id 为 `daily`
  - 影响文件：`app/telegram_bot.py`

---

## v2.0.0 - 2026-07-08

### 新增功能
- **Telegram Bot 集成**：`python-telegram-bot` 实时聊天
  - 影响文件：`app/telegram_bot.py`（新建）
- **IMAP 邮件监听**：iCloud 邮箱每15秒轮询，实时回复检测
  - 影响文件：`app/imap_listener.py`（新建）
- **Resend 邮件推送**：HTTP API 替代 SMTP（Railway 封端口）
  - 影响文件：`app/mailer.py`（新建）
- **三层推送体系**：早安/午间/晚间/关怀，LLM 个性化内容
  - 影响文件：`app/mailer.py`
- **日志系统**：SQLite 存储，Dashboard 可视化
  - 影响文件：`app/logger.py`（新建）
- **Dashboard 开发者面板**：浏览器查看日志统计
  - 影响文件：`app/main.py`

### 修复
- **Resend 403**：API key 注册邮箱与发件邮箱不匹配，重新注册
- **IMAP UID 类型错误**：`int` 对象没有 `decode` 属性

---

## v1.0.0 - 2026-07-07

### 初始版本
- FastAPI 后端 + SQLite 记忆系统
- 快捷指令 API：`/api/chat`, `/api/chat/stream`
- 基础记忆：12 分类 + LLM 智能提取
- 联网搜索：DDGS 集成
