# SundayOS — 你的 iPhone 外置大脑

> 像钢铁侠的贾维斯一样，SundayOS 是一个拥有记忆和人格的个人 AI 助手。
> **现在支持国内免费 AI，零成本验证！**

## 🧠 这是什么？

SundayOS 运行在你的 iPhone 上，通过「快捷指令」作为入口，连接云端的 AI 大脑。它不只是回答问题——它会**记住**你是谁、你的爱好、你的日程、你关心的人。随着时间的推移，它会变得越来越了解你。

```
你说："帮我查一下明天的天气"
Sunday："明天北京晴转多云，18-25°C。对了小明，你明天上午10点有个会议，记得带伞哦～"

你说："我今天心情不太好"
Sunday："发生什么了？上次你提到项目压力大，是那个事吗？"
```

## 🆓 免费验证方案

SundayOS 现在支持 **四个 LLM 供应商**，切换只需改一行配置：

| 供应商 | 免费额度 | 模型 | 注册方式 |
|--------|---------|------|---------|
| 🥇 **蚂蚁百灵** | **50万 token/天** | Ling-2.6-1T | 注册即用 |
| 🥈 **阿里通义千问** | 2000次/天 | qwen-plus | 阿里云账号 |
| 🥉 OpenAI | 付费 | gpt-4o-mini | 绑定信用卡 |
| 🔧 自定义 | 取决于你的API | 任意 | 兼容 OpenAI 格式即可 |

> 💡 **推荐蚂蚁百灵**：额度最大、OpenAI 完全兼容、每日 50 万 token 免费

## 🚀 3 分钟跑起来

### 1. 获取免费 API Key

#### 蚂蚁百灵（推荐）

1. 打开 https://chat.ant-ling.com/open
2. 注册账号并登录
3. 点击「创建令牌」
4. 复制令牌（格式：`ant_xxxxxx`）

#### 阿里通义千问（备选）

1. 打开 https://modelscope.cn
2. 登录阿里云账号 → 个人中心 → 访问令牌
3. 创建令牌，勾选「大模型推理」权限
4. 复制 Token（格式：`sk-xxxxxx`）

### 2. 配置并启动

```bash
cd sundayos/backend

# 安装依赖
pip install -r requirements.txt

# 配置 API Key
# 编辑 .env 文件，设置：
#   LLM_API_KEY=你的Key
#   （默认使用 Ling Studio，无需修改 LLM_PROVIDER）

# 启动
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. 切换供应商

编辑 `.env` 中的 `LLM_PROVIDER` 即可：

```env
# 用蚂蚁百灵（默认）
LLM_PROVIDER=ling_studio
LLM_API_KEY=ant_your_key
LLM_MODEL=Ling-2.6-1T

# 或切换到通义千问
# LLM_PROVIDER=dashscope
# LLM_API_KEY=sk_your_key
# LLM_MODEL=qwen-plus

# 或切换到 OpenAI
# LLM_PROVIDER=openai
# LLM_API_KEY=sk_your_key
# LLM_MODEL=gpt-4o-mini
```

### 4. 测试

```bash
# 健康检查
curl http://localhost:8000/health

# 发送第一条消息
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sunday-os-dev-key-change-in-production" \
  -d '{"message": "你好Sunday，我是小明，我喜欢跑步和编程", "user_id": "xiaoming"}'
```

### 5. 配置 iPhone 快捷指令

详见 [📱 iPhone 配置指南](docs/USER_GUIDE.md)

## 📡 API 参考

```bash
# 基础对话
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"message": "你好", "user_id": "user123"}'

# 流式对话（SSE 打字机效果）
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"message": "讲个笑话", "user_id": "user123"}'

# 搜索记忆
curl -X POST http://localhost:8000/api/memory/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"user_id":"user123","query":"我的爱好"}'

# 可用技能
curl "http://localhost:8000/api/skills/available?api_key=your-key"
```

## 💰 成本对比

| 方案 | 月费 | 日额度 |
|------|------|--------|
| 🆓 蚂蚁百灵 | **¥0** | 50万 token |
| 🆓 通义千问 | **¥0** | 2000次 |
| 💰 OpenAI gpt-4o-mini | ¥30-80 | 按量付费 |
| 🖥️ 本地部署 | ¥0 | 取决于硬件 |

## 🔒 隐私

- 所有数据存储在你自己的服务器上
- API Key 鉴权保护
- 支持一键删除所有记忆和画像
- 不会与任何第三方共享数据

## 📂 项目结构

```
sundayos/
├── backend/                 # 后端服务
│   ├── app/
│   │   ├── main.py         # FastAPI 入口
│   │   ├── config.py       # 配置管理（多供应商支持）
│   │   ├── routers/        # API 路由
│   │   │   ├── chat.py     # 对话接口（支持流式）
│   │   │   ├── memory.py   # 记忆接口（语义搜索）
│   │   │   ├── user.py     # 用户画像
│   │   │   └── skills.py   # 技能接口
│   │   ├── services/       # 核心服务
│   │   │   ├── llm_service.py      # LLM 引擎（多供应商）
│   │   │   ├── memory_service.py   # 记忆系统（四层架构）
│   │   │   ├── user_service.py     # 画像引擎
│   │   │   └── skill_service.py    # 技能调度
│   │   ├── models/         # 数据模型
│   │   └── middleware/     # 中间件
│   ├── .env.example        # 环境变量模板
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── requirements.txt
├── shortcuts/              # iPhone 快捷指令配置
└── docs/                   # 文档
    ├── ARCHITECTURE.md     # 架构设计
    └── USER_GUIDE.md       # iPhone 配置指南
```
