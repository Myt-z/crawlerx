"""
通用网页爬虫 —— 支持翻页、深度爬取、CSS/XPath 提取
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Any

from loguru import logger

import config
from .base import BaseCrawler
from parsers.html_parser import HTMLParser


class WebCrawler(BaseCrawler):
    """
    网页爬虫。
    - 支持单页 / 翻页 / 深度爬取
    - 支持 CSS 选择器 / XPath 提取
    - 自定义解析回调
    """

    def __init__(self, start_url: str = None, **kwargs):
        super().__init__(**kwargs)
        self.start_url = start_url
        self.parser = HTMLParser()

    # ---- 单页爬取 ----

    async def crawl_page(self, url: str, rules: dict) -> list[dict]:
        """
        爬取单个页面，按 rules 提取字段。

        rules 格式:
        {
            "title":   {"selector": "h1.title", "attr": "text"},
            "link":    {"selector": "a.read-more", "attr": "href"},
            "content": {"selector": "div.content p", "attr": "text", "multiple": True},
        }

        返回列表，每项是一个 dict。
        """
        html = await self.fetch(str(url))
        if html is None:
            return []
        return self.parser.parse_list(html, rules, url=str(url))

    # ---- 翻页爬取 ----

    async def crawl_paginated(
        self,
        start_url: str,
        rules: dict,
        next_selector: str = None,
        next_callback: Callable[[str, int], Optional[str]] = None,
        max_pages: int = 0,
        checkpoint_key: str = None,
    ) -> list[dict]:
        """
        翻页爬取，自动跟到下一页。

        - next_selector:  CSS 选择器定位「下一页」链接（取 href 属性）
        - next_callback:  自定义翻页函数，接收 (当前HTML, 当前页码)，返回下一页 URL 或 None
        - max_pages:       最大翻页数，0 表示不限
        - checkpoint_key:  检查点标识，提供后启用断点续爬（Ctrl+C 中断后可恢复）
        """
        all_data = []
        current_url = start_url
        page = 1
        seen_urls = set()
        checkpoint_path = None

        # ---- 断点续爬：加载检查点 ----
        if checkpoint_key and config.CHECKPOINT_ENABLED:
            config.CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
            safe_key = "".join(c for c in checkpoint_key if c.isalnum() or c in "_-")
            checkpoint_path = config.CHECKPOINT_DIR / f"{safe_key}.json"
            if checkpoint_path.exists():
                try:
                    ckpt = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                    all_data = ckpt.get("data", [])
                    current_url = ckpt.get("current_url", start_url)
                    page = ckpt.get("page", 1)
                    seen_urls = set(ckpt.get("seen_urls", []))
                    logger.info(f"[断点续爬] 从第 {page} 页恢复, 已有 {len(all_data)} 条数据")
                except Exception as e:
                    logger.warning(f"[断点续爬] 检查点损坏, 从头开始: {e}")

        while current_url:
            if max_pages > 0 and page > max_pages:
                break

            if current_url in seen_urls:
                logger.warning(f"[翻页] 检测到重复 URL，停止翻页: {current_url}")
                break
            seen_urls.add(current_url)

            logger.info(f"[翻页] 第 {page} 页 — {current_url}")
            html = await self.fetch(str(current_url))
            if html is None:
                break

            items = self.parser.parse_list(html, rules, url=str(current_url))
            logger.info(f"  提取 {len(items)} 条")
            all_data.extend(items)

            # ---- 保存检查点 ----
            if checkpoint_path and page % config.CHECKPOINT_INTERVAL == 0:
                try:
                    ckpt_data = {
                        "page": page + 1,
                        "current_url": current_url,
                        "data": all_data,
                        "seen_urls": list(seen_urls),
                        "updated_at": datetime.now().isoformat(),
                    }
                    checkpoint_path.write_text(
                        json.dumps(ckpt_data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    logger.debug(f"[检查点] 已保存, 第 {page} 页, 共 {len(all_data)} 条")
                except Exception as e:
                    logger.warning(f"[检查点] 保存失败: {e}")

            # 找下一页
            if next_callback:
                current_url = next_callback(html, page)
            elif next_selector:
                current_url = self.parser.next_page_url(html, current_url, next_selector)
            else:
                current_url = None

            page += 1

        # ---- 爬取完成，清理检查点 ----
        if checkpoint_path and checkpoint_path.exists():
            try:
                checkpoint_path.unlink()
                logger.info("[检查点] 爬取完成，已清理检查点文件")
            except Exception:
                pass

        return all_data

    # ---- 深度爬取（从列表页进入详情页） ----

    async def crawl_deep(
        self,
        start_url: str,
        list_rules: dict,
        detail_rules: dict,
        link_selector: str,
        detail_url_builder: Callable[[str], str] = None,
        max_pages: int = 0,
        max_items: int = 0,
    ) -> list[dict]:
        """
        先爬列表页提取详情链接，再逐条爬取详情页。

        - list_rules:    列表页提取规则
        - detail_rules:  详情页提取规则
        - link_selector: 详情页链接的 CSS 选择器
        - detail_url_builder: 将相对链接转为绝对链接
        - max_items:     最多爬多少条详情（0=不限）
        """
        all_detail = []

        # Phase 1: 收集所有详情链接
        html = await self.fetch(str(start_url))
        if html is None:
            return []

        detail_urls = self.parser.extract_links(html, link_selector)
        detail_urls = list(dict.fromkeys(detail_urls))  # 去重，保持顺序
        if detail_url_builder:
            detail_urls = [detail_url_builder(u) for u in detail_urls]

        if max_items > 0:
            detail_urls = detail_urls[:max_items]

        logger.info(f"[深度爬取] 共 {len(detail_urls)} 个详情页待爬")

        # Phase 2: 并发爬取详情页
        sem = asyncio.Semaphore(self.max_concurrent)

        async def _crawl_detail(url: str) -> dict:
            async with sem:
                h = await self.fetch(str(url))
                if h is None:
                    return {}
                items = self.parser.parse_list(h, detail_rules, url=str(url))
                result = items[0] if items else {}
                result["_url"] = url
                return result

        tasks = [_crawl_detail(u) for u in detail_urls]
        all_detail = await asyncio.gather(*tasks)
        return [d for d in all_detail if d]

    # ---- 快捷方法：直接传入选择器提取字段 ----

    async def extract_field(self, url: str, selector: str, attr: str = "text") -> Any:
        """提取单个字段值"""
        html = await self.fetch(str(url))
        if html is None:
            return None
        return self.parser.extract(html, selector, attr)
