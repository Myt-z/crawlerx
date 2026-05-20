"""
可视化爬虫平台 — 基于 Gradio 的可对话半自动化爬虫助手
========================================================
支持自然语言沟通，自动识别意图、收集参数、执行任务、展示结果。

启动: python app.py
访问: http://localhost:7860
"""
import asyncio
import os
import re
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

import gradio as gr
import config
from config import DATA_DIR

# ================================================================
# 状态机定义
# ================================================================

class AgentState:
    IDLE = "idle"
    WEB_CRAWL = "web_crawl"       # 等待网页爬取参数
    VIDEO_DL = "video_dl"         # 等待视频下载参数
    DOUYIN_DL = "douyin_dl"       # 等待抖音下载参数
    ANALYZE = "analyze"           # 等待分析参数
    MEDIA_DL = "media_dl"         # 等待媒体下载参数
    EXECUTING = "executing"       # 正在执行


# ================================================================
# 对话 Agent — 意图识别 + 参数收集 + 任务调度
# ================================================================

class CrawlerAgent:
    """爬虫对话助手——理解用户意图，收集缺失参数，执行任务"""

    def __init__(self):
        self.state = AgentState.IDLE
        self.params: dict = {}
        self.last_result: dict = {}

    # ---- 意图识别 ----

    def detect_intent(self, message: str) -> str:
        """从用户消息中识别意图"""
        msg = message.lower().strip()

        # 抖音 (优先级最高, URL特征明显)
        if re.search(r"douyin\.com|抖音|modal_id", msg):
            return AgentState.DOUYIN_DL

        # 爬虫/抓取
        if any(w in msg for w in ["爬", "抓取", "采集", "爬虫", "crawl"]):
            return AgentState.WEB_CRAWL

        # 视频
        if any(w in msg for w in ["视频", "video", "m3u8", ".mp4", "下载视频"]):
            if "douyin" in msg or "抖音" in msg:
                return AgentState.DOUYIN_DL
            return AgentState.VIDEO_DL

        # 分析
        if any(w in msg for w in ["分析", "统计", "图表", "可视化", "analyze", "词频", "词云"]):
            return AgentState.ANALYZE

        # 下载媒体
        if any(w in msg for w in ["下载图片", "下载文件", "批量下载", "download"]):
            return AgentState.MEDIA_DL

        # 如果当前有状态，继续当前状态
        if self.state != AgentState.IDLE:
            return self.state

        return AgentState.IDLE

    # ---- URL 提取 ----

    def extract_url(self, message: str) -> Optional[str]:
        """从消息中提取 URL"""
        urls = re.findall(r"https?://[^\s,，。]+", message)
        return urls[0] if urls else None

    def extract_number(self, message: str, key: str) -> Optional[int]:
        """提取数量参数"""
        patterns = [
            rf"{key}[：:\s]*(\d+)",
            rf"(\d+)\s*[页条个张]",
        ]
        for p in patterns:
            m = re.search(p, message)
            if m:
                return int(m.group(1))
        return None

    # ---- 参数检查与问题生成 ----

    def check_web_params(self) -> list[str]:
        """检查网页爬取参数是否齐全，返回缺失项的问题列表"""
        questions = []
        if not self.params.get("url"):
            questions.append("请提供目标网站的网址（URL）")
        if not self.params.get("rules"):
            questions.append(
                "请告诉我要提取哪些字段，以及对应的 CSS 选择器。\n"
                "格式: `字段名:选择器`。例如：\n"
                "• title:h1.title — 提取标题\n"
                "• price:span.price — 提取价格\n"
                "• link:a:attr:href — 提取链接地址\n"
                '多个字段用英文逗号分隔，如: `title:h1.title,price:span.price`'
            )
        elif "paginate" not in self.params:
            questions.append("需要自动翻页吗？请回复「是」或「否」")
        elif self.params.get("paginate") and "next_selector" not in self.params:
            questions.append("「下一页」按钮的 CSS 选择器是什么？例如: `a.next` 或 `li.next a`")
        else:
            if "format" not in self.params:
                questions.append("数据保存为什么格式？json / csv / db (默认 json)")
            elif self.params.get("paginate") and "max_pages" not in self.params:
                questions.append("最多爬多少页？（0=不限制，直接回车即可）")
        return questions

    def check_video_params(self) -> list[str]:
        """检查视频下载参数"""
        questions = []
        if not self.params.get("url"):
            questions.append("请提供视频的 URL（m3u8 链接、mp4 直链，或包含视频的网页地址）")
        if "output" not in self.params:
            # 可选
            pass
        return questions

    def check_douyin_params(self) -> list[str]:
        if not self.params.get("url"):
            questions = ["请提供抖音视频的链接或视频 ID"]
        else:
            return []  # 参数齐全，直接执行
        return questions

    def check_analyze_params(self) -> list[str]:
        questions = []
        if not self.params.get("file"):
            questions.append("请提供数据文件路径（支持 .json / .csv / .db）")
        return questions  # column 和 chart 是可选的

    # ---- 参数解析 ----

    def parse_web_params(self, message: str):
        """从用户消息中提取网页爬取参数"""
        # URL
        url = self.extract_url(message)
        if url:
            self.params["url"] = url

        # Rules: 按逗号分割，每段是 field:selector 或 field:selector:attr
        rules = {}
        # 先去掉翻页、格式等关键词，避免干扰
        clean = re.sub(r'[，,]?\s*(不?翻页?|json|csv|db|是|否|单页|一页|下一页|multi|多值)\s*[，,]?', '', message)
        # 找所有 field:selector 对（selector可以包含字母数字.#->空格）
        rule_pattern = r"(\w+)\s*:\s*([a-zA-Z0-9.#\-_ >:]+?)(?:,|，|$)"
        for m in re.finditer(rule_pattern, clean):
            field = m.group(1)
            raw_sel = m.group(2).strip().rstrip(',，')
            # 处理 field:selector:attr 格式
            # selector 中可能有 :attr: 或末尾 :text
            if raw_sel.endswith(':text'):
                sel = raw_sel[:-5]
                attr = 'text'
            elif ':attr:' in raw_sel:
                parts = raw_sel.split(':attr:', 1)
                sel = parts[0]
                attr = parts[1] if len(parts) > 1 else 'text'
            else:
                sel = raw_sel
                attr = 'text'
            rules[field] = {"selector": sel.strip(), "attr": attr}

        if rules:
            self.params["rules"] = rules

        # 翻页
        if re.search(r"是|[Yy]es|翻页|paginate|下一页", message) and not re.search(r"不翻|否", message):
            self.params["paginate"] = True
        elif re.search(r"否|[Nn]o|不翻|单页|一页", message):
            self.params["paginate"] = False

        # 下一页选择器
        next_m = re.search(r"[Nn]ext.*?[:：\s]+([a-zA-Z0-9.#\-\s>]+)", message)
        if next_m:
            self.params["next_selector"] = next_m.group(1).strip()
        elif "next" in message.lower():
            self.params["next_selector"] = "a.next"

        # 最大页数
        n = self.extract_number(message, "页")
        if n is not None:
            self.params["max_pages"] = n
        elif "不限制" in message or "全部" in message:
            self.params["max_pages"] = 0

        # 格式
        for fmt in ["json", "csv", "db"]:
            if fmt in message.lower():
                self.params["format"] = fmt

        # 输出文件名
        out_m = re.search(r"输出[：:\s]+(\S+)", message)
        if out_m:
            self.params["output"] = out_m.group(1)

    def parse_video_params(self, message: str):
        url = self.extract_url(message)
        if url:
            self.params["url"] = url
        out_m = re.search(r"(?:文件名|保存为|output)[：:\s]+(\S+)", message)
        if out_m:
            self.params["output"] = out_m.group(1)

    def parse_douyin_params(self, message: str):
        url = self.extract_url(message)
        if url:
            self.params["url"] = url
        # 也可能直接给 ID
        id_m = re.search(r"(\d{15,20})", message)
        if id_m and not self.params.get("url"):
            self.params["url"] = id_m.group(1)

    def parse_analyze_params(self, message: str):
        # 文件路径
        file_m = re.search(r"([\w/\\\-]+\.(?:json|csv|db))", message)
        if file_m:
            self.params["file"] = file_m.group(1)

        # 列名 - 找 "分析 xxx 列" 或 "column: xxx"
        col_m = re.search(r"(?:列|column|字段)[：:\s]*(\w+)", message)
        if col_m:
            self.params["column"] = col_m.group(1)

        # 图表类型
        for ct in ["bar", "pie", "line", "wordcloud", "柱状图", "饼图", "折线图", "词云"]:
            if ct in message:
                self.params["chart"] = ct if ct in ("bar", "pie", "line", "wordcloud") else {
                    "柱状图": "bar", "饼图": "pie", "折线图": "line", "词云": "wordcloud"
                }[ct]

        # Top N
        n = self.extract_number(message, "Top|top")
        if n:
            self.params["top_n"] = n

    # ---- 主循环: 处理消息, 返回回复 ----

    async def process(self, message: str) -> str:
        """处理一条用户消息，返回助手的回复"""
        msg = message.strip()
        intent = self.detect_intent(msg)

        # 如果新意图与当前状态不同，重置状态
        # 如果检测到 IDLE（消息无明确意图），保持当前状态继续收集参数
        if intent == AgentState.IDLE and self.state != AgentState.IDLE:
            intent = self.state  # 保持当前状态
        elif self.state != AgentState.IDLE and intent != self.state:
            self.state = intent
            self.params = {}
        else:
            self.state = intent

        # ---- IDLE: 识别意图 ----
        if self.state == AgentState.IDLE:
            return self._welcome()

        # ---- WEB_CRAWL ----
        elif self.state == AgentState.WEB_CRAWL:
            self.parse_web_params(msg)
            questions = self.check_web_params()

            if questions:
                return f"**[网页爬取]** 还需要以下信息：\n\n" + "\n\n".join(
                    f"**{i+1}.** {q}" for i, q in enumerate(questions)
                )
            # 参数齐全 -> 执行
            return await self._execute_web_crawl()

        # ---- VIDEO_DL ----
        elif self.state == AgentState.VIDEO_DL:
            self.parse_video_params(msg)
            questions = self.check_video_params()
            if questions:
                return f"**[视频下载]** 还需要以下信息：\n\n" + "\n\n".join(
                    f"**{i+1}.** {q}" for i, q in enumerate(questions)
                )
            return await self._execute_video_dl()

        # ---- DOUYIN_DL ----
        elif self.state == AgentState.DOUYIN_DL:
            self.parse_douyin_params(msg)
            questions = self.check_douyin_params()
            if questions:
                return f"**[抖音下载]** \n\n" + "\n".join(questions)
            return await self._execute_douyin_dl()

        # ---- ANALYZE ----
        elif self.state == AgentState.ANALYZE:
            self.parse_analyze_params(msg)
            questions = self.check_analyze_params()
            if questions:
                return f"**[数据分析]** 还需要以下信息：\n\n" + "\n\n".join(
                    f"**{i+1}.** {q}" for i, q in enumerate(questions)
                )
            return await self._execute_analyze()

        # ---- MEDIA_DL ----
        elif self.state == AgentState.MEDIA_DL:
            self.parse_video_params(msg)  # 复用 URL 提取
            if not self.params.get("url"):
                return "**[媒体下载]** 请提供要下载的文件 URL 或包含媒体的网页地址"
            return await self._execute_media_dl()

        return "抱歉，我不太理解你的意思。请重新描述一下你想做什么？\n\n你可以说：\n• 「爬」某网站\n• 「下载」视频\n• 「分析」数据\n• 「下载」图片"

    # ================================================================
    # 任务执行
    # ================================================================

    async def _execute_web_crawl(self) -> str:
        self.state = AgentState.EXECUTING
        p = self.params

        try:
            from crawlers import WebCrawler
            crawler = WebCrawler(delay=1.0, max_concurrent=10)

            rules = p["rules"]
            if p.get("paginate"):
                data = await crawler.crawl_paginated(
                    start_url=p["url"],
                    rules=rules,
                    next_selector=p.get("next_selector", "a.next"),
                    max_pages=p.get("max_pages", 0),
                )
            else:
                data = await crawler.crawl_page(p["url"], rules)

            await crawler.close()
            self.last_result = {"type": "web", "data": data, "count": len(data)}

            # 保存
            fmt = p.get("format", "json")
            out_path = self._save_data(data, fmt)

            preview = self._format_preview(data[:5], len(data))
            self.state = AgentState.IDLE
            self.params = {}

            return (
                f"✅ **爬取完成！**\n\n"
                f"📊 共获取 **{len(data)}** 条数据\n"
                f"💾 已保存至: `{out_path}`\n\n"
                f"{preview}\n\n"
                f"---\n"
                f"💡 下一步你可以：\n"
                f'• 输入「分析 {out_path}」来统计数据\n'
                f'• 输入「分析 {out_path} 柱状图」生成图表\n'
                f'• 输入「爬 XXX」开始新的爬取'
            )
        except Exception as e:
            self.state = AgentState.IDLE
            self.params = {}
            return f"❌ **爬取失败**: {e}"

    async def _execute_video_dl(self) -> str:
        self.state = AgentState.EXECUTING
        p = self.params

        try:
            from crawlers import VideoCrawler
            crawler = VideoCrawler()

            path = await crawler.download_m3u8(p["url"], filename=p.get("output"))

            await crawler.close()
            self.state = AgentState.IDLE
            self.params = {}

            if path:
                size_mb = path.stat().st_size / 1024 / 1024
                return f"✅ **视频下载完成！**\n\n📁 路径: `{path}`\n📦 大小: {size_mb:.1f} MB"
            else:
                return "❌ **下载失败**，请检查 URL 是否有效，或确认 ffmpeg 已安装。"
        except Exception as e:
            self.state = AgentState.IDLE
            self.params = {}
            return f"❌ **下载失败**: {e}"

    async def _execute_douyin_dl(self) -> str:
        self.state = AgentState.EXECUTING
        p = self.params

        try:
            from douyin_dl import DouyinDownloader
            dl = DouyinDownloader(headless=True)
            path = await dl.download(p["url"], output_name=p.get("output"))

            self.state = AgentState.IDLE
            self.params = {}

            if path:
                size_mb = path.stat().st_size / 1024 / 1024
                return (
                    f"✅ **抖音视频下载完成！**\n\n"
                    f"📁 路径: `{path}`\n"
                    f"📦 大小: {size_mb:.1f} MB\n\n"
                    f"💡 视频已保存在 `data/videos/` 目录"
                )
            else:
                return (
                    "❌ **下载失败**\n\n"
                    "可能原因：\n"
                    "1. 该视频需要登录才能观看\n"
                    "2. 视频已被删除或设为私密\n"
                    "3. 系统 Edge 浏览器不可用"
                )
        except Exception as e:
            self.state = AgentState.IDLE
            self.params = {}
            return f"❌ **下载失败**: {e}"

    async def _execute_analyze(self) -> str:
        self.state = AgentState.EXECUTING
        p = self.params

        file_path = p.get("file", "")
        if not Path(file_path).exists():
            # 尝试在 data 目录下找
            alt = DATA_DIR / file_path
            if alt.exists():
                file_path = str(alt)
            else:
                self.state = AgentState.IDLE
                self.params = {}
                return f"❌ 文件不存在: `{file_path}`\n请确认路径是否正确"

        try:
            from analysis import DataAnalyzer, Visualizer
            from pathlib import Path as P

            path = P(file_path)
            if path.suffix == ".json":
                analyzer = DataAnalyzer.from_json(path)
            elif path.suffix == ".csv":
                analyzer = DataAnalyzer.from_csv(path)
            else:
                analyzer = DataAnalyzer.from_db(path)

            lines = []
            lines.append(f"✅ **数据分析完成**\n")
            lines.append(f"📊 共 **{len(analyzer.df)}** 行, **{len(analyzer.df.columns)}** 列")
            lines.append(f"📋 列名: {', '.join(analyzer.df.columns[:15])}")

            # 频率分布
            if p.get("column"):
                col = p["column"]
                if col in analyzer.df.columns:
                    top = p.get("top_n", 10)
                    vc = analyzer.value_counts(col, top_n=top)
                    lines.append(f"\n**{col}** 分布 Top {top}:")
                    lines.append("```")
                    lines.append(vc.to_string(index=False))
                    lines.append("```")

                    # 图表
                    if p.get("chart"):
                        chart_type = p["chart"]
                        charts_dir = P("data/charts")
                        charts_dir.mkdir(parents=True, exist_ok=True)
                        chart_path = charts_dir / f"chat_{col}_{chart_type}.png"
                        Visualizer.from_value_counts(
                            analyzer.df, col, chart_type=chart_type,
                            top_n=top, title=f"{col} 分布",
                            save_path=chart_path,
                        )
                        lines.append(f"\n📈 图表已生成: `{chart_path}`")
                else:
                    lines.append(f"\n⚠️ 列 '{col}' 不存在，可用列: {', '.join(analyzer.df.columns)}")

            # 词频
            if p.get("chart") == "wordcloud" and p.get("column"):
                from analysis import Visualizer
                freq = analyzer.word_frequency(p["column"], top_n=100)
                chart_path = P("data/charts") / f"chat_wordcloud.png"
                Visualizer.wordcloud(freq, title="词云", save_path=chart_path)
                lines.append(f"\n☁️ 词云已生成: `{chart_path}`")

            self.state = AgentState.IDLE
            self.params = {}
            return "\n".join(lines)
        except Exception as e:
            self.state = AgentState.IDLE
            self.params = {}
            return f"❌ **分析失败**: {e}"

    async def _execute_media_dl(self) -> str:
        self.state = AgentState.EXECUTING
        p = self.params
        try:
            from downloader import MediaDownloader
            dl = MediaDownloader()
            urls = [u.strip() for u in p["url"].split(",")]
            saved = await dl.download_images(urls)
            await dl.close()

            self.state = AgentState.IDLE
            self.params = {}
            return f"✅ **下载完成**\n\n📁 共 {len(saved)} 个文件\n📂 保存至: `{dl.download_dir}`"
        except Exception as e:
            self.state = AgentState.IDLE
            self.params = {}
            return f"❌ **下载失败**: {e}"

    # ================================================================
    # 工具方法
    # ================================================================

    def _welcome(self) -> str:
        return (
            "👋 **你好！我是爬虫助手。**\n\n"
            "我能帮你做这些事：\n\n"
            "🌐 **网页爬取** — 说「爬」+ 网址\n"
            "📹 **视频下载** — 说「下载视频」+ 链接\n"
            "🎵 **抖音下载** — 直接发抖音链接\n"
            "📊 **数据分析** — 说「分析」+ 文件路径\n"
            "🖼️ **图片下载** — 说「下载图片」+ 链接\n\n"
            "💬 **示例**: 「爬 https://example.com，提取标题和价格」\n"
            "💬 **示例**: 「https://www.douyin.com/video/xxx」\n"
            "💬 **示例**: 「分析 data/demo/quotes.json」\n\n"
            "你想做什么？"
        )

    def _save_data(self, data: list[dict], fmt: str) -> str:
        from storage import JSONStorage, CSVStorage, DBStorage
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path("data")

        if fmt == "csv":
            p = out_dir / f"crawl_{timestamp}.csv"
            CSVStorage(p).save(data)
        elif fmt == "db":
            p = out_dir / f"crawl_{timestamp}.db"
            with DBStorage(p) as db:
                db.create_table_from_data("data", data[0])
                db.insert("data", data)
        else:
            p = out_dir / f"crawl_{timestamp}.json"
            JSONStorage(p).save(data)
        return str(p)

    def _format_preview(self, items: list[dict], total: int) -> str:
        if not items:
            return "_(无数据)_"
        lines = [f"**数据预览** (前 {len(items)} 条):\n"]
        for i, item in enumerate(items, 1):
            lines.append(f"**[{i}]**")
            for k, v in item.items():
                v_str = str(v)
                display = v_str[:60] + "..." if len(v_str) > 60 else v_str
                lines.append(f"  • {k}: {display}")
            lines.append("")
        return "\n".join(lines)


# ================================================================
# Gradio UI
# ================================================================

agent = CrawlerAgent()

async def chat_handler(message: str, history: list):
    """Gradio ChatInterface 回调"""
    reply = await agent.process(message)
    return reply


def create_ui():
    """构建 Gradio Web 界面"""
    with gr.Blocks(title="爬虫助手 - Python 全功能爬虫平台") as app:
        gr.Markdown("""
        <div style="text-align: center; margin-bottom: 10px;">
        <h1>Python 全功能爬虫平台</h1>
        <p style="color: #666; font-size: 14px;">跟我对话 -- 爬网页、下视频、分析数据</p>
        </div>
        """)

        with gr.Row(equal_height=True):
            with gr.Column(scale=4):
                chatbot = gr.ChatInterface(
                    fn=chat_handler,
                    chatbot=gr.Chatbot(height=550),
                )

            with gr.Column(scale=1, min_width=180):
                gr.Markdown("""
                <div style="font-size: 13px; line-height: 1.8;">
                **快捷指令**
                <hr style="margin: 4px 0;">
                <b>网页爬取</b><br>
                <code style="font-size: 11px;">爬 URL 提取字段</code><br><br>
                <b>抖音下载</b><br>
                <code style="font-size: 11px;">粘贴链接即可</code><br><br>
                <b>视频下载</b><br>
                <code style="font-size: 11px;">下载视频 URL</code><br><br>
                <b>数据分析</b><br>
                <code style="font-size: 11px;">分析 data/xxx.json</code><br><br>
                <b>图片下载</b><br>
                <code style="font-size: 11px;">下载图片 URL</code>
                <hr style="margin: 4px 0;">
                <b>输出文件</b>
                </div>
                """)

                file_md = gr.Markdown(_list_output_files_text())

    return app


def _list_output_files_text() -> str:
    """生成输出文件列表文本"""
    lines = []
    for d in ["demo", "json", "csv", "charts", "videos"]:
        p = Path("data") / d
        if p.exists():
            for f in sorted(p.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:3]:
                if f.is_file():
                    lines.append(f"📄 `{f.name}`")
    return "\n".join(lines) if lines else "_(暂无文件)_"


def _list_output_files():
    """列出输出文件供下载"""
    files = []
    for d in ["demo", "json", "csv", "charts", "videos"]:
        p = Path("data") / d
        if p.exists():
            for f in sorted(p.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
                if f.is_file():
                    files.append((str(f), str(f.relative_to("."))))
    if files:
        gr.Markdown("\n".join(f"📄 `{name}`" for _, name in files))
    else:
        gr.Markdown("_(暂无文件)_")


# ================================================================
# 启动
# ================================================================

def main():
    print("=" * 55)
    print("  Python 全功能爬虫平台 -- 可视化版")
    print("=" * 55)
    print()
    print("  启动后访问: http://localhost:7860")
    print()
    print("  你可以跟爬虫助手对话，例如：")
    print('    - "爬 https://quotes.toscrape.com 提取名言和作者"')
    print('    - "https://www.douyin.com/video/xxx"')
    print('    - "分析 data/demo/quotes.json，生成柱状图"')
    print()
    print("  按 Ctrl+C 停止服务")
    print()

    ui = create_ui()
    ui.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        inbrowser=True,
        css="""
        /* ===== 整体布局 ===== */
        .gradio-container {
            max-width: 900px !important;
            margin: 0 auto !important;
        }
        footer { display: none !important; }

        /* ===== 聊天窗口 ===== */
        .chatbot {
            height: 550px !important;
        }

        /* ===== 矩形对话框 —— 用户消息 ===== */
        .bubble-wrap.user .message-wrap .message {
            border-radius: 2px !important;
            background: #1a73e8 !important;
            color: #fff !important;
            border: 1px solid #1557b0 !important;
            font-size: 14px !important;
            padding: 10px 14px !important;
            box-shadow: none !important;
        }

        /* ===== 矩形对话框 —— 机器人消息 ===== */
        .bubble-wrap.bot .message-wrap .message {
            border-radius: 2px !important;
            background: #f1f3f4 !important;
            color: #202124 !important;
            border: 1px solid #dadce0 !important;
            font-size: 14px !important;
            padding: 10px 14px !important;
            box-shadow: none !important;
        }

        /* ===== 输入框区域 ===== */
        .textbox-container textarea {
            border-radius: 2px !important;
            border: 1px solid #dadce0 !important;
            font-size: 14px !important;
            padding: 10px 12px !important;
        }
        .textbox-container textarea:focus {
            border-color: #1a73e8 !important;
            box-shadow: 0 0 0 2px rgba(26,115,232,0.15) !important;
        }

        /* ===== 按钮 ===== */
        button {
            border-radius: 2px !important;
            font-size: 13px !important;
            text-transform: none !important;
        }
        button.primary {
            background: #1a73e8 !important;
            border: 1px solid #1557b0 !important;
        }

        /* ===== 右侧面板 ===== */
        .prose {
            font-size: 13px !important;
        }
        """,
    )


if __name__ == "__main__":
    main()
