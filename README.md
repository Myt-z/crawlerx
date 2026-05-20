<!-- omit in toc -->
<p align="center">
  <img src="https://img.shields.io/badge/version-2.0-0f172a?style=flat-square" alt="version">
  <img src="https://img.shields.io/badge/python-3.11+-3b82f6?style=flat-square&logo=python&logoColor=white" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="license">
  <img src="https://img.shields.io/badge/tests-84%2F84%20passed-brightgreen?style=flat-square" alt="tests">
</p>

<h1 align="center">CrawlerX</h1>
<p align="center"><strong>Python 全功能爬虫平台</strong> — 对话式操作，零代码采集</p>

<p align="center">
  <a href="#-特性">特性</a> •
  <a href="#-快速开始">快速开始</a> •
  <a href="#-使用方式">使用方式</a> •
  <a href="#-部署">部署</a> •
  <a href="#-架构">架构</a>
</p>

---

## ✨ 特性

- **💬 对话式爬虫** — 用自然语言描述需求，AI 自动完成爬取、下载、分析
- **🌐 智能网页爬取** — 异步并发引擎，CSS/XPath 提取，翻页/深度爬取，UA 轮换
- **🎬 视频下载** — m3u8 流媒体解析 + ffmpeg 合并，直链 mp4 下载
- **🎵 抖音无水印下载** — Playwright 浏览器自动化，突破反爬
- **📊 数据分析** — pandas 统计 + matplotlib 柱状图/饼图/词云
- **💾 多格式存储** — JSON / CSV / SQLite 三选
- **🎨 精美 Landing 页面** — 6 屏滚动式介绍 + 在线聊天界面
- **🐳 一键 Docker 部署** — 自带 Chromium + ffmpeg + 中文字体

## 🚀 快速开始

```bash
# 1. 克隆
git clone https://github.com/你的用户名/crawlerx.git
cd crawlerx

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动服务
python server.py
# 打开 http://localhost:8800
```

> 抖音下载需要 Edge 浏览器（Windows 自带）或 Chromium

## 📖 使用方式

### 方式 1：网页对话（推荐）
```
打开 http://localhost:8800
→ 跟爬虫助手聊天
→ "爬 https://quotes.toscrape.com 提取名言和作者"
→ 助手自动引导、执行、展示结果
```

### 方式 2：命令行
```bash
# 网页爬取
python main.py web "URL" --rules "title:h1:text,price:span.price:text"

# 抖音下载
python main.py douyin "视频链接或ID"

# 数据分析
python main.py analyze data.json --column author --chart bar

# 运行演示
python main.py demo
```

### 方式 3：Python API
```python
from crawlers import WebCrawler
import asyncio

async def main():
    async with WebCrawler() as c:
        data = await c.crawl_page("https://example.com", {
            "title": {"selector": "h1", "attr": "text"},
            "link":  {"selector": "a", "attr": "href"},
        })
        print(data)

asyncio.run(main())
```

## 🐳 部署

### Docker（推荐）
```bash
docker-compose up -d
# 自带 Chromium + ffmpeg，所有功能可用
```

### Railway
```bash
# 推送 GitHub → railway.app → New Project → Deploy from GitHub
# 自动检测 Dockerfile，5 分钟上线
```

详见 [DEPLOY.md](DEPLOY.md)

## 📁 架构

```
crawlerx/
├── server.py              # FastAPI 后端 (REST API)
├── static/index.html      # 前端 (6屏 Landing + 聊天)
├── main.py                # CLI 入口
├── douyin_dl.py           # 抖音下载器 (Playwright)
├── config.py              # 配置中心
├── crawlers/              # 爬虫引擎
│   ├── base.py            #   异步基类
│   ├── web.py             #   网页爬虫
│   └── video.py           #   视频爬虫
├── parsers/               # 数据解析
│   ├── html_parser.py     #   CSS/XPath
│   └── json_parser.py     #   JSON 路径
├── storage/               # 数据存储
│   ├── json_storage.py    #   JSON
│   ├── csv_storage.py     #   CSV
│   └── db_storage.py      #   SQLite
├── analysis/              # 数据分析
│   ├── stats.py           #   统计/词频
│   └── visualize.py       #   柱状图/饼图/词云
├── downloader/            # 媒体下载
│   └── media_downloader.py
├── data/                  # 输出目录
├── Dockerfile             # 生产镜像
├── docker-compose.yml     # 一键部署
└── test_platform.py       # 84 项自动化测试
```

## 🧪 测试

```bash
python test_platform.py
# 84/84 通过 · 9 大类 · 覆盖 API / 解析 / 存储 / 前端 / 错误处理
```

## 🛠 技术栈

| 类别 | 技术 |
|------|------|
| 后端 | FastAPI · httpx · uvicorn |
| 前端 | 原生 HTML/CSS/JS (零框架依赖) |
| 解析 | parsel · lxml · BeautifulSoup |
| 视频 | m3u8 · ffmpeg · Playwright |
| 分析 | pandas · matplotlib · jieba · wordcloud |
| 部署 | Docker · Railway · Render |

## 📄 License

MIT
