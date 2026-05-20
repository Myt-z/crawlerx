"""
异步爬虫基类 —— 提供重试、UA 轮换、代理、速率控制等通用能力。
所有爬虫继承此类即可获得这些能力。
"""
import asyncio
import random
from pathlib import Path
from typing import Optional

import httpx
import aiohttp
from loguru import logger

import config


class BaseCrawler:
    """异步爬虫基类"""

    def __init__(
        self,
        delay: float = None,
        timeout: int = None,
        max_retries: int = None,
        max_concurrent: int = None,
        proxy: str = None,
        headers: dict = None,
    ):
        self.delay = delay or config.DEFAULT_DELAY
        self.timeout = timeout or config.DEFAULT_TIMEOUT
        self.max_retries = max_retries or config.MAX_RETRIES
        self.max_concurrent = max_concurrent or config.MAX_CONCURRENT
        self.proxy = proxy
        self.headers = headers or config.DEFAULT_HEADERS.copy()

        # 并发控制信号量
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

        # UA 池
        self._ua_list = self._load_user_agents()

        # session 按需延迟创建（避免跨事件循环问题）
        self._httpx_client: Optional[httpx.AsyncClient] = None
        self._aiohttp_session: Optional[aiohttp.ClientSession] = None

    # ---- UA 轮换 ----

    def _load_user_agents(self) -> list[str]:
        """加载 UA 列表，优先用 fake-useragent 库，否则用内置列表"""
        try:
            from fake_useragent import UserAgent
            ua = UserAgent()
            return [ua.chrome for _ in range(10)] + [ua.edge for _ in range(5)]
        except Exception:
            pass
        return [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        ]

    def _random_ua(self) -> str:
        return random.choice(self._ua_list)

    def _build_headers(self) -> dict:
        """构建请求头，可选 UA 轮换"""
        h = self.headers.copy()
        if config.USER_AGENT_ROTATION:
            h["User-Agent"] = self._random_ua()
        return h

    # ---- 代理 ----

    def _random_proxy(self) -> Optional[str]:
        if self.proxy:
            return self.proxy
        if config.PROXY_LIST:
            return random.choice(config.PROXY_LIST)
        return None

    # ---- 重试装饰器逻辑（内联在 fetch 中） ----

    async def fetch(
        self, url: str, method: str = "GET", raw: bool = False, **kwargs
    ) -> Optional[str | bytes]:
        """
        异步请求单个 URL，内置重试 + 退避。
        raw=True 返回 bytes（用于下载二进制文件）。
        """
        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self._semaphore:
                    result = await self._do_request(url, method, raw, **kwargs)
                if self.delay > 0:
                    await asyncio.sleep(self.delay)
                return result
            except Exception as e:
                last_exc = e
                wait = self.delay * (2 ** (attempt - 1))
                logger.warning(f"[重试 {attempt}/{self.max_retries}] {url} — {e}，等待 {wait:.1f}s")
                await asyncio.sleep(wait)

        logger.error(f"[失败] {url}: {last_exc}")
        return None

    async def _do_request(
        self, url: str, method: str, raw: bool, **kwargs
    ) -> str | bytes:
        """实际执行 HTTP 请求（使用 httpx）"""
        proxy_url = self._random_proxy()
        client = await self._get_httpx_client(proxy_url)
        h = self._build_headers()

        resp = await client.request(
            method=method,
            url=url,
            headers=h,
            timeout=self.timeout,
            **kwargs,
        )
        resp.raise_for_status()
        return resp.content if raw else resp.text

    async def _get_httpx_client(self, proxy_url: str = None) -> httpx.AsyncClient:
        """获取或创建 httpx 客户端。有代理时创建临时客户端。"""
        if proxy_url:
            return httpx.AsyncClient(
                proxy=proxy_url,
                follow_redirects=True,
                timeout=self.timeout,
            )
        if self._httpx_client is None:
            self._httpx_client = httpx.AsyncClient(
                follow_redirects=True,
                limits=httpx.Limits(max_connections=self.max_concurrent + 5),
            )
        return self._httpx_client

    # ---- 批量并发抓取 ----

    async def fetch_many(self, urls: list[str], **kwargs) -> list[Optional[str]]:
        """并发抓取多个 URL，返回结果列表（顺序与 urls 一致）"""
        tasks = [self.fetch(url, **kwargs) for url in urls]
        return await asyncio.gather(*tasks)

    async def fetch_many_with_limit(
        self, urls: list[str], concurrency: int = None, **kwargs
    ) -> list[Optional[str]]:
        """
        有限并发抓取多个 URL。
        当 URL 数量巨大时避免一次性发太多请求。
        """
        limit = concurrency or self.max_concurrent
        sem = asyncio.Semaphore(limit)

        async def _bounded(url):
            async with sem:
                return await self.fetch(url, **kwargs)

        return await asyncio.gather(*[_bounded(u) for u in urls])

    # ---- 下载二进制文件 ----

    async def download_file(self, url: str, dest: Path, chunk_size: int = None) -> bool:
        """
        下载二进制文件到本地（支持断点续传）。
        返回 True/False 表示成功/失败。
        """
        chunk_size = chunk_size or config.VIDEO_CHUNK_SIZE
        dest.parent.mkdir(parents=True, exist_ok=True)

        existing_size = dest.stat().st_size if dest.exists() else 0
        headers = self._build_headers()
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"

        try:
            client = await self._get_httpx_client()
            async with client.stream(
                "GET", url, headers=headers, timeout=self.timeout * 5
            ) as resp:
                if resp.status_code not in (200, 206):
                    logger.error(f"[下载失败] {url} status={resp.status_code}")
                    return False

                mode = "ab" if resp.status_code == 206 else "wb"
                with open(dest, mode) as f:
                    async for chunk in resp.aiter_bytes(chunk_size):
                        f.write(chunk)
            logger.info(f"[下载完成] {url} → {dest.name}")
            return True
        except Exception as e:
            logger.error(f"[下载失败] {url}: {e}")
            return False

    # ---- 资源回收 ----

    async def close(self):
        if self._httpx_client:
            await self._httpx_client.aclose()
            self._httpx_client = None
        if self._aiohttp_session:
            await self._aiohttp_session.close()
            self._aiohttp_session = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
