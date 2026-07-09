# Claude Code 接手 SundayOS — CMD 版操作指南

> Windows CMD 专属，每一步都验证过，照着敲就行。

---

## 第 0 步：先确认你电脑上有什么

打开 CMD（Win+R → 输入 `cmd` → 回车），依次输入以下命令检查：

```batch
node --version
```

```batch
npm --version
```

```batch
git --version
```

如果都显示版本号（比如 `v22.13.0`），说明环境 OK，跳到**第一步**。

如果某个命令提示"不是内部或外部命令"：

- **node/npm 没装** → 去 https://nodejs.org 下载 LTS 版，双击安装（一路 Next，全默认）
- **git 没装** → 去 https://git-scm.com/download/win 下载，双击安装（一路 Next）

装完后**关闭 CMD 重新打开**，再检查一次。

---

## 第一步：安装 Claude Code

在 CMD 里输入：

```batch
npm install -g @anthropic-ai/claude-code
```

等待安装完成（可能需要 1-2 分钟）。

验证：

```batch
claude --version
```

看到版本号就说明装好了。

---

## 第二步：获取并配置 API Key

### 2.1 获取 Key

**方案 A（官方，需要外网 + 信用卡）：**
1. 浏览器打开 https://console.anthropic.com
2. 注册/登录 Anthropic 账号
3. 左侧菜单 → API Keys → Create Key
4. 复制 Key（格式 `sk-ant-api03-xxxxxxxxx`）

**方案 B（中转站，国内直接用，支付宝充值）：**
1. 浏览器打开 https://api.cphone.vip
2. 注册/登录
3. 左侧 API 令牌 → 创建 Key
4. 复制 Key（格式 `sk-xxxxxxxxx`）

### 2.2 设置环境变量

在 CMD 里输入（把 `你的Key` 替换成你复制的那个）：

```batch
setx ANTHROPIC_API_KEY "你的Key"
```

然后**关闭 CMD，重新打开一个新的 CMD 窗口**。

验证是否生效：

```batch
echo %ANTHROPIC_API_KEY%
```

应该显示你的 Key。

---

## 第三步：克隆 SundayOS 项目

在 CMD 里：

```batch
cd %USERPROFILE%\Desktop

git clone https://github.com/banana0712/Sunday-OS-2.0.git

cd Sunday-OS-2.0
```

现在桌面上就有一个 `Sunday-OS-2.0` 文件夹了。

---

## 第四步：让 Claude Code 认识 SundayOS

### 4.1 启动 Claude Code

确保你在项目目录：

```batch
cd %USERPROFILE%\Desktop\Sunday-OS-2.0
claude
```

第一次运行会问：
- "Allow Claude to read files?" → 输入 `yes`
- "Allow Claude to modify files?" → 输入 `yes`
- 可能会让你选默认模型 → 选推荐的就行

然后你会进入一个聊天界面，可以开始对话了！

### 4.2 让 Claude 学习项目

进入 Claude Code 后，**一条一条**输入以下指令：

**第一条：**
```
请你先完整阅读 SundayOS_技术文档.md 和 Claude对接SundayOS指南.md 这两份文件。读完后用自己的话总结 SundayOS 是什么。
```

**第二条（等第一条完成后）：**
```
现在请浏览项目代码结构，重点看 backend/app/ 下的所有 .py 文件。告诉我每个文件是做什么的。
```

**第三条：**
```
帮我查看当前 git 状态和最近 3 条 commit。
```

如果 Claude 都能正确回答，说明它已经完全理解项目了。

---

## 第五步：日常工作流程

### 加新功能

```
我想给 Sunday 加一个功能：[描述你要的功能]
请先给我实现计划，不要改代码。我确认后你再动手。
```

### 修 bug

```
我发现一个 bug：[描述问题]
请帮我排查原因，找到后直接修复。
```

### 改完后部署

```
改好了，请帮我：
1. git add 所有改动
2. git commit（写好 commit message）
3. git push 到 GitHub

然后告诉我部署到 Railway 的命令。
```

### 查看部署日志

```batch
cd %USERPROFILE%\Desktop\Sunday-OS-2.0\backend
railway logs
```

### 部署上线

```batch
cd %USERPROFILE%\Desktop\Sunday-OS-2.0\backend
railway up
```

> ⚠️ 重要：部署必须从 `backend` 目录运行，不是项目根目录！

---

## 第六步：万能启动指令

以后每次打开 Claude Code，直接把下面这段话粘贴进去：

```
你现在是 SundayOS 项目的专属 AI 工程师。

项目位置：%USERPROFILE%\Desktop\Sunday-OS-2.0
文档：SundayOS_技术文档.md（完整架构）、Claude对接SundayOS指南.md（服务对接）
仓库：https://github.com/banana0712/Sunday-OS-2.0
部署平台：Railway，项目名 sunday-os
部署命令：cd backend && railway up

你的权限：
- ✅ 可以读写项目文件
- ✅ 可以执行 git commit/push
- ✅ 可以运行 railway 命令
- ❌ 不能改 Railway 环境变量（密钥都在上面配好了）
- ❌ 不要创建 .env 文件（不需要）

请先阅读 SundayOS_技术文档.md，然后告诉我你准备好了。
```

---

## 常见问题

### Q: CMD 里输入 claude 提示"不是内部命令"

**A:** npm 全局目录没加到 PATH。试试这个：

```batch
npm config get prefix
```

会显示一个路径，比如 `C:\Users\你的用户名\AppData\Roaming\npm`。把这个路径加到系统环境变量 PATH 里，然后重新打开 CMD。

或者直接用 npx 运行（每次都要加 npx）：

```batch
npx @anthropic-ai/claude-code
```

### Q: 没有 GitHub 推送权限

**A:** 先 Fork 项目：
1. 浏览器打开 https://github.com/banana0712/Sunday-OS-2.0
2. 右上角 Fork → 选择你自己的账号
3. 然后克隆你 Fork 的地址：

```batch
git clone https://github.com/你的用户名/Sunday-OS-2.0.git
```

### Q: Claude 改坏了代码怎么恢复？

**A:** 
```batch
git diff          → 看改了什么
git checkout .    → 撤销所有改动
```

### Q: 怎么退出 Claude Code？

**A:** 输入 `/exit` 或者按 `Ctrl+C`。

---

## 速查卡

| 操作 | CMD 命令 |
|------|----------|
| 进入项目 | `cd %USERPROFILE%\Desktop\Sunday-OS-2.0` |
| 启动 Claude | `claude` |
| 查看改动 | `git diff` |
| 提交代码 | `git add . && git commit -m "描述"` |
| 推送代码 | `git push` |
| 部署上线 | `cd backend && railway up` |
| 查看日志 | `cd backend && railway logs` |
| 撤销改动 | `git checkout .` |
