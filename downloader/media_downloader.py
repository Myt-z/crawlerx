"""
通用媒体下载器 —— 支持图片 / 音频 / 文档等任意文件类型
"""
import asyncio
import hashlib
import os
import re
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urlparse

from loguru import logger
from tqdm.asyncio import tqdm

import config
from crawlers.base import BaseCrawler


class MediaDownloader:
    """
    批量文件下载器，封装 BaseCrawler 的下载能力。
    支持进度条、去重、自动命名、并发控制。
    """

    def __init__(self, download_dir: str | Path = None, max_workers: int = None):
        self.download_dir = Path(download_dir or config.VIDEO_DIR)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.max_workers = max_workers or config.VIDEO_MAX_WORKERS
        self._crawler: Optional[BaseCrawler] = None

    # ---- 图片批量下载 ----

    async def download_images(
        self,
        urls: list[str],
        prefix: str = "img",
        progress: bool = True,
    ) -> list[Path]:
        """
        批量下载图片，自动识别扩展名（jpg/png/gif/webp）。
        返回成功下载的文件路径列表。
        """
        crawler = await self._get_crawler()
        sem = asyncio.Semaphore(self.max_workers)
        saved = []
        failed = 0

        async def _download(url: str, idx: int) -> Optional[Path]:
            async with sem:
                ext = self._guess_ext(url, default=".jpg")
                filename = f"{prefix}_{idx:04d}{ext}"
                filepath = self.download_dir / filename
                if filepath.exists():
                    return filepath
                ok = await crawler.download_file(url, filepath)
                return filepath if ok else None

        tasks = [_download(url, i) for i, url in enumerate(urls, 1)]

        if progress:
            for coro in tqdm.as_completed(tasks, desc="下载图片", total=len(tasks)):
                r = await coro
                if r:
                    saved.append(r)
                else:
                    failed += 1
        else:
            results = await asyncio.gather(*tasks)
            saved = [r for r in results if r is not None]
            failed = len(urls) - len(saved)

        if failed:
            logger.warning(f"[图片] 下载完成 {len(saved)}/{len(urls)}，失败 {failed}")
        return saved

    # ---- 通用文件下载 ----

    async def download_files(
        self,
        urls: list[str],
        filenames: list[str] = None,
        progress: bool = True,
    ) -> list[Path]:
        """批量下载任意文件（需提供文件名列表）"""
        crawler = await self._get_crawler()
        sem = asyncio.Semaphore(self.max_workers)
        saved = []

        if filenames is None:
            filenames = [self._url_to_filename(u) for u in urls]

        async def _download(url: str, fname: str) -> Optional[Path]:
            async with sem:
                filepath = self.download_dir / fname
                if filepath.exists():
                    return filepath
                ok = await crawler.download_file(url, filepath)
                return filepath if ok else None

        pairs = list(zip(urls, filenames))
        tasks = [_download(u, f) for u, f in pairs]

        if progress:
            for coro in tqdm.as_completed(tasks, desc="下载文件", total=len(tasks)):
                r = await coro
                if r:
                    saved.append(r)
        else:
            results = await asyncio.gather(*tasks)
            saved = [r for r in results if r is not None]

        return saved

    # ---- 从 HTML 提取并下载 ----

    async def download_from_page(
        self,
        page_url: str,
        selector: str = "img",
        attr: str = "src",
        filename_pattern: str = None,
    ) -> list[Path]:
        """
        从网页中提取媒体链接并批量下载。
        selector="img" → 下载所有图片
        selector="video source" → 下载视频
        """
        from parsers.html_parser import HTMLParser

        crawler = await self._get_crawler()
        html = await crawler.fetch(str(page_url))
        if html is None:
            return []

        parser = HTMLParser()
        urls = parser.extract_list(html, selector, attr)

        # 过滤无效 URL
        urls = [u for u in urls if u and u.startswith(("http://", "https://"))]

        if not urls:
            logger.warning(f"[提取] 未在 {page_url} 中找到匹配 {selector} 的资源")
            return []

        logger.info(f"[提取] 从页面找到 {len(urls)} 个资源")
        return await self.download_images(urls, prefix="dl")

    # ---- 工具 ----

    def _guess_ext(self, url: str, default: str = ".bin") -> str:
        """从 URL 推断文件扩展名"""
        # 去掉查询参数
        path = urlparse(url).path
        ext = os.path.splitext(path)[1].lower()
        if ext and len(ext) <= 5 and ext.isalnum() or ext.startswith("."):
            return ext
        # 尝试从 Content-Type 推断？先返回默认值
        return default

    def _url_to_filename(self, url: str) -> str:
        """URL → 安全的文件名"""
        parsed = urlparse(url)
        path = parsed.path
        name = os.path.basename(path) or hashlib.md5(url.encode()).hexdigest()[:12]
        if not os.path.splitext(name)[1]:
            name += ".bin"
        return name

    async def _get_crawler(self) -> BaseCrawler:
        if self._crawler is None:
            self._crawler = BaseCrawler(max_concurrent=self.max_workers)
        return self._crawler

    async def close(self):
        if self._crawler:
            await self._crawler.close()
