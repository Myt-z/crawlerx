"""
爬虫平台 FastAPI 后端 — 为自定义前端提供 REST API
==================================================
启动: python server.py
访问: http://localhost:8800
"""
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from crawlers import WebCrawler, VideoCrawler
from analysis import DataAnalyzer, Visualizer
from storage import JSONStorage, CSVStorage, DBStorage
from downloader import MediaDownloader
from config import DATA_DIR

# ---- FastAPI App ----
app = FastAPI(
    title="CrawlerX API",
    version="2.0.0",
    description="Python 全功能爬虫平台 — 网页爬取 / 视频下载 / 数据分析",
)

# CORS (允许任何来源访问，生产环境可收紧)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

# ---- 环境检测 ----
PLAYWRIGHT_AVAILABLE = False
FFMPEG_AVAILABLE = False
try:
    from douyin_dl import DouyinDownloader
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    pass

try:
    import subprocess
    subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    FFMPEG_AVAILABLE = True
except Exception:
    pass


# ---- 请求/响应模型 ----
class ChatRequest(BaseModel):
    message: str
    state: str = "idle"        # 前端维护的对话状态
    context: dict = {}          # 上下文 (已收集的参数)


class ChatResponse(BaseModel):
    reply: str
    state: str = "idle"
    context: dict = {}
    action: Optional[str] = None  # "execute_web" | "execute_video" | "execute_douyin" | "execute_analyze"


class ExecuteRequest(BaseModel):
    action: str
    context: dict


# ---- Agent 核心逻辑 (从 app.py 移植) ----

def detect_intent(message: str) -> str:
    msg = message.lower()
    if re.search(r"douyin\.com|抖音|modal_id", msg):
        return "douyin_dl"
    if any(w in msg for w in ["爬", "抓取", "采集", "爬虫", "crawl"]):
        return "web_crawl"
    if any(w in msg for w in ["视频", "video", "m3u8", "下载视频"]):
        return "douyin_dl" if ("douyin" in msg or "抖音" in msg) else "video_dl"
    if any(w in msg for w in ["分析", "统计", "图表", "可视化", "analyze", "词频", "词云"]):
        return "analyze"
    if any(w in msg for w in ["下载图片", "下载文件", "批量下载"]):
        return "media_dl"
    return "idle"


def extract_url(message: str) -> Optional[str]:
    urls = re.findall(r"https?://[^\s,，。]+", message)
    return urls[0] if urls else None


def parse_web_params(message: str, context: dict) -> dict:
    """提取网页爬取参数，合并到 context"""
    url = extract_url(message)
    if url:
        context["url"] = url
    context["intent"] = "web_crawl"

    # 解析 rules
    rules = context.get("rules", {})
    rule_matches = re.findall(
        r"(\w+)\s*[:：]\s*([a-zA-Z0-9.#\-_ >]+?)(?=[,，]|$)",
        message,
    )
    for field, sel in rule_matches:
        sel = sel.strip().rstrip(",，")
        if sel.endswith(":text"):
            sel = sel[:-5]
        rules[field] = {"selector": sel, "attr": "text"}

    if rules:
        context["rules"] = rules

    # 翻页
    if re.search(r"是|[Yy]es|翻页|paginate|下一页", message) and not re.search(r"不翻|否", message):
        context["paginate"] = True
    elif re.search(r"否|[Nn]o|不翻|单页|一页", message):
        context["paginate"] = False

    # 下一页选择器
    next_m = re.search(r"next.*?[:：\s]+([a-zA-Z0-9.#\-_>]+)", message, re.IGNORECASE)
    if next_m:
        context["next_selector"] = next_m.group(1).strip()

    # 格式
    for fmt in ["json", "csv", "db"]:
        if fmt in message.lower():
            context["format"] = fmt

    # 最大页数
    n = re.search(r"(\d+)\s*[页]", message)
    if n:
        context["max_pages"] = int(n.group(1))

    return context


def parse_analyze_params(message: str, context: dict) -> dict:
    context["intent"] = "analyze"

    file_m = re.search(r"([\w/\\\-]+\.(?:json|csv|db))", message)
    if file_m:
        context["file"] = file_m.group(1)

    col_m = re.search(r"(?:列|column|字段)[：:\s]*(\w+)", message)
    if col_m:
        context["column"] = col_m.group(1)

    for ct in ["bar", "pie", "wordcloud", "柱状图", "饼图", "词云"]:
        if ct in message:
            context["chart"] = {"柱状图": "bar", "饼图": "pie", "词云": "wordcloud"}.get(ct, ct)

    n = re.search(r"[Tt]op\s*(\d+)", message)
    if n:
        context["top_n"] = int(n.group(1))

    return context


def check_web_params(context: dict) -> list[str]:
    q = []
    if not context.get("url"):
        q.append("请提供目标网站的网址 (URL)")
    if not context.get("rules"):
        q.append("请告诉我要提取哪些字段及CSS选择器。格式: 字段:选择器，如 title:h1.title")
    elif "paginate" not in context:
        q.append("需要自动翻页吗？")
    elif context.get("paginate") and "next_selector" not in context:
        q.append("「下一页」按钮的 CSS 选择器是什么？")
    elif "format" not in context:
        q.append("数据保存为什么格式？json / csv / db")
    elif context.get("paginate") and "max_pages" not in context:
        q.append("最多爬多少页？")
    return q


def check_analyze_params(context: dict) -> list[str]:
    q = []
    if not context.get("file"):
        q.append("请提供数据文件路径 (如 data/demo/quotes.json)")
    return q


# ---- API Routes ----

@app.get("/health")
async def health():
    """生产环境健康检查"""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "playwright": PLAYWRIGHT_AVAILABLE,
        "ffmpeg": FFMPEG_AVAILABLE,
    }


@app.get("/api/info")
async def platform_info():
    """返回平台能力信息"""
    return {
        "version": "2.0.0",
        "features": {
            "web_crawl": True,
            "video_download": FFMPEG_AVAILABLE,
            "douyin_download": PLAYWRIGHT_AVAILABLE,
            "data_analysis": True,
            "media_download": True,
        },
        "capabilities": {
            "playwright": PLAYWRIGHT_AVAILABLE,
            "ffmpeg": FFMPEG_AVAILABLE,
        },
    }


@app.get("/")
async def root():
    """返回聊天页面"""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>Static files not found</h1>")


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """
    核心对话接口。
    接收用户消息和当前上下文，返回助手回复 + 更新后的上下文。
    如果参数齐全，标记需要执行的操作。
    """
    msg = req.message.strip()
    ctx = req.context.copy()
    state = req.state

    # 意图检测
    intent = detect_intent(msg)
    if intent == "idle" and state != "idle":
        intent = state

    # ---- IDLE ----
    if intent == "idle":
        return ChatResponse(
            reply="你好！我是爬虫助手。你可以:\n• 「爬」网页\n• 「下载」视频/抖音\n• 「分析」数据",
            state="idle", context={},
        )

    # ---- WEB CRAWL ----
    if intent == "web_crawl":
        ctx = parse_web_params(msg, ctx)
        # 检测占位 URL
        if ctx.get("url") and any(p in ctx["url"].lower() for p in ["example.com", "xxx", "..."]):
            return ChatResponse(
                reply="**[网页爬取]** 你提供的链接 `{}` 看起来是占位地址，请提供真实的目标网址。".format(ctx["url"]),
                state="web_crawl", context=ctx,
            )
        questions = check_web_params(ctx)

        if questions:
            return ChatResponse(
                reply="**[网页爬取]** 还需要:\n" + "\n".join(f"**{i+1}.** {q}" for i, q in enumerate(questions)),
                state="web_crawl", context=ctx,
            )
        return ChatResponse(
            reply="参数齐全，正在执行...", state="web_crawl",
            context=ctx, action="execute_web",
        )

    # ---- DOUYIN ----
    if intent == "douyin_dl":
        if not PLAYWRIGHT_AVAILABLE:
            return ChatResponse(
                reply="抖音下载需要 Playwright 浏览器支持，当前环境未安装。请使用 Docker 部署或本地启动。",
                state="idle", context={},
            )
        url = extract_url(msg) or msg
        ctx = {"intent": "douyin_dl", "url": url}
        return ChatResponse(
            reply="正在解析抖音视频...", state="douyin_dl",
            context=ctx, action="execute_douyin",
        )

    # ---- ANALYZE ----
    if intent == "analyze":
        ctx = parse_analyze_params(msg, ctx)
        questions = check_analyze_params(ctx)

        if questions:
            return ChatResponse(
                reply="**[数据分析]** 还需要:\n" + "\n".join(f"**{i+1}.** {q}" for i, q in enumerate(questions)),
                state="analyze", context=ctx,
            )
        return ChatResponse(
            reply="正在分析数据...", state="analyze",
            context=ctx, action="execute_analyze",
        )

    # ---- VIDEO / MEDIA DL ----
    if intent in ("video_dl", "media_dl"):
        url = extract_url(msg)
        if not url:
            return ChatResponse(
                reply="**[视频/媒体下载]** 请提供要下载的链接。\n\n支持的格式：m3u8 流媒体、mp4/webm 直链、或包含视频的网页地址。",
                state=intent, context={},
            )
        # 检测占位 URL（example.com 等）
        if any(placeholder in url.lower() for placeholder in ["example.com", "xxx", "..."]):
            return ChatResponse(
                reply="**[视频/媒体下载]** 你提供的链接看起来是占位地址，请提供真实的视频链接。\n\n例如：`下载视频 https://真实的地址.m3u8`",
                state=intent, context={},
            )
        ctx = {"intent": intent, "url": url}
        return ChatResponse(
            reply=f"正在下载: {url[:80]}...", state=intent,
            context=ctx, action=f"execute_{intent}",
        )

    return ChatResponse(reply="请重新描述你的需求", state="idle", context={})


@app.post("/api/execute")
async def execute(req: ExecuteRequest):
    """执行爬虫/分析任务"""
    ctx = req.context

    if req.action == "execute_web":
        return await _do_web_crawl(ctx)
    elif req.action == "execute_douyin":
        return await _do_douyin(ctx)
    elif req.action == "execute_analyze":
        return await _do_analyze(ctx)
    elif req.action in ("execute_video_dl", "execute_media_dl"):
        return await _do_media_download(ctx)
    else:
        raise HTTPException(400, f"Unknown action: {req.action}")


@app.get("/api/files")
async def list_files():
    """列出最近的输出文件"""
    files = []
    for sub in ["demo", "json", "csv", "charts", "videos"]:
        p = DATA_DIR / sub
        if p.exists():
            for f in sorted(p.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
                if f.is_file():
                    files.append({
                        "name": f.name,
                        "path": str(f.relative_to(Path.cwd())),
                        "size": f.stat().st_size,
                    })
    return {"files": files}


# ---- 执行函数 ----

async def _do_web_crawl(ctx: dict):
    try:
        crawler = WebCrawler(delay=1.0, max_concurrent=10)
        rules = ctx["rules"]
        if ctx.get("paginate"):
            data = await crawler.crawl_paginated(
                start_url=ctx["url"], rules=rules,
                next_selector=ctx.get("next_selector", "a.next"),
                max_pages=ctx.get("max_pages", 0),
            )
        else:
            data = await crawler.crawl_page(ctx["url"], rules)
        await crawler.close()

        # 保存
        fmt = ctx.get("format", "json")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if fmt == "csv":
            p = f"data/crawl_{ts}.csv"
            CSVStorage(p).save(data)
        elif fmt == "db":
            p = f"data/crawl_{ts}.db"
            with DBStorage(p) as db:
                db.create_table_from_data("data", data[0])
                db.insert("data", data)
        else:
            p = f"data/crawl_{ts}.json"
            JSONStorage(p).save(data)

        preview = data[:3] if len(data) > 3 else data
        return {
            "success": True,
            "message": f"爬取完成！共 {len(data)} 条数据，已保存至 {p}",
            "data": {"count": len(data), "file": p, "preview": preview},
        }
    except Exception as e:
        return {"success": False, "message": f"爬取失败: {e}"}


async def _do_douyin(ctx: dict):
    try:
        from douyin_dl import DouyinDownloader
        dl = DouyinDownloader(headless=True)
        path = await dl.download(ctx["url"])
        if path:
            size_mb = path.stat().st_size / 1024 / 1024
            return {
                "success": True,
                "message": f"抖音视频下载完成！{size_mb:.1f} MB",
                "data": {"file": str(path), "size_mb": round(size_mb, 1)},
            }
        return {"success": False, "message": "下载失败，请检查视频是否需要登录"}
    except Exception as e:
        return {"success": False, "message": f"下载失败: {e}"}


async def _do_media_download(ctx: dict):
    """通用媒体下载"""
    try:
        url = ctx["url"]
        from downloader import MediaDownloader
        dl = MediaDownloader()
        if url.endswith((".m3u8", ".mp4", ".webm", ".flv", ".mov")):
            from crawlers import VideoCrawler
            crawler = VideoCrawler()
            path = await crawler.download_m3u8(url)
            await crawler.close()
            if path:
                size_mb = path.stat().st_size / 1024 / 1024
                return {"success": True, "message": f"视频下载完成！{size_mb:.1f} MB", "data": {"file": str(path), "size_mb": round(size_mb, 1)}}
            return {"success": False, "message": "视频下载失败，请检查 URL 或 ffmpeg"}
        else:
            saved = await dl.download_images([url])
            await dl.close()
            if saved:
                return {"success": True, "message": f"下载完成！{len(saved)} 个文件", "data": {"file": str(saved[0])}}
            return {"success": False, "message": "下载失败，请检查 URL"}
    except Exception as e:
        return {"success": False, "message": f"下载失败: {e}"}


async def _do_analyze(ctx: dict):
    try:
        file_path = ctx.get("file", "")
        p = Path(file_path)
        if not p.exists():
            p = DATA_DIR / file_path
        if not p.exists():
            return {"success": False, "message": f"文件不存在: {file_path}"}

        if p.suffix == ".json":
            analyzer = DataAnalyzer.from_json(p)
        elif p.suffix == ".csv":
            analyzer = DataAnalyzer.from_csv(p)
        else:
            analyzer = DataAnalyzer.from_db(p)

        result = {
            "rows": len(analyzer.df),
            "columns": list(analyzer.df.columns),
        }

        if ctx.get("column"):
            col = ctx["column"]
            if col in analyzer.df.columns:
                top = ctx.get("top_n", 10)
                vc = analyzer.value_counts(col, top_n=top)
                result["value_counts"] = vc.to_dict(orient="records")

                if ctx.get("chart"):
                    charts_dir = Path("data/charts")
                    charts_dir.mkdir(parents=True, exist_ok=True)
                    chart_type = ctx["chart"]
                    chart_path = charts_dir / f"api_{col}_{chart_type}.png"
                    Visualizer.from_value_counts(
                        analyzer.df, col, chart_type=chart_type,
                        top_n=top, title=f"{col} 分布", save_path=chart_path,
                    )
                    result["chart"] = str(chart_path)

        return {"success": True, "message": f"分析完成！{result['rows']}行, {len(result['columns'])}列", "data": result}
    except Exception as e:
        return {"success": False, "message": f"分析失败: {e}"}


# ---- 启动 ----

def main():
    print("=" * 55)
    print("  CrawlerX - Python 全功能爬虫平台")
    print("=" * 55)
    print(f"  地址:     http://localhost:8800")
    print(f"  API 文档: http://localhost:8800/docs")
    print(f"  健康检查: http://localhost:8800/health")
    print(f"  平台信息: http://localhost:8800/api/info")
    print()
    print("  功能状态:")
    print(f"    网页爬取:     [OK]")
    print(f"    视频下载:     [{'OK' if FFMPEG_AVAILABLE else 'OFF - 需要 ffmpeg'}]")
    print(f"    抖音下载:     [{'OK' if PLAYWRIGHT_AVAILABLE else 'OFF - 需要 Playwright'}]")
    print(f"    数据分析:     [OK]")
    print(f"    媒体下载:     [OK]")
    print()

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8800"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
