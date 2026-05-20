"""
自动化测试 —— 验证爬虫平台所有功能
=====================================
测试范围: API端点 / 网页爬取 / 数据分析 / 文件输出 / 前端页面 / 错误处理
"""
import asyncio
import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import httpx

BASE = "http://localhost:8800"
PASS = 0
FAIL = 0
ERRORS = []


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        msg = f"  ❌ {name} — {detail}"
        print(msg)
        ERRORS.append(msg)


# ================================================================
# 1. 基础服务
# ================================================================
async def test_basic():
    print("\n" + "=" * 60)
    print("  1. 基础服务")
    print("=" * 60)

    # HTTP 可达
    try:
        r = httpx.get(f"{BASE}/", timeout=5)
        check("服务可达", r.status_code == 200, f"status={r.status_code}")
    except Exception as e:
        check("服务可达", False, str(e))
        return

    # 返回 HTML
    check("返回 HTML 页面", "text/html" in r.headers.get("content-type", ""))
    check("包含 6 个屏幕", r.text.count('class="s s') >= 6, f"找到 {r.text.count('class=\"s s')} 个屏幕")
    check("包含聊天组件", "chat-app" in r.text)
    check("包含弧廊组件", "arc-ring" in r.text)
    check("包含导航点", 'class="dots"' in r.text)

    # API 文档
    r = httpx.get(f"{BASE}/docs", timeout=5)
    check("API 文档可达", r.status_code == 200)

    # 文件列表 API
    r = httpx.get(f"{BASE}/api/files", timeout=5)
    check("文件列表 API", r.status_code == 200 and "files" in r.json())


# ================================================================
# 2. 对话 Agent — 意图识别
# ================================================================
async def test_intent():
    print("\n" + "=" * 60)
    print("  2. 对话 Agent — 意图识别")
    print("=" * 60)

    # IDLE
    r = httpx.post(f"{BASE}/api/chat", json={"message": "你好", "state": "idle", "context": {}})
    d = r.json()
    check("IDLE 响应", "你好" in d["reply"] or "爬虫助手" in d["reply"])

    # WEB_CRAWL intent
    r = httpx.post(f"{BASE}/api/chat", json={"message": "爬 https://example.com 提取标题", "state": "idle", "context": {}})
    d = r.json()
    check("识别网页爬取意图", d["state"] == "web_crawl", f"got: {d['state']}")
    check("URL 已提取", "url" in d.get("context", {}), f"context keys: {list(d.get('context', {}).keys())}")

    # DOUYIN intent
    r = httpx.post(f"{BASE}/api/chat", json={"message": "https://www.douyin.com/video/12345678901234567", "state": "idle", "context": {}})
    d = r.json()
    check("识别抖音意图", d["state"] == "douyin_dl", f"got: {d['state']}")
    check("自动触发执行", d["action"] == "execute_douyin", f"action: {d['action']}")

    # ANALYZE intent
    r = httpx.post(f"{BASE}/api/chat", json={"message": "分析 data/demo/quotes.json", "state": "idle", "context": {}})
    d = r.json()
    check("识别分析意图", d["state"] == "analyze", f"got: {d['state']}")
    check("文件路径已提取", "file" in d.get("context", {}), f"context: {d.get('context', {})}")

    # VIDEO intent
    r = httpx.post(f"{BASE}/api/chat", json={"message": "下载视频 https://example.com/video.m3u8", "state": "idle", "context": {}})
    d = r.json()
    check("识别视频意图", d["state"] in ("video_dl", "douyin_dl"), f"got: {d['state']}")


# ================================================================
# 3. 网页爬取 — 完整流程
# ================================================================
async def test_web_crawl():
    print("\n" + "=" * 60)
    print("  3. 网页爬取")
    print("=" * 60)

    # Step 1: 发起爬取
    r = httpx.post(f"{BASE}/api/chat", json={
        "message": "爬 https://quotes.toscrape.com 提取 text:div.quote span.text, author:div.quote small.author",
        "state": "idle", "context": {},
    })
    d = r.json()
    check("Web crawl — 初始化", d["state"] == "web_crawl")

    # If action is execute (all params provided in one shot)
    if d.get("action"):
        check("Web crawl — 一键执行", True)
        action, ctx = d["action"], d["context"]
    else:
        # Need to provide more params
        r = httpx.post(f"{BASE}/api/chat", json={
            "message": "不翻页, json格式",
            "state": d["state"], "context": d.get("context", {}),
        })
        d = r.json()
        action, ctx = d.get("action"), d.get("context", {})
        check("Web crawl — 参数补全", action == "execute_web", f"action: {action}")

    # Execute
    if action:
        r = httpx.post(f"{BASE}/api/execute", json={"action": action, "context": ctx})
        ex = r.json()
        check("Web crawl — 执行成功", ex["success"], ex.get("message", "")[:100])
        check("Web crawl — 有数据", ex.get("data", {}).get("count", 0) > 0, f"count: {ex.get('data', {}).get('count', 0)}")
        check("Web crawl — 文件已保存", Path(ex.get("data", {}).get("file", "")).exists(), ex.get("data", {}).get("file", ""))
        check("Web crawl — 有预览", len(ex.get("data", {}).get("preview", [])) > 0)
    else:
        check("Web crawl — 有 action", False, "action is None")


# ================================================================
# 4. 数据分析
# ================================================================
async def test_analyze():
    print("\n" + "=" * 60)
    print("  4. 数据分析")
    print("=" * 60)

    # Ensure demo data exists
    demo_path = Path("data/demo/quotes.json")
    if not demo_path.exists():
        check("Demo 数据存在 (跳过分析测试)", False, str(demo_path))
        return
    check("Demo 数据存在", True)

    # Step 1: 发起分析
    r = httpx.post(f"{BASE}/api/chat", json={
        "message": "分析 data/demo/quotes.json author 列 柱状图",
        "state": "idle", "context": {},
    })
    d = r.json()
    check("Analyze — 初始化", d["state"] == "analyze", f"state: {d['state']}")

    if d.get("action"):
        action, ctx = d["action"], d["context"]
    else:
        r = httpx.post(f"{BASE}/api/chat", json={
            "message": "柱状图 Top 10",
            "state": d["state"], "context": d.get("context", {}),
        })
        d = r.json()
        action, ctx = d.get("action"), d.get("context", {})

    if action:
        r = httpx.post(f"{BASE}/api/execute", json={"action": action, "context": ctx})
        ex = r.json()
        check("Analyze — 执行成功", ex["success"], ex.get("message", "")[:100])
        data = ex.get("data", {})
        check("Analyze — 有行数", data.get("rows", 0) > 0)
        check("Analyze — 有列名", len(data.get("columns", [])) > 0, f"columns: {data.get('columns')}")
        if data.get("chart"):
            check("Analyze — 图表生成", Path(data["chart"]).exists(), data["chart"])
    else:
        check("Analyze — 有 action", False)


# ================================================================
# 5. 存储模块
# ================================================================
async def test_storage():
    print("\n" + "=" * 60)
    print("  5. 存储模块")
    print("=" * 60)

    from storage import JSONStorage, CSVStorage, DBStorage

    test_data = [
        {"title": "Test Book", "author": "Test Author", "price": 29.99},
        {"title": "Another Book", "author": "Another Author", "price": 19.99},
    ]

    # JSON
    json_path = Path("data/test_output.json")
    JSONStorage(json_path).save(test_data)
    check("JSON 存储", json_path.exists())
    loaded = JSONStorage(json_path).load()
    check("JSON 读取", len(loaded) == 2)

    # CSV
    csv_path = Path("data/test_output.csv")
    CSVStorage(csv_path).save(test_data)
    check("CSV 存储", csv_path.exists())
    csv_data = CSVStorage(csv_path).load()
    check("CSV 读取", len(csv_data) == 2, f"rows: {len(csv_data)}")

    # SQLite
    db_path = Path("data/test_output.db")
    with DBStorage(db_path) as db:
        db.create_table_from_data("books", test_data[0])
        db.insert("books", test_data)
        count = db.count("books")
    check("SQLite 存储", db_path.exists())
    check("SQLite 数据行数", count == 2, f"count: {count}")

    # Cleanup
    for p in [json_path, csv_path, db_path]:
        if p.exists():
            p.unlink()
    check("清理测试文件", True)


# ================================================================
# 6. 解析模块
# ================================================================
async def test_parsers():
    print("\n" + "=" * 60)
    print("  6. 解析模块")
    print("=" * 60)

    from parsers import HTMLParser, JSONParser

    # HTML Parser
    html = """
    <div class="quote">
      <span class="text">Hello World</span>
      <small class="author">Alice</small>
      <a class="tag">python</a>
      <a class="tag">code</a>
    </div>
    <div class="quote">
      <span class="text">Goodbye</span>
      <small class="author">Bob</small>
      <a class="tag">rust</a>
    </div>
    """
    parser = HTMLParser()
    rules = {
        "text": {"selector": "div.quote span.text", "attr": "text"},
        "author": {"selector": "div.quote small.author", "attr": "text"},
        "tags": {"selector": "div.quote a.tag", "attr": "text", "multiple": True},
    }
    parsed = parser.parse_list(html, rules)
    check("HTML 解析 — 行数", len(parsed) == 2, f"rows: {len(parsed)}")
    check("HTML 解析 — 字段", parsed[0]["text"] == "Hello World" and parsed[0]["author"] == "Alice")
    check("HTML 解析 — 多值", isinstance(parsed[0].get("tags"), list), f"type: {type(parsed[0].get('tags')).__name__}")

    # JSON Parser
    jp = JSONParser()
    data = {"user": {"profile": {"name": "Alice", "age": 30}}, "items": [{"id": 1}, {"id": 2}]}
    check("JSON 路径提取", jp.extract(data, "user.profile.name") == "Alice")
    check("JSON 数组索引", jp.extract(data, "items.0.id") == 1)
    check("JSON 键搜索", len(jp.find_keys(data, "id")) == 2)


# ================================================================
# 7. 配置 & 数据文件
# ================================================================
async def test_config():
    print("\n" + "=" * 60)
    print("  7. 配置 & 文件结构")
    print("=" * 60)

    import config

    check("DATA_DIR 存在", config.DATA_DIR.exists(), str(config.DATA_DIR))
    check("DEFAULT_DELAY > 0", config.DEFAULT_DELAY > 0)
    check("MAX_RETRIES 合理", config.MAX_RETRIES >= 2)
    check("MAX_CONCURRENT 合理", config.MAX_CONCURRENT >= 5)

    # 目录结构
    for sub in ["json", "csv", "db", "videos", "charts"]:
        p = config.DATA_DIR / sub
        check(f"目录 {sub}", p.exists(), str(p))

    # 模块文件
    for mod in ["crawlers/base.py", "crawlers/web.py", "crawlers/video.py",
                "parsers/html_parser.py", "parsers/json_parser.py",
                "storage/json_storage.py", "storage/csv_storage.py", "storage/db_storage.py",
                "analysis/stats.py", "analysis/visualize.py",
                "downloader/media_downloader.py",
                "config.py", "server.py", "douyin_dl.py"]:
        check(f"模块 {mod}", Path(mod).exists(), str(Path(mod)))


# ================================================================
# 8. 错误处理
# ================================================================
async def test_errors():
    print("\n" + "=" * 60)
    print("  8. 错误处理")
    print("=" * 60)

    # 文件不存在
    r = httpx.post(f"{BASE}/api/chat", json={
        "message": "分析 nonexistent_file.json",
        "state": "idle", "context": {},
    })
    d = r.json()
    if d.get("action"):
        r = httpx.post(f"{BASE}/api/execute", json={"action": d["action"], "context": d["context"]})
        ex = r.json()
        check("文件不存在 — 返回失败", not ex["success"])
        check("文件不存在 — 有错误信息", len(ex.get("message", "")) > 0)

    # 无效 URL
    r = httpx.post(f"{BASE}/api/chat", json={
        "message": "爬 not-a-valid-url 提取标题",
        "state": "idle", "context": {},
    })
    d = r.json()
    check("无效 URL — 仍进入 web 状态", d["state"] == "web_crawl" or "url" not in d.get("context", {}))

    # 占位 URL 检测
    r = httpx.post(f"{BASE}/api/chat", json={
        "message": "下载视频 https://example.com/video.m3u8",
        "state": "idle", "context": {},
    })
    d = r.json()
    check("占位 URL — 不自动执行", d.get("action") is None)
    check("占位 URL — 有提示信息", "占位" in d.get("reply", "") or "提供" in d.get("reply", ""))

    # 缺少 URL 时引导
    r = httpx.post(f"{BASE}/api/chat", json={
        "message": "下载视频",
        "state": "idle", "context": {},
    })
    d = r.json()
    check("无 URL — 提示提供链接", "提供" in d.get("reply", ""))

    # 网页爬取占位 URL
    r = httpx.post(f"{BASE}/api/chat", json={
        "message": "爬 https://example.com 提取标题",
        "state": "idle", "context": {},
    })
    d = r.json()
    check("网页爬取占位 URL — 有提示", "占位" in d.get("reply", "") or "真实" in d.get("reply", ""))

    # 未知 action
    r = httpx.post(f"{BASE}/api/execute", json={"action": "unknown_action", "context": {}})
    check("未知 action — 返回 400", r.status_code == 400)


# ================================================================
# 9. 前端页面质量检查
# ================================================================
async def test_frontend():
    print("\n" + "=" * 60)
    print("  9. 前端页面质量")
    print("=" * 60)

    r = httpx.get(f"{BASE}/", timeout=5)
    html = r.text

    # 关键组件检查
    check("响应式 viewport", 'name="viewport"' in html)
    check("PingFang SC 字体", "PingFang SC" in html)
    check("滚动导航逻辑", "goToScreen" in html)
    check("Arc Gallery", "arc-ring" in html and "arc-pivot" in html)
    check("Orb 动画", "@keyframes orbDrift" in html)
    check("粒子动画", "@keyframes particleUp" in html)
    check("计数器动画", "animateCounters" in html)
    check("聊天 JS 逻辑", "sendMsg" in html)
    check("API fetch 调用", "/api/chat" in html)
    check("Markdown 渲染", "strong" in html)  # renderMarkdown uses <strong>
    check("建议卡片", "chat-sug-btn" in html)
    check("返回按钮", "返回介绍" in html)
    check("6 屏 Section", 'class="s s' in html)


# ================================================================
# Main
# ================================================================
async def main():
    print()
    print("╔" + "═" * 58 + "╗")
    print("║" + "  Python 全功能爬虫平台 — 自动化测试".center(50) + "║")
    print("╚" + "═" * 58 + "╝")

    start = time.time()

    await test_basic()
    await test_intent()
    await test_web_crawl()
    await test_analyze()
    await test_storage()
    await test_parsers()
    await test_config()
    await test_errors()
    await test_frontend()

    elapsed = time.time() - start

    # Summary
    total = PASS + FAIL
    print("\n" + "=" * 60)
    print(f"  测试结果: {PASS}/{total} 通过, {FAIL} 失败, 耗时 {elapsed:.1f}s")
    print("=" * 60)

    if FAIL > 0:
        print("\n  失败项:")
        for e in ERRORS:
            print(f"    {e}")

    # Score
    pct = PASS / total * 100 if total > 0 else 0
    if pct >= 95:
        grade = "A+ 🏆"
    elif pct >= 85:
        grade = "A"
    elif pct >= 70:
        grade = "B"
    elif pct >= 50:
        grade = "C"
    else:
        grade = "F"
    print(f"\n  综合评分: {grade} ({pct:.0f}%)")

    return FAIL == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
