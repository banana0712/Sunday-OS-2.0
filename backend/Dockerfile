FROM python:3.11-slim
WORKDIR /app

# 环境变量
ENV PYTHONUNBUFFERED=1

# 系统依赖（ffmpeg 用于语音转码）
RUN apt-get update && apt-get install -y curl ffmpeg && rm -rf /var/lib/apt/lists/*

# 数据持久化目录（不用 VOLUME，CloudBase 用环境变量挂载）
RUN mkdir -p /app/data

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY app/ ./app/

# 健康检查（给足启动时间，SQLite 初始化可能需要几秒）
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

EXPOSE ${PORT:-8000}

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
