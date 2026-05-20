# ================================================================
# Python 全功能爬虫平台 — 生产环境 Docker 镜像
# ================================================================
FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="CrawlerX"
LABEL org.opencontainers.image.description="Python full-stack crawler platform"

# ---- 环境变量 ----
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# ---- 安装系统依赖 (Chromium + ffmpeg + 中文字体) ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Playwright 浏览器依赖
    libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libasound2 libpango-1.0-0 libcairo2 libatspi2.0-0 \
    # ffmpeg (视频合并)
    ffmpeg \
    # 中文字体 (matplotlib 词云用)
    fonts-noto-cjk \
    # 工具
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---- 安装 Playwright + Chromium ----
RUN pip install playwright==1.52.0 \
    && playwright install chromium \
    && playwright install-deps chromium

# ---- 工作目录 ----
WORKDIR /app

# ---- 先装依赖 (利用 Docker 层缓存) ----
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- 复制源码 ----
COPY . .

# ---- 数据目录 ----
RUN mkdir -p /app/data/json /app/data/csv /app/data/db /app/data/videos /app/data/charts /app/data/demo /app/logs

# ---- 健康检查 ----
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8800/ || exit 1

# ---- 端口 ----
EXPOSE 8800

# ---- 启动 ----
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8800", "--workers", "1", "--limit-concurrency", "20"]
