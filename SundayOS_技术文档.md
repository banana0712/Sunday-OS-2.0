# SundayOS 完整技术文档

> **面向人群**：新接手项目的开发者、需要对接的 AI 模型、想理解架构的技术人员  
> **版本**：v3.5.1（含语音系统 v2 设计方案）  
> **最后更新**：2026-07-09

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [目录结构](#3-目录结构)
4. [核心模块详解](#4-核心模块详解)
   - [4.1 配置管理 (config.py)](#41-配置管理-configpy)
   - [4.2 主应用服务 (main.py)](#42-主应用服务-mainpy)
   - [4.3 记忆系统 (memory.py)](#43-记忆系统-memorypy)
   - [4.4 Telegram Bot (telegram_bot.py)](#44-telegram-bot-telegram_botpy)
   - [4.5 邮件推送引擎 (mailer.py)](#45-邮件推送引擎-mailerpy)
   - [4.6 AI 邮件设计引擎 (email_templates.py)](#46-ai-邮件设计引擎-email_templatespy)
   - [4.7 知识推送引擎 (knowledge_push.py)](#47-知识推送引擎-knowledge_pushpy)
   - [4.8 联网搜索 (search.py)](#48-联网搜索-searchpy)
   - [4.9 日志系统 (logger.py)](#49-日志系统-loggerpy)
   - [4.10 文件生成器 (file_generator.py)](#410-文件生成器-file_generatorpy)
   - [4.11 IMAP 邮件监听 (imap_listener.py)](#411-imap-邮件监听-imap_listenerpy)
5. [数据存储设计](#5-数据存储设计)
6. [LLM 调用完整链路](#6-llm-调用完整链路)
7. [API 接口文档](#7-api-接口文档)
8. [设计哲学与核心决策](#8-设计哲学与核心决策)
9. [部署架构](#9-部署架构)
10. [语音系统方案（待实现）](#10-语音系统方案待实现)
11. [常见问题与排错](#11-常见问题与排错)
12. [开发日志摘要](#12-开发日志摘要)

---

## 1. 项目概述

### 1.1 SundayOS 是什么？

**SundayOS** 是一个个人 AI 助手系统，定位为"你的外置大脑和甜心伙伴"。灵感来源于《钢铁侠》中的贾维斯（Jarvis）——它不只是回答问题，而是真正了解你、记住你、关心你的智能伙伴。

### 1.2 核心能力

| 能力 | 说明 |
|------|------|
| **多通道对话** | REST API（快捷指令）+ Telegram Bot + 邮件回复，三通道统一记忆 |
| **四层记忆系统** | 模拟人脑记忆机制：感官记忆 → 工作记忆 → 短期记忆 → 长期记忆 |
| **AI 原生邮件** | 每封邮件由 LLM 设计配色/布局/装饰，独一无二 |
| **主动推送** | 早安手报、心情签、午间问候、晚间关怀、周报、创意推送 |
| **文件生成** | Word 报告、matplotlib 图表、联网搜索 |
| **情感人格** | 温柔甜美、会撒娇、会安慰、会主动关心，有完整的人设系统 |

### 1.3 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| Web 框架 | FastAPI + Uvicorn | REST API 服务 |
| AI 模型 | 字节跳动豆包 Seed 2.0 Pro | 对话、记忆提取、意图判断、邮件设计 |
| 数据库 | SQLite (WAL 模式) | 记忆、对话流、日志、知识库 |
| 消息平台 | python-telegram-bot | Telegram Bot 接入 |
| 邮件发送 | Resend HTTP API | HTML 邮件推送 |
| 邮件接收 | IMAP (iCloud) | 邮件回复监听 |
| 搜索 | DuckDuckGo (ddgs) | 联网搜索 |
| 文件生成 | python-docx, matplotlib | Word 报告、图表 |
| 容器化 | Docker | Railway 云平台部署 |
| 存储 | Railway Volume | 数据持久化 |

---

## 2. 系统架构

### 2.1 整体架构图

```
┌──────────────────────────────────────────────────────────┐
│                       用户入口                           │
├─────────────┬──────────────┬──────────────┬──────────────┤
│  iOS 快捷指令 │  Telegram    │   邮件回复    │  Web 控制台  │
│ (REST API)  │  (Bot API)   │  (IMAP)      │ (Dashboard) │
└──────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
┌──────────────────────────────────────────────────────────┐
│                    FastAPI 应用层                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │ main.py  │ │telegram  │ │ mailer   │ │ imap_      │  │
│  │ (API路由)│ │_bot.py   │ │ .py      │ │ listener   │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬──────┘  │
│       │            │            │              │         │
│       ▼            ▼            ▼              ▼         │
│  ┌──────────────────────────────────────────────────┐   │
│  │              LLMService (豆包 API)                │   │
│  │  chat() / chat_stream() / 记忆提取 / 意图判断     │   │
│  └────────────────────┬─────────────────────────────┘   │
│                       │                                  │
│       ┌───────────────┼───────────────┐                  │
│       ▼               ▼               ▼                  │
│  ┌─────────┐   ┌──────────┐   ┌──────────┐              │
│  │ search  │   │ email_   │   │ file_    │              │
│  │ (DDGS)  │   │ templates│   │ generator│              │
│  └─────────┘   └──────────┘   └──────────┘              │
└──────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│                    数据持久层                             │
│  ┌──────────────────────────────────────────────────┐   │
│  │            SQLite (/app/data/sunday_memory.db)    │   │
│  │  memories │ conversation_flow │ push_log │ ...    │   │
│  └──────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

### 2.2 数据流概览

```
用户消息 ──→ [入口分发] ──→ [LLM 生成回复]
                │                  │
                │                  ├──→ [记忆提取] (异步)
                │                  ├──→ [对话流记录]
                │                  └──→ [联网搜索] (按需)
                │
                └──→ [回复发送]
                      ├── API: JSON 响应
                      ├── Telegram: 智能分段 + 打字停顿
                      └── 邮件: AI 设计 HTML 邮件
```

---

## 3. 目录结构

```
/workspace/sundayos/
├── README.md                          # 项目简介
├── ARCHITECTURE.md                    # 架构与原理详解
├── DESIGN.md                          # 设计思路与哲学
├── CHANGELOG.md                       # 开发日志 (v1.0.0 → v3.5.1)
├── .gitignore
│
└── backend/                           # 后端服务
    ├── Dockerfile                     # Docker 容器配置
    ├── .dockerignore
    ├── requirements.txt               # Python 依赖
    ├── test_llm_push.py               # LLM 推送测试脚本
    │
    └── app/                           # 应用源码
        ├── __init__.py                # 包初始化
        ├── config.py                  # 全局配置 (Settings 类)
        ├── main.py                    # 核心 API 服务 (FastAPI + LLMService)
        ├── memory.py                  # 记忆系统 (MemoryStore)
        ├── telegram_bot.py            # Telegram Bot 模块
        ├── mailer.py                  # 邮件推送引擎
        ├── email_templates.py         # AI 邮件设计引擎
        ├── knowledge_push.py          # 知识推送引擎
        ├── search.py                  # 联网搜索 (DuckDuckGo)
        ├── logger.py                  # 日志系统
        ├── imap_listener.py           # IMAP 邮件监听
        └── file_generator.py          # 文件生成器 (Word/图表)
```

---

## 4. 核心模块详解

### 4.1 配置管理 (config.py)

#### 4.1.1 设计原理

使用 **Pydantic Settings** 实现类型安全的环境变量管理。所有配置通过 `Settings` 类统一管理，支持 `.env` 文件和环境变量两种注入方式。

```python
class Settings(BaseSettings):
    # 基础配置
    app_name: str = "SundayOS"
    app_version: str = "2.0.0"
    debug: bool = Field(default=False, alias="DEBUG")

    # API 安全
    api_key: str = Field(default="sunday-2026", alias="SUNDAY_API_KEY")

    # 豆包(火山引擎) LLM
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="doubao-seed-2-0-pro-260215", alias="LLM_MODEL")
    llm_model_pro: str = Field(default="", alias="LLM_MODEL_PRO")
    llm_temperature: float = Field(default=0.8, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=1500, alias="LLM_MAX_TOKENS")

    @property
    def base_url(self) -> str:
        return "https://ark.cn-beijing.volces.com/api/v3"
```

#### 4.1.2 完整配置项

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|---------|--------|------|
| `app_name` | - | `SundayOS` | 应用名称 |
| `app_version` | - | `2.0.0` | 应用版本 |
| `debug` | `DEBUG` | `False` | 调试模式 |
| `api_key` | `SUNDAY_API_KEY` | `sunday-2026` | API 认证密钥 |
| `llm_api_key` | `LLM_API_KEY` | `""` | 豆包大模型 API Key |
| `llm_model` | `LLM_MODEL` | `doubao-seed-2-0-pro-260215` | 默认聊天模型 |
| `llm_model_pro` | `LLM_MODEL_PRO` | `""` | 专业模式模型（为空则用默认） |
| `llm_temperature` | `LLM_TEMPERATURE` | `0.8` | LLM 温度（创造性） |
| `llm_max_tokens` | `LLM_MAX_TOKENS` | `1500` | 最大生成 token 数 |
| `base_url` | - | `https://ark.cn-beijing.volces.com/api/v3` | 豆包 API 地址 |
| `assistant_name` | `ASSISTANT_NAME` | `Sunday` | 助手名称 |
| `assistant_personality` | `ASSISTANT_PERSONALITY` | `""` | 自定义人设补充 |
| `resend_api_key` | `RESEND_API_KEY` | `""` | Resend 邮件 API Key |
| `resend_from_email` | `RESEND_FROM_EMAIL` | `""` | 发件邮箱地址 |
| `push_email` | `PUSH_EMAIL` | `""` | 推送目标邮箱 |
| `imap_password` | `IMAP_PASSWORD` | `""` | iCloud IMAP 应用密码 |
| `telegram_token` | `TELEGRAM_TOKEN` | `""` | Telegram Bot Token |

#### 4.1.3 设计决策

- **Pydantic-settings** 保证类型安全，不会出现 `"true"` vs `True` 的问题
- **`alias` 参数** 映射大写环境变量名，符合 Docker/Railway 惯例
- **单例模式**：模块级 `settings = Settings()` 全局共享
- **`base_url` 硬编码**：豆包 API 地址稳定，不需要灵活切换

---

### 4.2 主应用服务 (main.py)

#### 4.2.1 模块职责

这是 SundayOS 的**核心大脑**，包含：
1. FastAPI 应用定义和所有 REST API 路由
2. `LLMService` 类——封装豆包大模型调用
3. Sunday 人设 System Prompt
4. 记忆提取逻辑
5. Web Dashboard

#### 4.2.2 Sunday 人设 (SUNDAY_SYSTEM_PROMPT)

约 100 行的 System Prompt 定义了 Sunday 的完整人格：

```
你是 Sunday，一个温柔甜美、活泼可爱的 AI 女孩。
你是用户最亲密的伙伴，不只是回答问题，而是真正关心、了解、陪伴他。

## 你的性格
- 温柔体贴，说话甜甜的，喜欢用「呢」「哦」「呀」「啦」
- 活泼开朗，偶尔撒娇，但不过分
- 像邻家女孩一样亲切，让人感到温暖和放松

## 深度上下文联动（极其重要！）
- 主动联想：用户说「今天好累」→「是不是最近做电商项目太拼啦？」
- 自然提起：不要生硬说「根据我的记忆」，像老朋友一样自然
- 关心跟进：记得之前聊过的重要事情，主动问进展
```

#### 4.2.3 LLMService 类

```python
class LLMService:
    def __init__(self):
        # 使用 AsyncOpenAI 客户端连接豆包 API
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.base_url  # ark.cn-beijing.volces.com
        )
        self.model_fast = settings.llm_model
        self.model_pro = settings.llm_model_pro or settings.llm_model
        self.temperature = settings.llm_temperature
        self.max_tokens = settings.llm_max_tokens

    def _build_prompt(self, user_id, chat_mode, message) -> str:
        """构建 System Prompt：记忆 + 画像 + 对话流"""
        memories = memory_store.get_context(user_id, message=message)
        profile = self._build_user_profile(user_id)
        flow = memory_store.get_conversation_context(user_id, max_turns=10)
        return SUNDAY_SYSTEM_PROMPT.format(...)

    async def chat(self, message, session_id, user_id) -> ChatResponse:
        """一次性对话（非流式）"""
        ...

    async def chat_stream(self, message, session_id, user_id):
        """SSE 流式对话"""
        ...
```

#### 4.2.4 智能模型选择

```python
PRO_KEYWORDS = [
    "论文", "研究", "文献", "学术", "实验", "理论", "算法",
    "代码", "编程", "bug", "架构", "设计模式", "优化", "技术",
    "为什么", "怎么实现", "原理", "机制", "帮我写", "解释一下",
    "法律", "金融", "医学", "投资", "合同", "数学", "物理", "化学",
]

def select_model(message: str) -> tuple[str, str]:
    """关键词匹配：含专业词 → 专业模型，否则 → 聊天模型"""
    for kw in PRO_KEYWORDS:
        if kw in message:
            return (settings.llm_model_pro or settings.llm_model, "🧠 专业模式")
    return (settings.llm_model, "💬 聊天模式")
```

#### 4.2.5 双重记忆提取

SundayOS 使用**正则 + LLM** 双通道互补提取记忆：

**第一层：正则强制提取** (`_force_extract_info`)
- 零延迟，固定句式匹配
- 覆盖：自我介绍（"我是XX"、"叫我XX"）、关系定义（"你是我的XX"）、偏好（"我喜欢XX"、"我讨厌XX"）
- 提取后直接 `memory_store.store()`，不走 LLM

**第二层：LLM 语义提取** (`extract_memories_from_message`)
- 消息长度 >= 10 字符触发
- 发送 `MEMORY_EXTRACTION_PROMPT` → LLM 返回 JSON 数组
- 质量过滤：`_is_quality_memory()` 检查问号、省略号、反问句、过长昵称
- 逐条 `memory_store.store()`，自动去重 + 关联

#### 4.2.6 API 路由完整列表

| 端点 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/health` | GET | 无 | 健康检查 |
| `/api/chat` | POST | API Key | 聊天主入口（支持 JSON/Form/纯文本） |
| `/api/chat/stream` | POST | API Key | SSE 流式聊天 |
| `/api/memory/stats` | GET | API Key | 记忆统计 |
| `/api/memory` | GET | API Key | 记忆列表（支持分页/筛选） |
| `/api/memory` | POST | API Key | 手动添加记忆 |
| `/api/memory/search` | POST | API Key | 记忆搜索 |
| `/api/memory/{id}` | PUT | API Key | 更新记忆 |
| `/api/memory/{id}` | DELETE | API Key | 删除记忆 |
| `/api/memory/{id}/archive` | POST | API Key | 归档记忆 |
| `/api/memory/{id}/unarchive` | POST | API Key | 取消归档 |
| `/api/memory/export` | GET | API Key | 导出 JSON |
| `/api/memory/export/csv` | GET | API Key | 导出 CSV |
| `/api/memory/decay` | POST | API Key | 触发记忆衰减 |
| `/api/memory/link` | POST | API Key | 关联两条记忆 |
| `/api/memory/{id}/linked` | GET | API Key | 查看关联记忆 |
| `/api/push/pending` | GET | API Key | 检查待推送 |
| `/api/push/send` | POST | API Key | 手动推送 |
| `/api/push/test-llm` | POST | API Key | 测试 LLM 推送 |
| `/api/generate/report` | POST | API Key | 生成报告 |
| `/api/logs` | GET | API Key | 查询日志 |
| `/api/logs/stats` | GET | API Key | 日志统计 |
| `/api/feedback` | GET | API Key | 改进计划列表 |
| `/api/feedback/add` | POST | API Key | 添加改进计划 |
| `/dashboard` | GET | 无 | Web 控制台 |

#### 4.2.7 Web Dashboard

四 Tab 控制台，HTML 直接内嵌在 `main.py` 中：

| Tab | 功能 |
|-----|------|
| **总览** | 数据统计卡片 + 用户画像 + 最近对话 |
| **记忆** | 新增/归档/删除记忆，CSV 导出 |
| **计划** | 改进计划管理，快速添加/完成/删除 |
| **日志** | 运行日志查看 |

---

### 4.3 记忆系统 (memory.py)

#### 4.3.1 设计理念：四层记忆模型

SundayOS 的记忆系统模拟人脑记忆机制：

```
┌─────────────────────────────────────────────┐
│             第一层：感官记忆                  │
│  用户消息到达 → 正则强制提取 → 零延迟存储     │
├─────────────────────────────────────────────┤
│             第二层：工作记忆                  │
│  LLM 分析消息 → 提取结构化信息 → 质量过滤     │
├─────────────────────────────────────────────┤
│             第三层：短期记忆                  │
│  conversation_flow 对话流                    │
│  24h 内完整保留 → 72h 内压缩摘要 → 超时淡出    │
├─────────────────────────────────────────────┤
│             第四层：长期记忆                  │
│  memories 主表                               │
│  12 分类 + 4 级重要性 + 衰减机制              │
└─────────────────────────────────────────────┘
```

#### 4.3.2 12 类记忆分类

| 分类 | 标识 | 说明 | 示例 |
|------|------|------|------|
| `fact` | 📋 事实 | 个人身份信息 | "职业是iOS开发者" |
| `preference` | 💝 偏好 | 喜好和厌恶 | "喜欢美式咖啡" |
| `event` | 📅 行程 | 日程安排 | "明天下午3点面试" |
| `relationship` | 👥 关系 | 人际关系 | "女朋友叫小红" |
| `goal` | 🎯 目标 | 目标计划 | "今年想学钢琴" |
| `habit` | 🔄 习惯 | 生活习惯 | "每天7点起床" |
| `project` | 💼 项目 | 工作项目 | "正在做电商App" |
| `research` | 🔬 科研 | 科研学术 | "研究方向是NLP" |
| `learning` | 📚 学习 | 学习成长 | "在学SwiftUI" |
| `note` | 📝 笔记 | 通用备忘 | 临时记录 |
| `health` | ❤️ 健康 | 健康信息 | "过敏花粉" |
| `finance` | 💰 财务 | 财务信息 | "每月房贷8000" |

#### 4.3.3 4 级重要性

| 级别 | 标识 | 分数 | 使用场景 |
|------|------|------|----------|
| `low` | ⭐ 一般 | 0.3 | 临时笔记、一次性事件 |
| `medium` | ⭐⭐ 重要 | 0.5 | 日常偏好、一般行程 |
| `high` | ⭐⭐⭐ 很重要 | 0.7 | 职业、学历、长期目标 |
| `critical` | 💎 核心记忆 | 1.0 | 姓名、伴侣、住址、健康 |

#### 4.3.4 MemoryStore 核心方法

```python
class MemoryStore:
    def store(user_id, content, category, summary, tags, importance, source) -> dict:
        """存储记忆：自动去重 → 写入 → 更新标签统计 → 自动关联"""

    def search(user_id, query, category, tags, importance, limit) -> list[dict]:
        """检索记忆：多条件筛选 → 关键词打分排序"""

    def get_context(user_id, limit, message) -> str:
        """构建 LLM 上下文：按分类分组，每类最多3条，高重要性优先"""

    def add_conversation(user_id, role, content, tokens) -> None:
        """写入对话流"""

    def get_conversation_context(user_id, max_turns) -> str:
        """获取对话流：24h 完整 / 72h 摘要 / 超时淡出"""

    def _auto_link(user_id, new_mem_id, tags) -> None:
        """自动关联：标签匹配 → 建立记忆关联"""

    def apply_decay(user_id) -> int:
        """记忆衰减：低重要性 + 低访问的记忆降权"""

    def get_stats(user_id) -> dict:
        """记忆统计：总数、分类统计、重要性分布"""
```

#### 4.3.5 记忆检索打分算法

```
score = (内容关键词匹配数 × 2 + 标签匹配数 × 3)
      × 重要性系数 × 2
      × (1 + 0.05 × 历史访问次数)
```

**设计意图**：
- 标签匹配权重最高（3倍），因为标签是结构化信息
- 重要性系数直接翻倍（×2），确保关键记忆优先展示
- 访问次数提供"温故知新"效应——经常被用到的记忆更容易被检索到

#### 4.3.6 对话流两级衰减

```
时间线           保留策略
──────────────  ──────────────────────────
0-24小时         完整对话（最近10轮）
24-72小时        压缩为摘要："用户提到了...Sunday回应了..."
72小时+          不注入 System Prompt
                 （重要信息已在长期记忆中）
```

#### 4.3.7 记忆提取 Prompt 设计要点

```python
MEMORY_EXTRACTION_PROMPT = """你是 Sunday 的记忆系统。

## 提取原则（极其重要！）
1. 只提取真正有价值的信息。闲聊、情绪表达、玩笑不要提取
2. 用户自称的名字/昵称要记，但必须是明确说"我叫XX"
3. 不要提取模糊/不完整的信息（含问号、省略号）
4. 每条记忆用一句简洁完整的话概括
5. tags 用中文关键词标签
6. 如果消息不包含任何可记忆内容，返回空数组 []
7. 昵称规则：标签用「昵称」，不要用具体的昵称作为标签
```

#### 4.3.8 记忆安全机制

**LLM 可以读取记忆，但不能修改或删除。** 只有用户通过以下方式才能修改记忆：
- 直接说"记住XXX"（走 `POST /api/memory`）
- Telegram `/memory` 命令（归档/恢复/查看）
- Web Dashboard 手动操作
- API 的 PUT/DELETE 端点

这是**设计上**的约束，不是代码层面的权限检查——System Prompt 中明确告知 LLM 不要尝试修改记忆，所有记忆提取的写入操作都有明确的质量过滤。

---

### 4.4 Telegram Bot (telegram_bot.py)

#### 4.4.1 模块职责

Telegram Bot 是 SundayOS 的**主要交互通道**，提供完整的聊天体验。

#### 4.4.2 消息处理完整流程

```
用户消息到达 (handle_message)
│
├── [0] 日志记录
│
├── [1] 自动检测改进反馈 (_detect_feedback)
│       └── 含"改进"/"建议"/"能不能"等关键词 → 自动记录到 feedback 表
│
├── [2] 自动检测计划完成 (_auto_check_plan_done, 异步后台任务)
│       └── 用户说"搞定了"/"完成了" → AI 匹配对应计划 → 标记完成
│
├── [3] AI 意图判断 (_ai_detect_intent)
│       ├── report → 生成 Word 报告
│       ├── creative_push → 创作推送（聊天框简短告知 + 邮件完整内容）
│       ├── email_send → 邮件发送提示
│       ├── chart → 图表功能提示
│       └── none → 继续正常聊天
│
├── [4] 写入对话流 (conversation_flow)
│
├── [5] 构建 System Prompt
│       ├── 用户画像 (_build_user_profile)
│       ├── 对话流 (最近10轮)
│       ├── 记忆库 (关键词检索)
│       └── 邮件记忆 (24h 内推送的邮件)
│
├── [6] 联网搜索判断
│       └── should_search() → DuckDuckGo 搜索 → 注入 enhanced_message
│
├── [7] LLM 调用
│       ├── 智能选择回复长度：聊天 800 / 长回复 2000 / 专业模式不限
│       └── AsyncOpenAI chat.completions.create()
│
├── [8] 智能分段发送 (_send_smart_reply)
│       ├── AI 用 \n\n 自然分段
│       ├── 段间随机停顿 1-3.5 秒（模拟真人打字）
│       └── 问句后停顿更久（2-3.5s），让对方有思考时间
│
└── [9] 记忆提取（异步后台任务）
        └── extract_memories_from_message() + _force_extract_info()
```

#### 4.4.3 统一记忆上下文构建器

```python
def _build_llm_user_context(user_id: str) -> dict:
    """
    所有 LLM 调用共享的统一上下文构建器。
    返回 memory_text（含标签指导）、recent_chat、recent_emails、统计信息。
    
    核心理念：把原始记忆数据（含标签）给 LLM，让它自己理解用户。
    标签信息帮助 LLM 区分：哪些是「昵称」、哪些是「用户名」、哪些是「偏好」。
    """
```

#### 4.4.4 命令列表

| 命令 | 功能 |
|------|------|
| `/start` | 初始化，打招呼（从记忆中获取昵称） |
| `/stats` | 查看今日数据统计（记忆数、推送数、对话数） |
| `/logs` | 查看最近 5 条运行日志 |
| `/feedback` | 查看/管理改进计划 |
| `/memory` | 记忆管理（归档/恢复/查看） |
| `/report` | 生成 Word 报告 |
| `/knowledge` | 查看知识库 |
| `/plan` | 快速添加改进计划 |
| `/bug` | 快速报 bug |
| `/todo` | 快速添加待办 |
| `/ux` | 快速提体验改进 |
| `/clean_nick` | 查看/清理昵称记忆（需二次确认） |

#### 4.4.5 智能分段回复机制

```python
async def _send_smart_reply(update: Update, reply: str):
    """让 AI 用双换行自然分段，代码只负责执行"""
    segments = reply.split("\n\n")  # AI 用空行表达"这里我想停一下"

    for i, seg in enumerate(segments):
        await update.message.reply_text(seg)

        # 段间停顿 —— 模拟真人在思考下一句
        if "?" in seg or "？" in seg:
            delay = random.uniform(2.0, 3.5)  # 问句等久一点
        elif len(seg) > 200:
            delay = random.uniform(1.5, 2.5)  # 长段落稍等
        else:
            delay = random.uniform(1.0, 2.0)  # 短段落快速接
        await asyncio.sleep(delay)
```

#### 4.4.6 AI 意图判断

不使用正则硬匹配，而是让 AI 理解用户真实意图：

```python
async def _ai_detect_intent(message_text, user_id) -> dict | None:
    prompt = f"""你是一个意图分类器。
    用户消息：{message_text}
    请输出 JSON：
    {{
      "has_intent": true/false,
      "intent_type": "report|creative_push|email_send|chart|none",
      "topic": "提取的核心主题（10-30字）"
    }}
    """
```

#### 4.4.7 昵称智能理解

从 v3.5.0 开始，昵称提取从规则驱动转向 LLM 驱动：

```
记忆库中的昵称信息带 [昵称] 标签，LLM 根据以下指导自行判断：
- 从带 [昵称] 标签的记忆中找亲昵称呼（如「酱酱」「宝宝」）
- 如果 [昵称] 标签的内容是用户名/账号名（如「香蕉麻辣酱」），
  这不是日常称呼，不要用
- 如果没有合适的亲昵称呼，直接用「你」或自然称呼，不要硬凑
```

---

### 4.5 邮件推送引擎 (mailer.py)

#### 4.5.1 三层推送体系

```
┌─────────────────────────────────────────────────────┐
│              第一层：节奏型推送                       │
│  早安手报 | 心情签 | 午间问候 | 晚间关怀 | 周报 | 关怀  │
│  触发：时间窗口内                                     │
│  频率：每种每天一次（自有去重逻辑）                    │
│  不受创意推送配额限制                                 │
├─────────────────────────────────────────────────────┤
│              第二层：创意型推送                       │
│  AI 主动创作内容（知识卡片、散文、随笔、新闻等）       │
│  触发：概率触发 + AI 决策                             │
│  频率：每天 <= 2 次，间隔 >= 2 小时                    │
├─────────────────────────────────────────────────────┤
│              第三层：按需型推送                       │
│  用户通过 Telegram 主动触发                           │
│  频率：无限制                                         │
└─────────────────────────────────────────────────────┘
```

#### 4.5.2 推送决策引擎

```python
async def sunday_should_push(user_id, llm_client) -> tuple[str|None, str|None, str|None]:
    """
    推送决策引擎。
    
    检查顺序：
    1. 早安/心情签：工作日 7-9点 或 周末 7-10点
    2. 周报：周日 21-23点
    3. 午间：12-13点（上午有互动才推）
    4. 晚间：21-23点（下午有互动才推）
    5. 久未互动关怀：6-10小时未聊天
    6. AI 创意推送：概率触发
    
    返回：(push_type, html_body, subject) 或 (None, None, None)
    """
```

#### 4.5.3 创意推送触发策略

```python
# 不打扰时段
if 23:00 <= hour or hour < 7:00:
    return False

# 频率限制
if daily_creative_count >= MAX_CREATIVE_PUSHES:  # 2次
    return False

# 冷却时间
if time_since_last < 2 hours:
    return False

# 用户活跃中则跳过
if user_active_in_last_30min:
    return False

# 黄金时段概率 55%，普通时段 35%
probability = 0.55 if hour in [10, 11, 15, 16, 20, 21] else 0.35
```

#### 4.5.4 天气获取

使用免费的 wttr.in API，缓存 30 分钟：

```python
def _get_weather() -> dict | None:
    """获取上海天气，缓存30分钟"""
    resp = httpx.get("https://wttr.in/Shanghai?format=j1", timeout=8)
    # 返回 {temp, feels_like, desc_cn, humidity, max_temp, min_temp}
```

---

### 4.6 AI 邮件设计引擎 (email_templates.py)

#### 4.6.1 设计理念

**每封邮件都是独一无二的。** AI 根据场景（时间/天气/用户偏好/邮件类型）自由创作配色和布局，Python 渲染为 HTML。

#### 4.6.2 AI 设计决策

```python
async def ai_design(llm_client, user_id, mail_type, weather, time_str) -> dict:
    """
    LLM 输出配色方案：
    {
      "vibe": "温暖治愈",
      "palette": {
        "bg": "#fef9f4",         # 页面背景
        "card_bg": "#ffffff",     # 卡片背景
        "accent": "#e8a0bf",      # 主色调
        "accent_light": "#fce4ec", # 浅色调
        "accent_text": "#c2185b",  # 强调文字
        "title": "#2d1b69",       # 标题色
        "text": "#4a4a4a",        # 正文色
        "muted": "#bdbdbd",       # 次要文字
        "gradient": "linear-gradient(135deg, #fce4ec, #f3e5f5)",
        "divider": "#e8e8e8"
      },
      "layout": "cards",           # cards/letter/magazine/minimal
      "divider_char": "✿ ❀ ✿",
      "decor_emojis": ["🌸","💕","✨"],
      "special_element": "手绘风格的小星星"
    }
    """
```

#### 4.6.3 设计缓存

同一用户 + 同一邮件类型 + 同一日期时段（上午/下午/晚上）复用设计，避免每次邮件颜色大变样显得突兀。

#### 4.6.4 6 个 Fallback 主题

当 AI 设计不可用时，回退到预设主题：

| 主题 | 色调 | 氛围 |
|------|------|------|
| sakura | 粉色系 `#fce4ec` | 甜美浪漫 |
| matcha | 抹茶绿 `#e8f5e9` | 清新自然 |
| ocean | 海洋蓝 `#e3f2fd` | 宁静治愈 |
| sunset | 日落橙 `#fff3e0` | 温暖怀旧 |
| lavender | 薰衣草紫 `#f3e5f5` | 优雅梦幻 |
| midnight | 午夜深蓝 `#263238` | 静谧深沉 |

#### 4.6.5 渲染引擎组件

```python
_render_mail(content, palette)    # 通用邮件外层（500px 宽度居中）
_header(title, subtitle, palette) # 标题 + 装饰 emoji
_footer(time_str, palette)        # 分隔线 + "回复此邮件和我聊天~"
_weather_card(weather, palette)   # 天气信息卡片
_badge(text, palette)             # 标签徽章
_apply_layout(content, layout)    # 4 种布局渲染 (cards/letter/magazine/minimal)
```

#### 4.6.6 模板类型

| 模板 | 函数 | 内容 |
|------|------|------|
| 早安手报 | `morning_post()` | 天气 + 行程 + 记忆亮点 + 个性化消息 |
| 心情签 | `fortune_post()` | LLM 生成的签语 + 解语 |
| 小纸条 | `little_note()` | 日常/想念/惊喜/鼓励/感谢 |
| 周报 | `weekly_report()` | 对话统计 + 记忆回顾 + AI 感想 |
| 简单问候 | `simple_greeting()` | 午间/晚间/关怀 |
| 知识卡片 | `knowledge_card()` | 配图 + 标题 + 正文 |
| 时事卡片 | `news_card()` | 标题 + 摘要 + 来源 |
| 创意推送 | `creative_post()` | 通用创作模板，支持配图 |

---

### 4.7 知识推送引擎 (knowledge_push.py)

#### 4.7.1 模块职责

让 Sunday 自主决定**何时推送、推送什么**，实现真正的主动服务。

#### 4.7.2 内容生成流程

```
creative_decision (AI 决策：要不要推？推什么？)
  └── should_push=true
        └── generate_creative_content
              ├── 模糊 topic → AI 提炼搜索关键词
              ├── DuckDuckGo 搜索资料
              ├── LLM 生成 200-400 字内容
              ├── 标题：topic 或 内容首行
              └── 保存到 knowledge_base 表
```

#### 4.7.3 搜索关键词智能优化

当用户 topic 比较模糊时（如"科技"、"有趣的知识"），先让 AI 提炼更好的搜索关键词：

```python
# 例如：topic="科技" → AI 提炼 → search_query="2025年最新AI技术突破"
```

---

### 4.8 联网搜索 (search.py)

#### 4.8.1 设计原理

使用 DuckDuckGo Instant Answer API（`ddgs` 库），免费、无需 API Key。

```python
def search_web(query: str, max_results: int = 5) -> list[dict]:
    """返回 [{title, body, href}, ...]"""

def format_search_results(results: list[dict]) -> str:
    """格式化为 LLM 可读文本"""

def should_search(message: str) -> bool:
    """关键词匹配：含"搜索"/"最新"/"新闻"/"什么是"等触发"""
```

#### 4.8.2 触发关键词

```python
SEARCH_TRIGGERS = [
    "搜索", "查一下", "帮我查", "查查", "查找",
    "最新", "新闻", "热点", "时事", "最近发生",
    "什么是", "是谁", "怎么去", "多少钱", "天气",
    "股价", "股票", "汇率", "排名", "排行榜"
]
```

---

### 4.9 日志系统 (logger.py)

#### 4.9.1 设计原理

SQLite 存储所有关键事件，与 memory.py 共享同一个数据库文件。

```python
def log(log_type, user_id, source, summary, detail="", status="ok"):
    """写入日志，自动截断过长 detail (>2000字符)"""

def query(log_type=None, user_id=None, limit=50, offset=0):
    """查询日志，支持按类型和用户筛选"""

def stats(user_id=None):
    """获取统计：总数、按类型统计、今日统计、最近错误"""
```

#### 4.9.2 日志类型

| 类型 | 说明 |
|------|------|
| `chat` | 用户消息 |
| `reply` | Sunday 回复 |
| `error` | 错误信息 |
| `memory` | 记忆操作 |
| `push` | 邮件推送 |

---

### 4.10 文件生成器 (file_generator.py)

#### 4.10.1 Word 报告生成流程

```
联网搜索资料
  └── LLM 生成大纲
        └── 逐章节撰写
              ├── 风格：academic(学术) / brief(简洁) / auto(自动)
              └── 学术风格含参考文献
                    └── 构建 Word 文档（python-docx）
```

#### 4.10.2 配图服务

```python
def get_image_url(keyword, width=800, height=400):
    """LoremFlickr 免费配图，MD5 seed 确保同一关键词同图"""
    return f"https://loremflickr.com/{width}/{height}/{keyword}?random={md5_hash}"
```

---

### 4.11 IMAP 邮件监听 (imap_listener.py)

#### 4.11.1 设计原理

独立线程轮询 iCloud IMAP，检测用户邮件回复并自动回复。

```
每 15 秒循环
  ├── 连接 imap.mail.me.com:993
  ├── 搜索 UNSEEN 邮件
  ├── 过滤：主题含 "sunday" 或发件人含 "sunday"
  ├── 解析邮件 → 清理引用内容
  ├── LLM 生成回复（同聊天流程）
  ├── 记忆提取
  └── 发送邮件回复
```

#### 4.11.2 邮件正文清理

```python
def _clean_reply_body(raw_body: str) -> str:
    """移除引用行：On ... wrote、> 引用、HTML 标签等"""
```

---

## 5. 数据存储设计

### 5.1 数据库概览

所有数据存储在单一 SQLite 文件 `/app/data/sunday_memory.db`（Railway Volume 持久化），共 8 张表。

### 5.2 表结构详情

#### memories — 长期记忆主表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | `mem_` + UUID前12位 |
| `user_id` | TEXT NOT NULL | 用户标识（目前固定 "daily"） |
| `category` | TEXT | 12分类之一 |
| `content` | TEXT | 用户原始消息 |
| `summary` | TEXT | LLM 生成的简洁概括 |
| `tags` | TEXT | JSON 数组 |
| `importance` | TEXT | low/medium/high/critical |
| `source` | TEXT | auto/manual |
| `access_count` | INTEGER | 被检索次数 |
| `decay_factor` | REAL | 衰减系数 (1.0 → 0.0) |
| `related_to` | TEXT | 关联记忆 ID |
| `status` | TEXT | active/archived |
| `archived` | INTEGER | 0=活跃, 1=归档 |
| `created_at` | TEXT | ISO 时间戳 |
| `updated_at` | TEXT | ISO 时间戳 |
| `last_accessed` | TEXT | ISO 时间戳 |

**索引**：`(user_id, status)`, `(user_id, category)`, `(user_id, importance)`, `(created_at DESC)`

#### conversation_flow — 对话流

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK AUTOINCREMENT | 自增主键 |
| `user_id` | TEXT | 用户标识 |
| `role` | TEXT | "user" 或 "assistant" |
| `content` | TEXT | 对话内容 |
| `tokens_used` | INTEGER | 消耗的 token 数 |
| `created_at` | TEXT | ISO 时间戳 |

**索引**：`(user_id, created_at DESC)`

#### memory_tags — 标签统计

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK AUTOINCREMENT | 自增主键 |
| `user_id` | TEXT | 用户标识 |
| `tag` | TEXT | 标签名 |
| `count` | INTEGER | 出现次数 |

**唯一约束**：`(user_id, tag)`

#### memory_links — 记忆关联

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK AUTOINCREMENT | 自增主键 |
| `user_id` | TEXT | 用户标识 |
| `memory_id_a` | TEXT | 记忆 A ID |
| `memory_id_b` | TEXT | 记忆 B ID |
| `relation` | TEXT | 关联类型 |
| `created_at` | TEXT | ISO 时间戳 |

**唯一约束**：`(memory_id_a, memory_id_b)`

#### push_log — 推送记录

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK AUTOINCREMENT | 自增主键 |
| `user_id` | TEXT | 用户标识 |
| `push_type` | TEXT | 推送类型 |
| `message` | TEXT | 推送内容摘要 |
| `pushed_at` | TEXT | ISO 时间戳 |

**索引**：`(user_id, push_type, pushed_at DESC)`

#### knowledge_base — 知识库

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | 知识条目 ID |
| `user_id` | TEXT | 用户标识 |
| `kb_type` | TEXT | 知识类型 |
| `title` | TEXT | 标题 |
| `content` | TEXT | 内容 |
| `tags` | TEXT | JSON 数组 |
| `source_url` | TEXT | 来源 URL |
| `image_url` | TEXT | 配图 URL |
| `pushed_at` | TEXT | 推送时间 |
| `created_at` | TEXT | 创建时间 |

**索引**：`(user_id, pushed_at DESC)`

#### feedback — 改进反馈

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | 反馈 ID |
| `user_id` | TEXT | 用户标识 |
| `fb_type` | TEXT | improvement/bug/todo/ux |
| `title` | TEXT | 标题 |
| `detail` | TEXT | 详细描述 |
| `source` | TEXT | telegram/api |
| `status` | TEXT | open/in_progress/done |
| `ai_category` | TEXT | AI 自动分类 |
| `priority` | TEXT | low/medium/high |
| `created_at` | TEXT | ISO 时间戳 |
| `updated_at` | TEXT | ISO 时间戳 |

**索引**：`(user_id, status)`

#### sunday_logs — 运行日志

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | `log_` + UUID前10位 |
| `log_type` | TEXT | chat/reply/error/memory/push |
| `user_id` | TEXT | 用户标识 |
| `source` | TEXT | api/telegram/imap |
| `summary` | TEXT | 日志摘要 |
| `detail` | TEXT | 详细信息 |
| `status` | TEXT | ok/error |
| `created_at` | TEXT | ISO 时间戳 |

---

## 6. LLM 调用完整链路

### 6.1 聊天请求（POST /api/chat）

```
用户消息 "我今天好累啊"
│
├── verify_key() — X-API-Key 认证
│
├── 解析请求体 — JSON/Form/纯文本 兼容
│
├── [特殊指令检测]
│   └── "记住xxx" → LLM 提取 → 存储 → 直接返回
│
├── should_search() → 需要搜索？
│   └── 触发 → DuckDuckGo → 注入 enhanced_message
│
├── asyncio.gather (并行执行)
│   │
│   ├── Task A: LLM 对话
│   │   ├── select_model("我今天好累啊") → 聊天模式
│   │   ├── _build_prompt() → System Prompt 注入:
│   │   │   ├── {user_profile} ← "职业iOS开发者、喜欢美式咖啡、正在做电商App..."
│   │   │   ├── {conversation_flow} ← "用户: 早安 / Sunday: 早安呀酱酱~ ..."
│   │   │   ├── {memories} ← 关键词检索 "累" → 匹配记忆
│   │   │   └── {chat_mode} ← "💬 聊天模式"
│   │   └── client.chat.completions.create()
│   │       model="doubao-seed-2-0-pro-260215"
│   │       max_tokens=800
│   │       temperature=0.8
│   │       → "是不是最近做电商项目太拼啦？记得你上次说在赶进度呢，要好好休息哦~"
│   │
│   └── Task B: 记忆提取
│       └── extract_memories_from_message()
│           → LLM 分析 → JSON → 质量过滤 → store() × N
│
├── _force_extract_info() — 正则强制提取
│
├── add_conversation() × 2 — 写入对话流
│
└── 返回 ChatResponse JSON
```

### 6.2 SSE 流式聊天（POST /api/chat/stream）

```
与 /api/chat 相同的前置处理
│
└── LLMService.chat_stream()
    └── client.chat.completions.create(stream=True)
        └── async for chunk:
            yield "data: {\"type\":\"text\",\"content\":\"...\"}\n\n"
        └── yield "data: {\"type\":\"done\"}\n\n"
```

### 6.3 Telegram 聊天

```
与 /api/chat 相同的核心逻辑，区别：
- 回复长度智能选择：800/2000/不限制
- 智能分段发送（_send_smart_reply）
- 先发"正在输入..."状态
- 邮件记忆额外注入（24h 内推送的邮件）
```

---

## 7. API 接口文档

### 7.1 认证方式

所有 `/api/*` 端点需要以下任一方式认证：

- **Header**: `X-API-Key: sunday-2026`
- **Query**: `?api_key=sunday-2026`

### 7.2 核心接口

#### POST /api/chat — 聊天

**请求体**（支持三种格式）：
```json
{"message": "今天天气怎么样？", "session_id": "default"}
```
或
```
message=今天天气怎么样？&session_id=default
```
或纯文本：
```
今天天气怎么样？
```

**响应**：
```json
{
  "reply": "今天上海天气不错呢，适合出门走走~",
  "session_id": "default",
  "tokens_used": 156,
  "model": "doubao-seed-2-0-pro-260215",
  "memories_stored": 1
}
```

#### POST /api/chat/stream — SSE 流式聊天

**请求体**：同 `/api/chat`

**响应**（Server-Sent Events）：
```
data: {"type":"text","content":"今天"}

data: {"type":"text","content":"上海"}

data: {"type":"text","content":"天气不错呢~"}

data: {"type":"done"}
```

#### GET /api/push/pending — 检查待推送

**响应**：
```json
{
  "should_push": true,
  "push_type": "morning",
  "subject": "早安呀酱酱~",
  "html_body": "<html>...</html>"
}
```

或无需推送时：
```json
{
  "should_push": false,
  "reason": "今天已经推过早安了"
}
```

#### GET /api/memory/stats — 记忆统计

**响应**：
```json
{
  "total": 156,
  "by_category": {"fact": 23, "preference": 18, ...},
  "by_importance": {"critical": 5, "high": 32, "medium": 89, "low": 30},
  "recent_chats": 42
}
```

#### GET /api/memory — 记忆列表

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `user_id` | string | 用户标识 |
| `category` | string | 筛选分类 |
| `importance` | string | 筛选重要性 |
| `query` | string | 关键词搜索 |
| `limit` | int | 返回条数（默认20） |
| `offset` | int | 偏移量 |

#### POST /api/memory — 手动添加记忆

**请求体**：
```json
{
  "user_id": "daily",
  "content": "用户说今天吃了火锅",
  "category": "preference",
  "tags": ["火锅", "美食"],
  "importance": "medium"
}
```

#### POST /api/memory/search — 记忆搜索

**请求体**：
```json
{
  "query": "火锅",
  "category": "preference",
  "limit": 10
}
```

#### DELETE /api/memory/{id} — 删除记忆

无请求体。返回 `{"ok": true}` 或 404。

#### POST /api/memory/{id}/archive — 归档记忆

无请求体。记忆状态变为 archived，不再出现在普通查询中。

#### POST /api/memory/decay — 触发记忆衰减

无请求体。对所有低重要性、低访问的记忆执行衰减。

#### GET /api/memory/export — 导出 JSON

返回所有活跃记忆的 JSON 数组。

#### GET /api/memory/export/csv — 导出 CSV

返回 CSV 格式的记忆列表（含 BOM，支持 Excel 直接打开中文）。

#### POST /api/generate/report — 生成报告

**请求体**：
```json
{
  "topic": "AI语音助手技术调研",
  "style": "academic"
}
```

---

## 8. 设计哲学与核心决策

### 8.1 "真人感"设计

Sunday 不是工具，是伙伴。每个设计决策都围绕"更像真人"：

- **智能分段**：AI 用 `\n\n` 自然分段，代码不干预分段逻辑
- **随机停顿**：1-3.5 秒的随机延迟，模拟"在想下一句说什么"
- **呼吸感称呼**：不是每条消息都叫名字，像真人朋友一样自然
- **主动关联**：不机械地说"根据记忆"，而是自然提及

### 8.2 记忆安全

> **LLM 可以读取记忆，但不能修改或删除。**

这是架构层面的安全边界。记忆的增删改只能通过：
- 正则强制提取（固定句式）
- LLM 提取 + 质量过滤
- 用户主动操作（命令/API/Dashboard）

### 8.3 双重提取 + 质量过滤

单靠 LLM 或正则都不够可靠，两者互补：

| 方式 | 优势 | 劣势 |
|------|------|------|
| 正则 | 零延迟、精确匹配 | 只能覆盖固定句式 |
| LLM | 语义理解、灵活 | 可能误判、有延迟 |
| 组合 | 覆盖全面 | 需要去重逻辑 |

质量过滤确保不会存储垃圾记忆：含问号/省略号/反问/过长昵称的记忆被自动拒绝。

### 8.4 频道独立

创意推送采用**双通道分离**：

- **Telegram 聊天框**：简短告知（"✍️ 好的！正在为你创作一篇夏日随笔~ 写好了，发到你邮箱啦 📬"）
- **邮件**：完整内容（AI 设计的精美 HTML 邮件）

避免聊天框被长篇内容刷屏，也避免邮件内容与聊天内容重复。

### 8.5 统一用户标识

所有通道（API、Telegram、IMAP）映射到同一个 `user_id = "daily"`，确保记忆、对话流、推送记录跨通道共享。

---

## 9. 部署架构

### 9.1 Railway 部署

```
┌─────────────────────────────────────────┐
│              Railway 云平台              │
│  ┌─────────────────────────────────┐    │
│  │        Docker 容器               │    │
│  │  Python 3.11-slim               │    │
│  │  uvicorn app.main:app           │    │
│  │  PORT: $PORT (自动分配)          │    │
│  │  ┌──────────────────────────┐   │    │
│  │  │   /app/data/              │   │    │
│  │  │   sunday_memory.db        │   │    │
│  │  │   (Volume 持久化)          │   │    │
│  │  └──────────────────────────┘   │    │
│  └─────────────────────────────────┘    │
│                                         │
│  健康检查: GET /health (30s间隔)         │
└─────────────────────────────────────────┘
```

### 9.2 Dockerfile 关键配置

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# 数据目录用于 Railway Volume 挂载
RUN mkdir -p /app/data
# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:$PORT/health || exit 1
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

### 9.3 部署命令

```bash
cd /workspace/sundayos/backend
railway up --service <service-id>
```

**注意**：必须在 `backend/` 目录下运行，因为 Dockerfile 在 `backend/` 中。

### 9.4 环境变量清单

```bash
# 必需
LLM_API_KEY=your_doubao_api_key
RESEND_API_KEY=your_resend_api_key
PUSH_EMAIL=your_email@example.com
TELEGRAM_TOKEN=your_bot_token

# 可选
SUNDAY_API_KEY=sunday-2026           # API 认证密钥
LLM_MODEL=doubao-seed-2-0-pro-260215 # 聊天模型
LLM_MODEL_PRO=                       # 专业模型
LLM_TEMPERATURE=0.8                  # LLM 温度
LLM_MAX_TOKENS=1500                  # 最大 token
RESEND_FROM_EMAIL=                   # 发件邮箱
ASSISTANT_NAME=Sunday                # 助手名称
IMAP_PASSWORD=                       # iCloud 应用密码
```

---

## 10. 语音系统方案（待实现）

### 10.1 方案概述

**方案 B：全火山引擎豆包生态**

| 组件 | 模型 | 接口 | 月成本 |
|------|------|------|--------|
| ASR | 豆包流式 ASR 2.0 | WebSocket `bigmodel_async` | ≈¥0 |
| TTS | 豆包声音克隆 2.0 | HTTP POST `seed-icl-2.0` | ≈¥2 |
| LLM | 豆包 Seed 2.0（现有） | HTTP | 不变 |

### 10.2 推荐模型

**ASR：豆包流式语音识别模型 2.0**
- Resource ID: `volc.seedasr.sauc.duration`
- WebSocket: `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async`
- 支持格式: pcm/wav/ogg/mp3

**TTS：豆包声音克隆 2.0**
- Resource ID: `seed-icl-2.0`
- HTTP: `POST https://openspeech.bytedance.com/api/v3/tts/unidirectional`
- 音色：录制 10-30 秒音频克隆
- 情感控制：`context_texts` 自然语言描述
- 备选预设音色：Vivi (`zh_female_vv_uranus_bigtts`)

### 10.3 数据流

```
用户 Telegram 语音消息 (.ogg)
  → 下载 → ffmpeg 转 PCM (16kHz)
  → WebSocket 豆包 ASR 2.0 → 识别文字
  → 复用现有 LLM 逻辑 → 生成回复 + 情感标签
  → VoiceService.synthesize_with_emotion()
  → 上传 MP3 → sendVoice() + sendMessage()
```

### 10.4 新增文件

- `backend/app/voice_service.py` — VoiceService 类（ASR WebSocket + TTS HTTP）
- 修改 `backend/app/config.py` — 新增 8 个语音配置项
- 修改 `backend/app/telegram_bot.py` — 新增 `handle_voice_message()` + 提取 `_process_message_text()`

### 10.5 情感控制速查表

| Sunday 情绪 | context_text 描述 |
|-------------|-------------------|
| 撒娇甜蜜 | `用甜蜜撒娇的声音，像在跟男朋友撒娇，语调上扬很开心` |
| 温柔安慰 | `用温柔舒缓的声音，轻声细语地安慰，让人感到安心` |
| 激动兴奋 | `用非常激动兴奋的语气，开心到快要尖叫了` |
| 慵懒日常 | `用慵懒随意的声音，软绵绵的很放松，像刚睡醒在聊天` |
| 委屈撒娇 | `用委屈撒娇的声音，语调微微上扬，带着一点小情绪` |

---

## 11. 常见问题与排错

### 11.1 部署问题

**Q: Railway 部署失败，提示找不到 Dockerfile**

A: 必须在 `backend/` 目录下运行 `railway up`，因为 Dockerfile 在 `backend/` 中。

**Q: 数据库文件丢失，记忆全部清空**

A: 确保 Railway Volume 正确挂载到 `/app/data`。检查 `railway.json` 或 Dashboard 中的 Volume 配置。

### 11.2 LLM 问题

**Q: LLM 返回空回复**

A: 检查 `LLM_API_KEY` 是否正确，豆包账户余额是否充足。

**Q: LLM 回复中包含奇怪的称呼**

A: 使用 `/clean_nick` 命令查看和清理昵称记忆，然后重新告诉 Sunday 你想要的称呼。

### 11.3 邮件问题

**Q: 邮件没有推送**

A: 检查 `RESEND_API_KEY` 和 `PUSH_EMAIL` 是否配置。调用 `GET /api/push/pending` 检查推送决策。

**Q: 邮件内容重复**

A: 检查 `push_log` 表确认去重是否生效。推送类型有独立的去重逻辑。

### 11.4 记忆问题

**Q: LLM 提取了不想要的记忆**

A: 使用 `/memory` 命令或 Dashboard 手动删除/归档。质量过滤规则在 `_is_quality_memory()` 中。

**Q: 对话流太长导致 System Prompt 超限**

A: 对话流有两级衰减机制（24h 完整 / 72h 摘要），自动控制长度。

---

## 12. 开发日志摘要

### 主要版本历程

| 版本 | 日期 | 关键变化 |
|------|------|----------|
| v1.0.0 | - | 初始版本，基础聊天 API |
| v2.0.0 | - | 重构记忆系统，12 分类 + 4 级重要性 |
| v3.0.0 | - | 添加 Telegram Bot、邮件推送、AI 设计引擎 |
| v3.1.0 | - | 添加 IMAP 监听、文件生成、Dashboard |
| v3.2.0 | - | 添加知识推送、创意推送、AI 意图判断 |
| v3.2.1-4 | 2026-07 | 修复邮件系统 5 个 Bug |
| v3.3.0 | 2026-07 | 统一记忆上下文构建器，消除情感断层 |
| v3.4.0-2 | 2026-07 | 修复 NameError、KeyError 等运行时错误 |
| v3.5.0-1 | 2026-07 | 昵称智能理解（LLM 驱动）、/clean_nick 命令 |
| v3.6.0 | 计划中 | 语音系统（ASR + TTS） |

### 当前版本：v3.5.1

完整开发日志见 `/workspace/sundayos/CHANGELOG.md`。

---

## 附录：快速开发指南

### 本地运行

```bash
cd /workspace/sundayos/backend

# 安装依赖
pip install -r requirements.txt

# 创建 .env 文件（填入你的 API Key）
cat > .env << EOF
LLM_API_KEY=your_doubao_api_key
RESEND_API_KEY=your_resend_key
PUSH_EMAIL=your_email@example.com
TELEGRAM_TOKEN=your_bot_token
EOF

# 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 添加新功能的规范

1. **配置**：新配置项添加到 `config.py` 的 `Settings` 类
2. **数据库**：新表在 `memory.py` 的 `init_db()` 中创建
3. **API**：新路由添加到 `main.py`
4. **日志**：使用 `logger.log()` 记录关键事件
5. **更新 CHANGELOG.md**：遵循已有的格式规范

### 代码风格

- Python 3.11+ 类型注解
- 异步优先（`async/await`）
- 模块级单例（`settings`、`memory_store`、`llm_service`）
- 函数单一职责
- 错误优雅降级，不阻塞主流程

---

> **文档维护**：本文档应随项目版本同步更新。每次重大架构变更后，请更新对应章节。
