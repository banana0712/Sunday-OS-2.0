╔══════════════════════════════════════════════════════════════╗
║            SundayOS 项目架构与原理详解                         ║
║            v2.0 — 不只是助手，是伙伴                           ║
╚══════════════════════════════════════════════════════════════╝

═══════════════════════════════════════════════════════════════
一、项目总览
═══════════════════════════════════════════════════════════════

SundayOS 是一个个人 AI 助手后端服务，部署在 Railway 云平台，
通过 REST API 为 iOS 快捷指令提供对话服务。

核心栈：
  - Web 框架：FastAPI (Python 3.11)
  - LLM 引擎：字节跳动豆包 (火山引擎)，OpenAI 兼容 API
  - 存储引擎：SQLite 3 + WAL 模式
  - 搜索引擎：DuckDuckGo (免费，无需 API Key)
  - 容器化：Docker + Railway 自动构建
  - 持久化：Railway Volume (挂载 /app/data)

项目结构：
  backend/
  ├── Dockerfile           # 容器定义
  ├── requirements.txt     # 依赖：fastapi, uvicorn, openai, ddgs, pydantic
  └── app/
      ├── config.py        # Settings 类，读取环境变量
      ├── main.py          # 主应用：路由、人设、LLM 调用、记忆提取、搜索调度
      ├── memory.py        # 记忆系统：SQLite CRUD、检索、衰减、对话流
      └── search.py        # 网络搜索：DuckDuckGo 搜索 + 结果格式化

═══════════════════════════════════════════════════════════════
二、记忆系统架构（核心）
═══════════════════════════════════════════════════════════════

SundayOS 的记忆系统模拟人脑的记忆机制，分为四个层级：

  🧠 感官记忆（秒级） → 当前对话，不存储
  🔥 工作记忆（≤24h） → 对话流，完整记录
  🌤 短期记忆（24-72h）→ 对话流，压缩摘要
  💎 长期记忆（永久）  → SQLite 结构化存储

2.1 数据库设计
───────────────────────────────────────────────────────────────

四张表：

┌─────────────────────────────────────────────────────────────┐
│ memories (长期记忆主表)                                       │
├──────────────────┬──────────────────────────────────────────┤
│ id               │ TEXT PK, 格式 mem_xxxxxxxxxxxx            │
│ user_id          │ TEXT, 用户标识 (来自 session_id)          │
│ category          │ TEXT, 12 种分类之一                       │
│ content           │ TEXT, 用户原始消息                        │
│ summary           │ TEXT, LLM 生成的简洁概括                  │
│ tags              │ TEXT, JSON 数组，如 ["咖啡","美式"]       │
│ importance        │ TEXT, low/medium/high/critical            │
│ source            │ TEXT, auto/manual                        │
│ access_count      │ INT, 被检索/引用的次数                    │
│ decay_factor      │ REAL, 衰减系数 (1.0 → 0.0)               │
│ related_to        │ TEXT, 关联记忆 ID                         │
│ created_at        │ TEXT, ISO 时间戳                          │
│ updated_at        │ TEXT, ISO 时间戳                          │
│ last_accessed     │ TEXT, 最后访问时间                        │
│ archived          │ INT, 0=活跃 1=归档                        │
└──────────────────┴──────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ conversation_flow (对话流 — 短期工作记忆)                      │
├──────────────────┬──────────────────────────────────────────┤
│ id               │ INTEGER PK AUTOINCREMENT                  │
│ user_id          │ TEXT                                      │
│ role             │ TEXT, "user" 或 "assistant"               │
│ content           │ TEXT, 对话内容                             │
│ tokens_used      │ INTEGER, 消耗的 token 数                   │
│ created_at        │ TEXT, ISO 时间戳                          │
└──────────────────┴──────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ memory_tags (标签统计表)                                      │
├──────────────────┬──────────────────────────────────────────┤
│ user_id + tag    │ UNIQUE 联合主键                            │
│ count            │ INT, 该标签出现次数                        │
└──────────────────┴──────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ memory_links (记忆关联表)                                     │
├──────────────────┬──────────────────────────────────────────┤
│ memory_id_a/b    │ 关联双方                                   │
│ relation         │ TEXT, auto/manual/related                  │
│ UNIQUE(a, b)     │ 防止重复关联                               │
└──────────────────┴──────────────────────────────────────────┘

索引：
  - idx_memories_user (user_id, archived)
  - idx_memories_category (user_id, category)
  - idx_memories_importance (user_id, importance)
  - idx_memories_created (created_at DESC)
  - idx_flow_user_time (user_id, created_at DESC)

2.2 12 类记忆分类
───────────────────────────────────────────────────────────────

  fact         📋 事实      "我是iOS开发者" "住在北京"
  preference   💝 偏好      "喜欢美式咖啡" "讨厌下雨"
  event        📅 行程      "明天下午3点面试" "下周去上海"
  relationship 👥 关系      "女朋友叫小红" "同事老王"
  goal         🎯 目标      "今年想学钢琴" "计划买房"
  habit        🔄 习惯      "每天7点起床" "每周健身3次"
  project      💼 项目      "正在做电商App" "负责CRM系统"
  research     🔬 科研      "研究方向是NLP" "在写论文"
  learning     📚 学习      "在学SwiftUI" "读完了设计模式"
  note         📝 笔记      通用笔记、临时备忘
  health       ❤️ 健康      "过敏花粉" "血压偏高"
  finance      💰 财务      "每月房贷8000" "买了比特币"

2.3 记忆重要性等级
───────────────────────────────────────────────────────────────

  low (0.3)     ⭐ 一般      临时笔记、一次性事件
  medium (0.5)  ⭐⭐ 重要    日常偏好、一般行程、普通关系
  high (0.7)    ⭐⭐⭐ 很重要  职业、学历、长期目标、重要项目
  critical (1.0) 💎 核心记忆  姓名、伴侣、住址、关键健康信息

═══════════════════════════════════════════════════════════════
三、数据流详解
═══════════════════════════════════════════════════════════════

3.1 聊天请求完整流程
───────────────────────────────────────────────────────────────

  用户消息
     │
     ▼
  ┌──────────────────┐
  │  POST /api/chat  │  ← API Key 验证 (X-API-Key header)
  └──────┬───────────┘
         │
         ├──→ 解析请求体 (JSON / Form / 纯文本 兼容)
         │
         ├──→ 「记住xxx」指令？
         │      ├─ YES → LLM 提取记忆 → 存储 → 直接返回
         │      └─ NO  → 继续
         │
         ├──→ 🌐 联网搜索判断 (should_search)
         │      ├─ 匹配搜索关键词 → DuckDuckGo 搜索
         │      └─ 搜索结果注入 enhanced_message
         │
         ├──→ asyncio.gather (并行执行)
         │      │
         │      ├── Task A: LLM 对话
         │      │    ├─ select_model(message) → 聊天/专业模式
         │      │    ├─ _build_prompt(user_id, message)
         │      │    │    ├─ _build_user_profile(user_id) → 用户画像
         │      │    │    ├─ get_conversation_context(user_id) → 对话流
         │      │    │    └─ memory_store.get_context(user_id, message)
         │      │    │         └─ search() → 相关性排序 → 分类分组
         │      │    ├─ client.chat.completions.create()
         │      │    └─ 返回 reply + model + tokens
         │      │
         │      └── Task B: LLM 记忆提取
         │           ├─ extract_memories_from_message()
         │           ├─ 发送提取 prompt 到 LLM
         │           ├─ 解析 JSON 响应
         │           └─ memory_store.store() × N
         │                ├─ _find_duplicate() → 去重
         │                ├─ INSERT INTO memories
         │                ├─ UPSERT memory_tags
         │                └─ _auto_link() → 关联记忆
         │
         ├──→ 强制信息提取 (_force_extract_info)
         │      ├─ 自我介绍：我是XX → fact / critical
         │      ├─ 关系定义：你是我的XX → relationship / high
         │      └─ 偏好表达：我喜欢XX → preference / medium
         │
         ├──→ 写入对话流
         │      ├─ add_conversation(user, user_id)
         │      └─ add_conversation(assistant, user_id)
         │
         └──→ 合并结果 → ChatResponse JSON

3.2 模型选择逻辑
───────────────────────────────────────────────────────────────

select_model(message):
  扫描 PRO_KEYWORDS 列表:
    ["论文","研究","文献","学术","实验","理论","算法",
     "代码","编程","bug","架构","设计模式","优化","技术",
     "为什么","怎么实现","原理","机制","帮我写","解释一下",
     "法律","金融","医学","投资","合同","数学","物理","化学"]
  
  匹配任一关键词 → LLM_MODEL_PRO (ep-m-20260219151504-vr965)
                    max_tokens = 1500
                    标签: "🧠 专业模式"
  
  无匹配 → LLM_MODEL (ep-m-20260707225516-zws7x)
            max_tokens = 400
            标签: "💬 聊天模式"

3.3 记忆提取机制（双重保障）
───────────────────────────────────────────────────────────────

第一层：正则强制提取 (_force_extract_info) — 零延迟
  自我介绍句式：
    "我是XX" / "我叫XX" / "我的名字是XX" / "可以叫我XX" / "叫我XX"
    → 存入 fact 类，critical 重要性
  
  关系定义句式：
    "你是我的XX" / "我是你的XX"
    → 存入 relationship 类，high 重要性
  
  偏好表达句式：
    "我喜欢XX" / "我超喜欢XX" / "我爱XX" / "我讨厌XX" / "我不喜欢XX"
    → 存入 preference 类，medium 重要性

第二层：LLM 语义提取 (extract_memories_from_message) — 深度理解
  将用户消息嵌入 MEMORY_EXTRACTION_PROMPT 模板：
    - 12 类记忆的详细定义
    - 重要性判断标准
    - 提取原则（只记有价值的，闲聊忽略）
    - 特别规则：用户自称的任何名字/昵称都要记住
  
  调用 LLM（Character 模型, temperature=0.3）：
    → 返回 JSON 数组 [{category, summary, tags, importance}, ...]
    → 逐条调用 memory_store.store()
    → 自动去重 + 标签更新 + 自动关联

3.4 对话流两级衰减
───────────────────────────────────────────────────────────────

get_conversation_context(user_id, max_turns=10):

  🔥 热记忆 (≤24h)：
    完整展示最近 10 轮对话
    格式：
      ## 最近的对话
      👤: 我今天心情特别好，因为刚完成了一个大项目
      💕Sunday: 太棒啦！完成大项目肯定超有成就感的🥳

  🌤 温记忆 (24-72h)：
    压缩为模糊摘要
    格式：
      ## 之前的对话（记忆模糊）
      用户提到了「我今天心情特别好...」
      Sunday回应了「太棒啦！完成大项目...」

  ❄️ 冷记忆 (>72h)：
    不注入。但重要信息已被提取到长期记忆中。

3.5 记忆检索与上下文注入
───────────────────────────────────────────────────────────────

get_context(user_id, message):
  
  1. search(user_id, query=message, limit=15)
     先按 user_id 过滤 → 关键词匹配打分 → 排序
     
     打分公式：
       score = (内容匹配×2 + 标签匹配×3) × 重要性系数×2 × (1+0.05×访问次数)
  
  2. 按分类分组，每类最多取 3 条
  
  3. 按优先级排序分类：
     fact > preference > event > project > relationship >
     goal > habit > research > learning > health > finance > note
  
  4. 格式化为 LLM 可读文本：
     [📋 事实 | ⭐⭐⭐ 很重要] 姓名为阿杰，职业是iOS开发者
     [💼 项目 | ⭐⭐ 重要] 正在做电商App项目，使用SwiftUI框架

_build_user_profile(user_id):
  单独提取核心信息构建用户画像：
    事实(3条) + 偏好(3条) + 行程(2条) + 项目(2条) + 关系(2条)
  
  示例输出: "姓名为阿杰，职业是iOS开发者、喜欢喝美式咖啡，每天两杯、
            下周五要去上海旅行、正在做电商App项目，使用SwiftUI框架、
            女朋友叫小红"

3.6 记忆衰减机制
───────────────────────────────────────────────────────────────

apply_decay(user_id, days=30):
  
  条件：
    - 创建超过 N 天
    - 重要性为 low 或 medium
    - 访问次数 < 3
    - 未归档
  
  操作：decay_factor *= 0.9
  
  效果：长期不被访问的低重要性记忆逐渐降权，
        在检索时排在后面，模拟人类记忆的自然遗忘。

═══════════════════════════════════════════════════════════════
四、网络搜索架构
═══════════════════════════════════════════════════════════════

4.1 搜索引擎
───────────────────────────────────────────────────────────────

  引擎：DuckDuckGo (via ddgs Python 库)
  成本：免费，无需 API Key
  限制：合理使用，无明显请求限制

4.2 触发机制
───────────────────────────────────────────────────────────────

  should_search(message):
    扫描 SEARCH_TRIGGERS 关键词列表：
      ["搜索", "查一下", "帮我查", "查查", "查找",
       "最新", "新闻", "热点", "时事", "最近发生",
       "什么是", "是谁", "怎么去", "多少钱", "天气",
       "股价", "股票", "汇率", "排名", "排行榜"]

  触发后：
    1. asyncio.to_thread(search_web, query, 5)
    2. format_search_results() 格式化为 LLM 可读文本
    3. 注入 enhanced_message：原文 + 搜索结果 + 指令
    4. LLM 基于搜索结果回答，保持 Sunday 风格

4.3 结果格式
───────────────────────────────────────────────────────────────

  [网络搜索结果]
  1. **标题**
     摘要内容...
     来源: https://...

  ↓ 注入 LLM prompt ↓

  请基于以上搜索结果回答用户的问题，语言保持Sunday的风格。

═══════════════════════════════════════════════════════════════
五、Sunday 人设系统
═══════════════════════════════════════════════════════════════

5.1 System Prompt 结构
───────────────────────────────────────────────────────────────

SUNDAY_SYSTEM_PROMPT 包含七个部分：

  ① 性格定义
     - 温柔体贴、活泼开朗
     - 有自己的情绪和想法
     - "不是复读机，而是一个有灵魂的伙伴"
  
  ② 说话方式
     - 语气词：「呢」「哦」「呀」「啦」
     - 称呼：叫名字/昵称
     - 长度：日常 1-3 句，像微信聊天
     - emoji：偶尔用，不过度
  
  ③ 深度上下文联动（核心差异化）
     - 主动联想：从当前话题联想到相关记忆
     - 自然提及：不说"根据记忆"，而是像老朋友
     - 关心跟进：记得之前的事，主动问进展
     - 情感共鸣：不只是记录，要理解情感
  
  ④ 用户画像感知
     {user_profile} — 动态生成的个人画像
  
  ⑤ 最近对话
     {conversation_flow} — 对话流上下文（两级衰减）
  
  ⑥ 完整记忆库
     {memories} — 按分类组织的长期记忆上下文
  
  ⑦ 对话模式
     {chat_mode} — "💬 聊天模式" 或 "🧠 专业模式"

5.2 动态变量注入
───────────────────────────────────────────────────────────────

每次请求，System Prompt 中的变量被实时填充：

  {current_time}       → "2026年07月07日 16:30，周2"
  {user_profile}       → "姓名为阿杰，职业是iOS开发者、喜欢喝美式咖啡..."
  {conversation_flow}  → 最近10轮对话（两级衰减）
  {memories}           → "[📋 事实 | ⭐⭐⭐] 姓名为阿杰...\n[💼 项目 | ⭐⭐] 正在做电商App..."
  {chat_mode}          → "💬 聊天模式"

═══════════════════════════════════════════════════════════════
六、部署架构
═══════════════════════════════════════════════════════════════

6.1 Railway 部署配置
───────────────────────────────────────────────────────────────

  平台: Railway (railway.app)
  区域: sfo (旧金山)
  服务: sunday-os
  Dockerfile: 自动检测并构建
  端口: $PORT 环境变量 (Railway 自动分配，通常 8080)
  
  持久化:
    Volume: sunday-os-volume
    挂载: /app/data
    内容: sunday_memory.db (SQLite 数据库)
  
  环境变量:
    SUNDAY_API_KEY = sunday-2026
    LLM_API_KEY     = ark-...
    LLM_MODEL       = ep-m-20260707225516-zws7x (Character)
    LLM_MODEL_PRO   = ep-m-20260219151504-vr965 (Pro)
    LLM_TEMPERATURE = 0.8
    LLM_MAX_TOKENS  = 1500

6.2 健康检查
───────────────────────────────────────────────────────────────

  HEALTHCHECK --interval=30s --timeout=10s --start-period=15s
    CMD curl -f http://localhost:$PORT/health

6.3 自动迁移
───────────────────────────────────────────────────────────────

  init_db() 后执行 _migrate():
    - 检测 memories 表的现有列
    - 自动添加缺失列 (如 summary, related_to)
    - 保证数据库向后兼容

═══════════════════════════════════════════════════════════════
七、API 参考
═══════════════════════════════════════════════════════════════

7.1 聊天
───────────────────────────────────────────────────────────────

POST /api/chat

请求头:
  X-API-Key: sunday-2026
  Content-Type: application/json

请求体:
  {"message": "你好呀", "session_id": "iphone-daily"}

响应:
  {
    "reply": "...",
    "session_id": "iphone-daily",
    "tokens_used": 350,
    "model": "ep-m-20260707225516-zws7x",
    "memories_stored": 1
  }

7.2 记忆 API
───────────────────────────────────────────────────────────────

GET    /api/memory/stats?user_id=xxx     记忆统计
GET    /api/memory?user_id=xxx           记忆列表
POST   /api/memory                       手动添加
POST   /api/memory/search                关键词搜索
PUT    /api/memory/{id}                  更新
DELETE /api/memory/{id}                  删除
POST   /api/memory/{id}/archive          归档
POST   /api/memory/{id}/unarchive        取消归档
POST   /api/memory/link                  关联记忆
GET    /api/memory/{id}/linked           查看关联
GET    /api/memory/export?user_id=xxx    导出全部
POST   /api/memory/decay?user_id=xxx     触发衰减

7.3 健康检查
───────────────────────────────────────────────────────────────

GET /health

═══════════════════════════════════════════════════════════════
八、安全设计
═══════════════════════════════════════════════════════════════

  - API Key 认证：所有 /api/* 端点需要 X-API-Key header
  - 用户隔离：所有记忆按 user_id 隔离存储
  - user_id 来源：从 session_id 中提取（去掉 "iphone-" 前缀）
  - 错误处理：所有异常被捕获，返回友好提示
  - API Key 清理：自动去除 "Bearer " 前缀

═══════════════════════════════════════════════════════════════
九、性能特征
═══════════════════════════════════════════════════════════════

  响应时间 (聊天模式):
    - 网络延迟: ~200-400ms (中国→旧金山)
    - LLM 推理: ~2-3s (豆包 Character 模型)
    - 记忆提取: 并行执行，不增加总延迟
    - 网络搜索: +1-3s (仅在触发搜索时)
    - 总耗时: ~3-4s (无搜索) / ~5-7s (有搜索)

  并发处理:
    - asyncio.gather 并行聊天+记忆提取
    - asyncio.to_thread 包装同步搜索
    - SQLite WAL 模式支持并发读

═══════════════════════════════════════════════════════════════
文件结束
═══════════════════════════════════════════════════════════════
