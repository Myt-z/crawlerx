# CrawlerX 部署指南

## 方式 1: Docker (推荐 — 功能最完整)

Docker 镜像自带 Chromium + ffmpeg + 中文字体，所有功能都能用。

```bash
# 构建
docker build -t crawlerx .

# 本机运行 (数据持久化)
docker-compose up -d

# 访问
# http://localhost:8800
```

## 方式 2: Railway (最简单)

[Railway](https://railway.app) 支持 Docker 部署，且 Playwright 浏览器能正常运行。

### 步骤:
1. 注册 https://railway.app (GitHub 登录)
2. 创建新项目 → "Deploy from GitHub repo"
3. Railway 自动检测 Dockerfile 并构建
4. 部署完成后获得链接: `https://crawlerx.up.railway.app`

```bash
# 或者用 CLI:
railway login
railway init
railway up
```

## 方式 3: Fly.io

Fly.io 免费额度支持 3 台 VM，Docker 原生支持。

```bash
# 安装 flyctl: https://fly.io/docs/hands-on/install-flyctl/

fly launch   # 自动检测 Dockerfile
fly deploy
fly open     # 打开 https://crawlerx.fly.dev
```

## 方式 4: Render

[Render](https://render.com) 支持 Docker 或 native Python。

### 原生 Python 方式 (不用 Docker):
1. 注册 → New Web Service
2. 连接 GitHub repo
3. Build Command:
   ```
   pip install -r requirements.txt
   playwright install chromium
   playwright install-deps chromium
   ```
4. Start Command:
   ```
   uvicorn server:app --host 0.0.0.0 --port $PORT
   ```

## 方式 5: 自己的 VPS

在 Ubuntu/Debian VPS 上直接部署:

```bash
# 1. 安装系统依赖
apt update && apt install -y python3.11 python3-pip ffmpeg
pip install playwright && playwright install chromium && playwright install-deps chromium

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 后台运行
nohup uvicorn server:app --host 0.0.0.0 --port 8800 &

# 4. 配置 Nginx 反向代理 + SSL
# ...
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | 8800 | 服务端口 |
| `HOST` | 0.0.0.0 | 监听地址 |
| `LOG_LEVEL` | INFO | 日志级别 |

## 验证部署

```bash
# 健康检查
curl https://your-domain/health

# 期望返回:
# {"status":"healthy","version":"2.0.0","playwright":true,"ffmpeg":true}

# 平台能力
curl https://your-domain/api/info
```

---

## 功能可用性速查

| 功能 | Docker | Railway | Render (Native) | VPS |
|------|--------|---------|-----------------|-----|
| 网页爬取 | ✅ | ✅ | ✅ | ✅ |
| 数据分析 | ✅ | ✅ | ✅ | ✅ |
| 媒体下载 | ✅ | ✅ | ✅ | ✅ |
| 抖音下载 | ✅ | ✅ | ⚠️ 需配 Chromium | ✅ |
| 视频合并 | ✅ | ✅ | ⚠️ 需装 ffmpeg | ✅ |
