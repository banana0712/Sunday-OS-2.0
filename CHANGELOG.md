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

## v3.2.2 - 2026-07-09 09:00

### 🔧 紧急修复 — 意图理解错误 + 冷却冲突 + 内容曲解

#### 1. AI 意图判断 Prompt 重写
- 「推送一篇关于科技和小知识的邮件给我」被误判为 `email_send` → 修复为正确识别 `creative_push`
- 「那现在推送一封给我吧」topic 提取错误 → 新增模糊 topic 智能处理
- 新增推送场景覆盖：「推送一封XX给我」「给我推一篇」「来一封推送」等
- 明确区分 `creative_push`（创作新内容）vs `email_send`（发送已有文件）
- 影响文件：`app/telegram_bot.py`

#### 2. 模糊 topic 智能主题选择
- 用户说「推送一封给我」topic 为空 → 不再创作关于「推送技术」的元内容
- 新增 `_ai_pick_topic()`：根据用户画像、天气、时间智能选择有趣主题
- 模糊关键词检测：「推送内容」「来一封」「一篇」等自动触发 AI 选主题
- 影响文件：`app/telegram_bot.py`

#### 3. 搜索关键词智能优化
- `generate_creative_content` 搜索前检测模糊 topic → AI 提炼更好的搜索词
- 创作 prompt 明确禁止写「推送技术/推送系统」相关内容
- 影响文件：`app/knowledge_push.py`

#### 4. 节奏型推送独立于冷却机制
- **核心修复**：早安/午间/晚间/周报/关怀等节奏型推送不再受 `MAX_DAILY_PUSHES` 限制
- 节奏型推送有自己的去重逻辑（每天一次/每周一次），不会因为 AI 创意推送配额满了而被拦截
- AI 创意推送单独限制：每天最多 2 次
- `get_daily_push_count()` 新增 `push_type` 参数支持按类型过滤
- 影响文件：`app/mailer.py`, `app/memory.py`

### 架构改进
- 推送体系分层：
  - **节奏型**（不受冷却限制）：早安/心情签/周报/午间/晚间/关怀
  - **创意型**（受频率+冷却限制）：AI 主动创作推送，每天 ≤2 次
  - **按需型**（用户触发）：立即推送，不受任何限制

---

## v3.2.1 - 2026-07-09 08:20

### 🔧 紧急修复 — 邮件推送系统 5 大 Bug

#### 1. 返回值类型不一致导致推送静默失败
- `sunday_should_push()` 声明返回 2 元组，实际返回 3 元组，且频率上限检查返回 `None, None`（2个）导致解包崩溃
- 修复：统一为 3 元组 `(type, html, subject) | (None, None, None)`
- 影响文件：`app/mailer.py`, `app/main.py`

#### 2. 立即推送时聊天框重复邮件内容
- 用户说「写一篇XX」→ Telegram 和邮件发完全一样的内容 → 体验极差
- 修复：聊天框改为 AI 生成简短告知（1-2句俏皮话），邮件发完整内容
- 新增 `_generate_push_chat_reply()` 函数
- 影响文件：`app/telegram_bot.py`

#### 3. 邮件主题不使用内容标题
- creative 类型邮件主题固定为「Sunday 给你发消息啦~ 💕」而非文章标题
- 修复：`_build_creative_post` 返回 `creative['title']` 作为 subject，`_pick_subject_for_type` 添加 creative 兜底
- 影响文件：`app/mailer.py`, `app/main.py`

#### 4. 邮件配图比例偏低
- `creative_post` 模板完全没有图片支持，只有 emoji banner
- 修复：添加 `image_url` 参数，优先使用 LoremFlickr 配图，无图时 fallback 装饰 banner
- `_build_creative_post` 自动尝试获取配图
- 影响文件：`app/email_templates.py`, `app/mailer.py`

#### 5. 主动推送触发概率太低
- 30% 概率 × 3h 冷却 × 1h 无互动 → 几乎从不触发
- 修复：
  - 触发概率：普通时段 30%→35%，黄金时段（10-11/15-16/20-21点）55%
  - 冷却时间：3h→2h
  - 互动冷却：1h→30min
- 影响文件：`app/knowledge_push.py`

### 优化
- `/api/push/pending` 返回增加 `subject` 字段方便调试
- `/api/push/send` knowledge 类型改为「知识分享」标签
- 所有 return 路径显式 3 元组，防止解包错误

---

## v3.2.0 - 2026-07-09 06:35

### 新增功能
- **SundayOS 控制台**：Dashboard 升级为四 Tab 管理后台（总览/记忆/计划/日志）
  - 影响文件：`app/main.py`
- **总览页**：数据统计卡片 + 用户画像（Sunday眼中的你）+ 最近对话记录
  - 影响文件：`app/main.py`
- **记忆管理**：控制台直接新增记忆（输入框+按钮）
  - 影响文件：`app/main.py`
- **改进计划管理**：控制台快速添加/完成/删除计划
  - 影响文件：`app/main.py`
- **AI 自动完成检测**：聊天中说"搞定了/做好了"→ AI 自动匹配并标记对应计划为 done
  - 影响文件：`app/telegram_bot.py`
- **`/plan` 命令**：替代 `/:`，标准命令格式（`/plan` `/bug` `/todo` `/ux`）
  - 影响文件：`app/telegram_bot.py`
- **移动端响应式适配**：卡片堆叠、表格横向滚动、字体缩放
  - 影响文件：`app/main.py`

### 修复
- **feedback 表自动迁移**：旧表自动添加 `ai_category` 和 `priority` 列
  - 影响文件：`app/memory.py`
- **feedback API**：新增 POST `/api/feedback/add` 和 done/delete 端点
  - 影响文件：`app/main.py`
- **移动端表格换行**：内容正常换行显示，不截断不用省略号
  - 影响文件：`app/main.py`

---

## v3.1.2 - 2026-07-09 05:56

### 新增功能
- **`/:` 快速写入改进计划**：在聊天中直接 `/: 内容` → 自动写入改进计划
  - AI 自动分类：判断 feature/enhancement/bug/ux/other
  - AI 自动优化标题、标注优先级、添加分类标签
  - 影响文件：`app/telegram_bot.py`, `app/memory.py`

### 优化
- feedback 表新增 `ai_category` 和 `priority` 字段
- 旧格式（改进:/bug:/TODO:）仍兼容

---

## v3.1.1 - 2026-07-09 05:42

### 新增功能
- **即时创作响应**：Telegram 说"写一篇XX/帮我创作/生成推送"→ AI 识别意图 → 立即生成并发送
  - 同时发 Telegram + 邮件双通道
  - 影响文件：`app/telegram_bot.py`

### 频率控制
- 主动推送：每天最多2次，间隔≥3h，23-7不推，刚聊天1h内不推
- 即时创作：用户明确指令时立即执行，不计入主动推送配额

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
