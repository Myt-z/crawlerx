"""
Python 全功能爬虫平台 CLI
===========================
支持: 网页爬取 | 视频下载 | 数据分析 | 媒体下载

用法:
  python main.py web      <url> [--rules RULES]  网页爬取
  python main.py video    <url> [--output NAME]   视频下载
  python main.py douyin   <url> [--output NAME]   抖音视频下载
  python main.py analyze  <file> [--chart TYPE]   数据分析
  python main.py download <url> [--type TYPE]     媒体下载
  python main.py demo                             跑一个演示
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from loguru import logger

import config
from crawlers import WebCrawler, VideoCrawler
from parsers import HTMLParser, JSONParser
from storage import JSONStorage, CSVStorage, DBStorage
from analysis import DataAnalyzer, Visualizer
from downloader import MediaDownloader


async def cmd_douyin(args):
    """抖音视频下载"""
    from douyin_dl import DouyinDownloader
    dl = DouyinDownloader(headless=not args.show_browser)
    result = await dl.download(args.url_or_id, args.output)
    if result:
        print(f"\n视频已保存: {result.absolute()}")
    else:
        print("\n下载失败。可能原因:")
        print("  1. 视频需要登录才能观看（请在浏览器中打开看看是否需要登录）")
        print("  2. 视频已被删除或设为私密")
        print("  3. 抖音反爬机制升级，需要更新脚本")
        sys.exit(1)

# ---- 日志配置 ----
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | <level>{message}</level>",
    level=config.LOG_LEVEL,
)
logger.add(
    config.LOG_FILE,
    rotation=config.LOG_ROTATION,
    retention="7 days",
    encoding="utf-8",
    level="DEBUG",
)


# ================================================================
# 辅助函数
# ================================================================

def parse_rule_arg(rules_str: str) -> dict:
    """
    将命令行参数转为 rules 字典。
    格式: "title:h1.title:text,price:span.price:text,link:a:attr:href"
    """
    rules = {}
    for part in rules_str.split(","):
        pieces = part.split(":")
        field = pieces[0]
        selector = pieces[1] if len(pieces) > 1 else ""
        if len(pieces) >= 3 and pieces[2] == "attr":
            attr = pieces[3] if len(pieces) > 3 else "text"
            multiple = len(pieces) > 4 and pieces[4] == "multi"
        else:
            attr = pieces[2] if len(pieces) > 2 else "text"
            multiple = len(pieces) > 3 and pieces[3] == "multi"
        rules[field] = {"selector": selector, "attr": attr, "multiple": multiple}
    return rules


# ================================================================
# 子命令处理
# ================================================================

async def cmd_web(args):
    """网页爬取"""
    crawler = WebCrawler(max_concurrent=args.concurrency, delay=args.delay)

    rules = parse_rule_arg(args.rules)
    logger.info(f"规则: {json.dumps(rules, ensure_ascii=False)}")

    if args.deep:
        # 深度爬取：列表 → 详情
        detail_rules = parse_rule_arg(args.detail_rules) if args.detail_rules else rules
        data = await crawler.crawl_deep(
            start_url=args.url,
            list_rules=rules,
            detail_rules=detail_rules,
            link_selector=args.link_selector,
            max_items=args.max_items,
        )
    elif args.paginate:
        # 翻页爬取
        data = await crawler.crawl_paginated(
            start_url=args.url,
            rules=rules,
            next_selector=args.next_selector,
            max_pages=args.max_pages,
        )
    else:
        # 单页爬取
        data = await crawler.crawl_page(args.url, rules)

    logger.info(f"共爬取 {len(data)} 条数据")
    await crawler.close()

    if not data:
        return

    # 保存
    _save_data(data, args)
    _print_preview(data)


async def cmd_video(args):
    """视频下载"""
    crawler = VideoCrawler(max_concurrent=args.concurrency)

    if args.extract:
        # 从网页提取视频 URL
        urls = await crawler.extract_video_urls(args.url)
        logger.info(f"发现 {len(urls)} 个视频链接:")
        for u in urls:
            print(f"  {u}")
        if not urls:
            await crawler.close()
            return
        # 下载第一个
        target = urls[0]
    else:
        target = args.url

    logger.info(f"开始下载: {target}")
    path = await crawler.download_m3u8(target, filename=args.output)
    if path:
        logger.info(f"视频已保存: {path}")
    else:
        logger.error("下载失败")

    await crawler.close()


async def cmd_download(args):
    """媒体批量下载"""
    dl = MediaDownloader(download_dir=args.output_dir)

    if args.page:
        # 从网页提取媒体
        saved = await dl.download_from_page(args.url, selector=args.selector)
    else:
        # 直接 URL 列表下载
        urls = [u.strip() for u in args.url.split(",")]
        if args.type == "image":
            saved = await dl.download_images(urls)
        else:
            saved = await dl.download_files(urls)

    logger.info(f"下载完成: {len(saved)} 个文件 → {dl.download_dir}")
    await dl.close()


async def cmd_analyze(args):
    """数据分析"""
    path = Path(args.file)

    # 加载数据
    if path.suffix == ".json":
        analyzer = DataAnalyzer.from_json(path)
    elif path.suffix == ".csv":
        analyzer = DataAnalyzer.from_csv(path)
    elif path.suffix == ".db":
        analyzer = DataAnalyzer.from_db(path, table=args.table or "data")
    else:
        logger.error(f"不支持的文件格式: {path.suffix}")
        return

    # 数据清洗
    if args.clean:
        analyzer = analyzer.clean()

    # 打印概览
    summary = analyzer.summary()
    print("\n" + "=" * 50)
    print(f"  数据概览: {path.name}")
    print("=" * 50)
    print(f"  行数: {summary['rows']}")
    print(f"  列数: {summary['columns']}")
    print(f"  内存: {summary['memory_usage']}")
    print(f"  列名: {list(analyzer.df.columns)}")
    if args.verbose:
        print(f"\n  缺失值:\n{json.dumps(summary['missing'], indent=4, ensure_ascii=False)}")
        print(f"\n  描述性统计:\n{analyzer.describe()}")

    # 值分布
    if args.column:
        print(f"\n--- {args.column} 频率分布 (Top {args.top_n}) ---")
        print(analyzer.value_counts(args.column, top_n=args.top_n).to_string(index=False))

    # 词频
    if args.word_freq:
        freq = analyzer.word_frequency(args.word_freq, top_n=args.top_n)
        print(f"\n--- 词频 Top {args.top_n} ---")
        for word, count in freq:
            print(f"  {word}: {count}")

    # 生成图表
    if args.chart:
        chart_type = args.chart
        if chart_type == "wordcloud" and args.word_freq:
            # 需要词频
            col = args.word_freq or list(analyzer.df.columns)[0]
            freq = analyzer.word_frequency(col, top_n=100)
            out_path = args.output or f"data/charts/{path.stem}_wordcloud.png"
            Visualizer.wordcloud(freq, title=f"{col} 词云", save_path=out_path)
            print(f"\n  词云已保存: {out_path}")
        elif args.column:
            out_path = args.output or f"data/charts/{path.stem}_{args.column}_{chart_type}.png"
            Visualizer.from_value_counts(
                analyzer.df, args.column,
                chart_type=chart_type, top_n=args.top_n,
                title=f"{args.column} {chart_type}", save_path=out_path,
            )
            print(f"  图表已保存: {out_path}")

    # 导出
    if args.export:
        export_path = Path(args.export)
        if export_path.suffix == ".csv":
            analyzer.to_csv(export_path)
        elif export_path.suffix in (".xls", ".xlsx"):
            analyzer.to_excel(export_path)
        elif export_path.suffix == ".json":
            analyzer.to_json(export_path)
        print(f"  数据已导出: {export_path}")

    # 清洗后回存
    if args.save_clean:
        clean_path = Path(args.save_clean)
        if clean_path.suffix == ".csv":
            analyzer.to_csv(clean_path)
        elif clean_path.suffix == ".json":
            analyzer.to_json(clean_path)
        print(f"  清洗结果已保存: {clean_path}")


async def cmd_demo(args):
    """跑一个完整的演示流程：爬取 → 分析 → 可视化"""
    print("\n" + "=" * 55)
    print("  爬虫平台 Demo —— 爬取 + 分析 + 可视化")
    print("=" * 55)

    # ---- Step 1: 爬取 ----
    print("\n[Step 1] 爬取 quotes.toscrape.com ...")
    crawler = WebCrawler(delay=1.0, max_concurrent=5)
    rules = {
        "text":   {"selector": "div.quote span.text", "attr": "text"},
        "author": {"selector": "div.quote small.author", "attr": "text"},
        "tags":   {"selector": "div.quote a.tag", "attr": "text", "multiple": True},
    }
    data = await crawler.crawl_paginated(
        start_url="http://quotes.toscrape.com",
        rules=rules,
        next_selector="li.next a",
        max_pages=3,  # 只爬 3 页做演示
    )
    await crawler.close()
    print(f"  共爬取 {len(data)} 条名言")

    if not data:
        print("  未爬取到数据，Demo 终止。请检查网络连接。")
        return

    # ---- Step 2: 存储 ----
    print("\n[Step 2] 保存数据 ...")
    demo_dir = Path("data/demo")
    demo_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = demo_dir / "quotes.json"
    JSONStorage(json_path).save(data)
    print(f"  JSON → {json_path}")

    # CSV
    csv_path = demo_dir / "quotes.csv"
    CSVStorage(csv_path).save(data)
    print(f"  CSV → {csv_path}")

    # SQLite
    db_path = demo_dir / "quotes.db"
    with DBStorage(db_path) as db:
        db.create_table_from_data("quotes", data[0])
        db.insert("quotes", data)
        count = db.count("quotes")
    print(f"  SQLite → {db_path} ({count} 条)")

    # ---- Step 3: 分析 ----
    print("\n[Step 3] 数据分析 ...")
    analyzer = DataAnalyzer(data)

    # 作者分布
    author_stats = analyzer.value_counts("author", top_n=10)
    print(f"\n  作者名言数 Top 10:\n{author_stats.to_string(index=False)}")

    # 词频统计
    text_freq = analyzer.word_frequency("text", top_n=20, lang="en")
    print(f"\n  高频词 Top 10: {', '.join(f'{w}({c})' for w, c in text_freq[:10])}")

    # ---- Step 4: 可视化 ----
    print("\n[Step 4] 生成图表 ...")
    charts_dir = Path("data/charts")
    charts_dir.mkdir(parents=True, exist_ok=True)

    Visualizer.from_value_counts(
        analyzer.df, "author", chart_type="bar", top_n=10,
        title="Top 10 Authors by Quote Count",
        save_path=charts_dir / "author_bar.png",
    )
    print(f"  柱状图 → {charts_dir / 'author_bar.png'}")

    Visualizer.from_value_counts(
        analyzer.df, "author", chart_type="pie", top_n=8,
        title="Author Distribution (Pie)",
        save_path=charts_dir / "author_pie.png",
    )
    print(f"  饼图 → {charts_dir / 'author_pie.png'}")

    # 词云
    Visualizer.wordcloud(
        text_freq, title="Quotes Word Cloud",
        save_path=charts_dir / "wordcloud.png",
    )
    print(f"  词云 → {charts_dir / 'wordcloud.png'}")

    print("\n" + "=" * 55)
    print(f"  Demo 完成！查看结果:")
    print(f"    数据: {demo_dir.absolute()}")
    print(f"    图表: {charts_dir.absolute()}")
    print("=" * 55)


# ================================================================
# 数据保存 & 预览
# ================================================================

def _save_data(data: list[dict], args):
    """根据命令行参数决定存储方式"""
    out = args.output or "data/crawl_output"
    out_path = Path(out)

    if args.format == "json":
        p = out_path.with_suffix(".json")
        JSONStorage(p).save(data)
        logger.info(f"已保存 JSON: {p}")
    elif args.format == "csv":
        p = out_path.with_suffix(".csv")
        CSVStorage(p).save(data)
        logger.info(f"已保存 CSV: {p}")
    elif args.format == "db":
        p = out_path.parent / f"{out_path.stem}.db"
        with DBStorage(p) as db:
            table = args.table or "crawl_data"
            db.create_table_from_data(table, data[0])
            db.insert(table, data)
        logger.info(f"已保存 SQLite: {p}")
    else:
        p = out_path.with_suffix(".json")
        JSONStorage(p).save(data)
        logger.info(f"已保存: {p}")


def _print_preview(data: list[dict], n: int = 5):
    """打印数据预览"""
    if not data:
        return
    print(f"\n--- 预览 (前 {min(n, len(data))} 条) ---")
    for i, item in enumerate(data[:n]):
        print(f"\n  [{i+1}]")
        for k, v in item.items():
            v_str = str(v)
            if len(v_str) > 60:
                v_str = v_str[:57] + "..."
            print(f"      {k}: {v_str}")


# ================================================================
# CLI 主入口
# ================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Python 全功能爬虫平台 —— 网页爬取 | 视频下载 | 数据分析 | 媒体下载",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 网页爬取
  python main.py web http://quotes.toscrape.com \\
      --rules "text:span.text:text,author:small.author:text,tags:a.tag:text:multi" \\
      --paginate --next-selector "li.next a" --format csv

  # 视频下载
  python main.py video "https://example.com/video.m3u8" --output my_video

  # 从网页提取视频
  python main.py video "https://example.com/page" --extract

  # 数据分析
  python main.py analyze data/quotes.json --column author --chart bar

  # 词云
  python main.py analyze data/quotes.json --word-freq text --chart wordcloud

  # 媒体下载
  python main.py download "https://example.com/img1.jpg,https://example.com/img2.jpg"

  # 运行演示
  python main.py demo
        """,
    )

    sub = parser.add_subparsers(dest="command", help="子命令")

    # ---- web 子命令 ----
    p_web = sub.add_parser("web", help="网页爬取")
    p_web.add_argument("url", help="目标 URL")
    p_web.add_argument("--rules", "-r", required=True,
                       help='提取规则，格式: field:selector:attr, 如 "title:h1:text,link:a:attr:href"')
    p_web.add_argument("--paginate", "-p", action="store_true", help="启用翻页")
    p_web.add_argument("--next-selector", default="a.next", help="下一页按钮的 CSS 选择器")
    p_web.add_argument("--deep", "-d", action="store_true", help="深度爬取（列表页 → 详情页）")
    p_web.add_argument("--link-selector", help="详情页链接选择器")
    p_web.add_argument("--detail-rules", help="详情页提取规则（格式同 --rules）")
    p_web.add_argument("--max-pages", type=int, default=0, help="最大翻页数")
    p_web.add_argument("--max-items", type=int, default=0, help="最大爬取条目数")
    p_web.add_argument("--format", "-f", choices=["json", "csv", "db"], default="json", help="输出格式")
    p_web.add_argument("--output", "-o", help="输出文件路径")
    p_web.add_argument("--table", help="数据库表名（format=db 时使用）")
    p_web.add_argument("--concurrency", "-c", type=int, default=10, help="并发数")
    p_web.add_argument("--delay", type=float, default=1.5, help="请求间隔（秒）")

    # ---- video 子命令 ----
    p_video = sub.add_parser("video", help="视频下载")
    p_video.add_argument("url", help="视频 URL 或包含视频的网页 URL")
    p_video.add_argument("--output", "-o", help="输出文件名")
    p_video.add_argument("--extract", "-e", action="store_true", help="从网页中提取视频链接（不直接下载）")
    p_video.add_argument("--concurrency", "-c", type=int, default=8, help="ts 分片并发下载数")

    # ---- download 子命令 ----
    p_dl = sub.add_parser("download", help="媒体批量下载")
    p_dl.add_argument("url", help="文件 URL（多个用逗号分隔）")
    p_dl.add_argument("--type", "-t", choices=["image", "file"], default="file", help="下载类型")
    p_dl.add_argument("--page", "-p", action="store_true", help="从网页提取媒体链接")
    p_dl.add_argument("--selector", "-s", default="img", help="媒体元素 CSS 选择器")
    p_dl.add_argument("--output-dir", "-o", default="data/downloads", help="下载目录")
    p_dl.add_argument("--concurrency", "-c", type=int, default=8, help="并发下载数")

    # ---- analyze 子命令 ----
    p_ana = sub.add_parser("analyze", help="数据分析")
    p_ana.add_argument("file", help="数据文件路径 (.json / .csv / .db)")
    p_ana.add_argument("--table", help="数据库表名 (file 为 .db 时)")
    p_ana.add_argument("--column", help="要分析的列名")
    p_ana.add_argument("--chart", choices=["bar", "pie", "line", "wordcloud"], help="生成图表类型")
    p_ana.add_argument("--word-freq", help="词频统计列名")
    p_ana.add_argument("--top-n", type=int, default=20, help="显示 Top N")
    p_ana.add_argument("--clean", action="store_true", help="数据清洗")
    p_ana.add_argument("--output", "-o", help="图表输出路径")
    p_ana.add_argument("--export", help="导出数据路径 (.csv / .xlsx / .json)")
    p_ana.add_argument("--save-clean", help="清洗后保存路径")
    p_ana.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    # ---- douyin 子命令 ----
    p_douyin = sub.add_parser("douyin", help="抖音视频下载")
    p_douyin.add_argument("url_or_id", help="抖音视频 URL 或纯视频 ID")
    p_douyin.add_argument("--output", "-o", help="输出文件名")
    p_douyin.add_argument("--show-browser", action="store_true", help="显示浏览器窗口（调试用）")

    # ---- demo 子命令 ----
    sub.add_parser("demo", help="运行完整演示")

    # ---- 兼容：无子命令时默认跑原始爬虫 ----
    args = parser.parse_args()

    if args.command is None:
        _run_legacy()
        return

    if args.command == "web":
        asyncio.run(cmd_web(args))
    elif args.command == "video":
        asyncio.run(cmd_video(args))
    elif args.command == "download":
        asyncio.run(cmd_download(args))
    elif args.command == "analyze":
        asyncio.run(cmd_analyze(args))
    elif args.command == "douyin":
        asyncio.run(cmd_douyin(args))
    elif args.command == "demo":
        asyncio.run(cmd_demo(args))


def _run_legacy():
    """原始爬虫：保持向后兼容，直接 python main.py 也会跑"""
    import time
    import requests
    from bs4 import BeautifulSoup

    BASE_URL = "http://quotes.toscrape.com"
    print("=" * 50)
    print("  名人名言爬虫 (原始模式)")
    print(f"  目标: {BASE_URL}")
    print("  提示: 试用 python main.py demo 体验新功能")
    print("=" * 50)

    all_quotes = []
    current_url = BASE_URL
    page = 1

    while current_url:
        print(f"\n--- 第 {page} 页 --- {current_url}")
        try:
            resp = requests.get(current_url, headers=config.DEFAULT_HEADERS, timeout=10)
            resp.encoding = "utf-8"
            if resp.status_code != 200:
                break
            html = resp.text
        except Exception as e:
            print(f"  请求失败: {e}")
            break

        soup = BeautifulSoup(html, "html.parser")
        for div in soup.find_all("div", class_="quote"):
            text_span = div.find("span", class_="text")
            author = div.find("small", class_="author")
            tags = [t.text.strip() for t in div.find_all("a", class_="tag")]
            all_quotes.append({
                "text": text_span.text.strip('"').strip() if text_span else "",
                "author": author.text.strip() if author else "",
                "tags": tags,
            })

        next_link = soup.find("li", class_="next")
        current_url = BASE_URL + next_link.find("a")["href"] if next_link else None
        page += 1
        if current_url:
            time.sleep(1.5)

    with open("quotes.json", "w", encoding="utf-8") as f:
        json.dump(all_quotes, f, ensure_ascii=False, indent=2)
    print(f"\n[完成] 共 {len(all_quotes)} 条名言 → quotes.json")


if __name__ == "__main__":
    main()
