"""
抖音视频下载器 —— 基于 Playwright 浏览器自动化
================================================
原理：
1. 用 Playwright 启动真实 Chromium 浏览器
2. 访问抖音视频页面，JS 完整渲染
3. 拦截页面发出的网络请求，抓到真实视频 .mp4 地址
4. 用 httpx 下载视频文件

用法：
  python douyin_dl.py <视频URL或视频ID>
  python douyin_dl.py 7640469163852533027
"""
import asyncio
import re
import sys
from pathlib import Path

import httpx
from loguru import logger

# 尝试导入 curl_cffi 用于 TLS 指纹伪装
try:
    import curl_cffi as _curl_cffi
    _HAS_CURL_CFFI_DOUYIN = True
except ImportError:
    _HAS_CURL_CFFI_DOUYIN = False
    _curl_cffi = None

# 项目根目录
sys.path.insert(0, str(Path(__file__).parent))
import config

VIDEO_ID_PATTERN = re.compile(r"(\d{15,20})")
DOUYIN_VIDEO_URL = re.compile(r"https?://(?:www\.)?douyin\.com/(?:video|user/self\?.*modal_id=)(\d+)")

# 视频 CDN 域名特征
VIDEO_CDN_PATTERNS = [
    r"douyinvod\.com",
    r"douyin\.com/.*\.(mp4|mov)",
    r"snssdk\.com",
    r"bytecdn\.cn",
    r"ixigua\.com",
    r"bytedance\.com.*\.(mp4|mov)",
    r"pstatp\.com",
]


class DouyinDownloader:
    """
    抖音视频下载器
    - 自动从页面 URL 提取视频 ID
    - Playwright 渲染页面 + 网络拦截
    - 支持无水印/有水印两种链接
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.video_urls: list[str] = []
        self.video_dir = Path(config.VIDEO_DIR)
        self.video_dir.mkdir(parents=True, exist_ok=True)

    # ================================================================
    # 入口
    # ================================================================

    async def download(self, url_or_id: str, output_name: str = None) -> Path | None:
        """主入口：给 URL 或视频 ID，返回下载好的文件路径"""
        video_id = self._extract_id(url_or_id)
        logger.info(f"视频 ID: {video_id}")

        # Step 1: 用 Playwright 打开视频页，拦截真实视频地址
        real_video_url = await self._get_video_url(video_id)
        if not real_video_url:
            logger.error("未能获取到视频下载地址")
            return None

        logger.info(f"真实视频地址: {real_video_url[:120]}...")

        # Step 2: 下载视频
        out_name = output_name or f"douyin_{video_id}.mp4"
        out_path = self.video_dir / out_name
        success = await self._download_video(real_video_url, out_path)
        return out_path if success else None

    # ================================================================
    # Playwright 渲染 + 网络拦截
    # ================================================================

    async def _get_video_url(self, video_id: str) -> str | None:
        """用 Playwright 打开抖音视频页，拦截 mp4 请求"""
        from playwright.async_api import async_playwright

        page_url = f"https://www.douyin.com/video/{video_id}"

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                channel="msedge",  # 使用系统自带的 Edge 浏览器
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )

            # 注入反检测脚本
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh']});
            """)

            page = await context.new_page()

            # --- 网络拦截：抓到任何 mp4 请求就记录下来 ---
            captured_urls: list[str] = []

            async def _on_request(request):
                url = request.url
                # 视频请求的特征
                if any(re.search(p, url) for p in VIDEO_CDN_PATTERNS):
                    captured_urls.append(url)
                    logger.debug(f"[拦截] {url[:120]}")

            async def _on_response(response):
                url = response.url
                content_type = response.headers.get("content-type", "")
                if "video/" in content_type and response.status == 200:
                    captured_urls.append(url)
                    logger.debug(f"[响应] video/{content_type} → {url[:120]}")

            page.on("request", _on_request)
            page.on("response", _on_response)

            # 访问视频页
            logger.info(f"正在打开: {page_url}")
            try:
                await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                # 等待视频元素加载
                await page.wait_for_timeout(8000)  # 等 JS 渲染完、视频开始加载
            except Exception as e:
                logger.warning(f"页面加载可能不完整: {e}")
                await page.wait_for_timeout(5000)

            # 尝试从页面 JS 变量中提取视频信息（方案 B）
            if not captured_urls:
                try:
                    js_data = await page.evaluate("""() => {
                        // 尝试从各种可能的全局变量中获取视频数据
                        const sources = [];
                        // 方法: 扫描所有 script 标签中的 JSON
                        document.querySelectorAll('script').forEach(s => {
                            if (s.textContent && s.textContent.includes('video')){
                                sources.push(s.textContent.substring(0, 5000));
                            }
                        });
                        return sources;
                    }""")
                    # 从 script 内容中提取视频 URL
                    for src in js_data:
                        urls = re.findall(
                            r'https?://[^"\'\\s]+/(?:[^"\'\\s]*?)(?:play|video|aweme)[^"\'\\s]*?\.(?:mp4|m3u8)[^"\'\\s]*',
                            src, re.IGNORECASE,
                        )
                        captured_urls.extend(urls)
                except Exception as e:
                    logger.debug(f"JS 提取失败: {e}")

            await browser.close()

            # 去重 + 排序（无水印优先，mp4 优先）
            unique = list(dict.fromkeys(captured_urls))
            return self._pick_best_url(unique)

    def _pick_best_url(self, urls: list[str]) -> str | None:
        """从捕获的 URL 中选择最好的（无水印 > 有水印，mp4 > 其他）"""
        if not urls:
            return None

        # 优先级：不含 watermark 关键词 > 含 watermark > 其他
        def _priority(u: str) -> int:
            score = 0
            if ".mp4" in u:
                score += 10
            if "watermark" in u.lower() or "wm" in u.lower():
                score -= 5
            if "play" in u:
                score += 3
            return score

        sorted_urls = sorted(urls, key=_priority, reverse=True)
        return sorted_urls[0]

    # ================================================================
    # 下载视频文件
    # ================================================================

    async def _download_video(self, url: str, out_path: Path) -> bool:
        """下载视频到本地，带进度提示"""
        if out_path.exists():
            logger.info(f"文件已存在: {out_path}")
            return True

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
            "Referer": "https://www.douyin.com/",
            "Accept": "*/*",
            "Accept-Encoding": "identity",  # 不要压缩，方便看进度
            "Connection": "keep-alive",
        }

        logger.info(f"开始下载: {out_path.name}")
        try:
            if _HAS_CURL_CFFI_DOUYIN and getattr(config, 'USE_CURL_CFFI', True):
                client = _curl_cffi.requests.AsyncSession(
                    impersonate=getattr(config, 'IMPERSONATE_TARGET', 'chrome124'),
                    timeout=120,
                )
            else:
                client = httpx.AsyncClient(follow_redirects=True, timeout=120)
            async with client:
                async with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code not in (200, 206):
                        logger.error(f"下载失败 HTTP {resp.status_code}")
                        return False

                    total = int(resp.headers.get("content-length", 0))
                    downloaded = 0

                    with open(out_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(1024 * 1024):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                pct = downloaded / total * 100
                                mb = downloaded / 1024 / 1024
                                total_mb = total / 1024 / 1024
                                print(f"\r  下载进度: {mb:.1f}/{total_mb:.1f} MB ({pct:.0f}%)", end="")

            size_mb = out_path.stat().st_size / 1024 / 1024
            print(f"\r  下载完成: {size_mb:.1f} MB → {out_path}")
            return True
        except Exception as e:
            logger.error(f"下载异常: {e}")
            return False

    # ================================================================
    # 工具
    # ================================================================

    def _extract_id(self, url_or_id: str) -> str:
        """从 URL 或 id 字符串中提取纯视频 ID"""
        # 直接是 ID
        if url_or_id.isdigit() and len(url_or_id) >= 15:
            return url_or_id
        # 从 URL 中提取
        m = DOUYIN_VIDEO_URL.search(url_or_id)
        if m:
            return m.group(1)
        m = VIDEO_ID_PATTERN.search(url_or_id)
        if m:
            return m.group(1)
        raise ValueError(f"无法从 '{url_or_id}' 中提取视频 ID")


# ================================================================
# CLI
# ================================================================

async def main():
    if len(sys.argv) < 2:
        print("用法: python douyin_dl.py <视频URL或视频ID>")
        print("示例: python douyin_dl.py 7640469163852533027")
        print("示例: python douyin_dl.py https://www.douyin.com/video/7640469163852533027")
        sys.exit(1)

    downloader = DouyinDownloader()
    result = await downloader.download(sys.argv[1])
    if result:
        print(f"\n成功: {result.absolute()}")
    else:
        print("\n失败: 未能下载视频。可能原因:")
        print("  1. 视频需要登录才能观看")
        print("  2. 抖音反爬机制升级")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
