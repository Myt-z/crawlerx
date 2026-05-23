"""
视频爬虫 —— 支持 m3u8 流媒体、直链视频下载，自动合并 ts 分片
"""
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional

import m3u8
from loguru import logger

import config
from .base import BaseCrawler


class VideoCrawler(BaseCrawler):
    """
    视频爬虫，支持：
    - m3u8 流媒体解析 + ts 分片并发下载 + ffmpeg 合并
    - 直链 mp4/webm 下载（断点续传）
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.video_dir = Path(config.VIDEO_DIR)
        self.video_dir.mkdir(parents=True, exist_ok=True)

    # ================================================================
    # m3u8 流媒体
    # ================================================================

    async def download_m3u8(
        self,
        m3u8_url: str,
        filename: str = None,
        headers: dict = None,
    ) -> Optional[Path]:
        """
        下载 m3u8 视频的完整流程：
        1. 解析 m3u8 → 获取 ts 分片列表
        2. 并发下载所有 ts 分片到临时目录
        3. ffmpeg 合并为 mp4
        4. 清理临时文件

        返回最终 mp4 文件路径，失败返回 None
        """
        if filename is None:
            filename = self._auto_name(m3u8_url)
        if not filename.endswith(".mp4"):
            filename += ".mp4"

        out_path = self.video_dir / filename
        if out_path.exists():
            logger.info(f"[跳过] 视频已存在: {out_path}")
            return out_path

        # Step 1: 解析 m3u8
        logger.info(f"[m3u8] 解析播放列表: {m3u8_url}")
        playlist = await self._parse_m3u8(m3u8_url, headers)
        if playlist is None:
            return None

        segments = playlist.get("segments", [])
        if not segments:
            # 可能是主播放列表，需要选最高画质
            best_uri = self._select_best_stream(playlist)
            if best_uri:
                resolved = self._resolve_url(m3u8_url, best_uri)
                logger.info(f"[m3u8] 选择最高画质: {resolved}")
                playlist = await self._parse_m3u8(resolved, headers)
                segments = playlist.get("segments", []) if playlist else []

        if not segments:
            logger.error("[m3u8] 未找到任何 ts 分片")
            return None

        logger.info(f"[m3u8] 共 {len(segments)} 个 ts 分片")

        # Step 2: 下载 ts 分片
        tmp_dir = self.video_dir / f".tmp_{filename}"
        # 清理上次中断可能遗留的临时目录
        if tmp_dir.exists():
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(exist_ok=True)

        success = await self._download_segments(segments, m3u8_url, tmp_dir, headers)
        if not success:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

        # Step 3: ffmpeg 合并
        logger.info(f"[ffmpeg] 合并 ts 分片 → {out_path}")
        try:
            merged = await self._merge_ts(tmp_dir, out_path)
            return out_path if merged else None
        finally:
            # Step 4: 清理临时目录（无论成功失败都清理）
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def _parse_m3u8(self, url: str, extra_headers: dict = None) -> Optional[dict]:
        """下载并解析 m3u8 播放列表"""
        h = self._build_headers()
        if extra_headers:
            h.update(extra_headers)

        try:
            client = await self._get_httpx_client()
            resp = await client.get(url, headers=h, timeout=self.timeout)
            resp.raise_for_status()
            playlist = m3u8.loads(resp.text, uri=url)
            return playlist.data
        except Exception as e:
            logger.error(f"[m3u8] 解析失败: {e}")
            return None

    def _select_best_stream(self, playlist: dict) -> Optional[str]:
        """从主播放列表中选择最高码率流"""
        playlists = playlist.get("playlists", [])
        if not playlists:
            return None
        best = max(playlists, key=lambda p: p.get("stream_info", {}).get("bandwidth", 0))
        return best.get("uri")

    def _resolve_url(self, base: str, target: str) -> str:
        """将相对 URI 转为绝对 URL"""
        if target.startswith(("http://", "https://")):
            return target
        if target.startswith("//"):
            return "https:" + target
        import urllib.parse
        return urllib.parse.urljoin(base, target)

    async def _download_segments(
        self, segments: list, base_url: str, tmp_dir: Path, extra_headers: dict = None
    ) -> bool:
        """并发下载所有 ts 分片到临时目录"""
        # 去重：按 URI 消除重复分片
        seen_uris = set()
        unique_segments = []
        for seg in segments:
            uri = seg.get("uri", "")
            resolved = self._resolve_url(base_url, uri)
            if resolved not in seen_uris:
                seen_uris.add(resolved)
                unique_segments.append(seg)
        if len(unique_segments) < len(segments):
            logger.info(f"[ts] 去重: {len(segments)} -> {len(unique_segments)} 个分片")
        segments = unique_segments

        sem = asyncio.Semaphore(config.VIDEO_MAX_WORKERS)
        failed = []

        async def _download_one(idx: int, seg: dict):
            async with sem:
                uri = seg.get("uri", "")
                seg_url = self._resolve_url(base_url, uri)
                seg_path = tmp_dir / f"{idx:06d}.ts"

                # 断点续传：跳过已下载的分片
                if seg_path.exists() and seg_path.stat().st_size > 0:
                    return

                for retry in range(3):
                    try:
                        client = await self._get_httpx_client()
                        h = self._build_headers()
                        if extra_headers:
                            h.update(extra_headers)
                        resp = await client.get(seg_url, headers=h, timeout=self.timeout * 2)
                        resp.raise_for_status()
                        seg_path.write_bytes(resp.content)
                        return
                    except Exception as e:
                        if retry == 2:
                            failed.append(idx)
                            logger.error(f"[ts] 下载失败 #{idx}: {e}")
                        else:
                            await asyncio.sleep(1)

        tasks = [_download_one(i, seg) for i, seg in enumerate(segments)]
        await asyncio.gather(*tasks)

        if failed:
            logger.error(f"[ts] 失败 {len(failed)}/{len(segments)} 个分片")
            return False
        return True

    async def _merge_ts(self, tmp_dir: Path, out_path: Path) -> bool:
        """用 ffmpeg concat 合并 ts 分片 → mp4"""
        file_list = tmp_dir / "filelist.txt"
        ts_files = sorted(tmp_dir.glob("*.ts"))
        file_list.write_text(
            "\n".join(f"file '{f.absolute().as_posix()}'" for f in ts_files),
            encoding="utf-8",
        )

        cmd = [
            config.FFMPEG_PATH, "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(file_list.absolute()),
            "-c", "copy",
            str(out_path.absolute()),
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"[ffmpeg] 合并失败: {stderr.decode(errors='ignore')[:500]}")
                return False
            return True
        except FileNotFoundError:
            logger.error("[ffmpeg] 未找到 ffmpeg，请将其添加到 PATH 或设置 config.FFMPEG_PATH")
            return False
        except Exception as e:
            logger.error(f"[ffmpeg] 异常: {e}")
            return False

    # ================================================================
    # 直链视频下载
    # ================================================================

    async def download_direct(
        self, url: str, filename: str = None
    ) -> Optional[Path]:
        """
        下载直链视频（mp4/webm/mov 等），支持断点续传。
        """
        if filename is None:
            filename = self._auto_name(url)
        out_path = self.video_dir / filename
        success = await self.download_file(url, out_path)
        return out_path if success else None

    # ================================================================
    # 从网页中提取视频链接
    # ================================================================

    async def extract_video_urls(self, page_url: str) -> list[str]:
        """
        从网页中提取视频 URL（<video> 标签、m3u8 链接等）。
        """
        from parsers.html_parser import HTMLParser
        html = await self.fetch(str(page_url))
        if html is None:
            return []

        parser = HTMLParser()
        urls = []

        # <video> 标签的 src 属性
        srcs = parser.extract_list(html, "video[src]", "src")
        urls.extend(srcs)

        # <source> 标签
        srcs = parser.extract_list(html, "video source[src]", "src")
        urls.extend(srcs)

        # <script> 中嵌入的 m3u8 链接
        pattern = r'https?://[^"\'\\s<>]+\.m3u8[^"\'\\s<>]*'
        matches = re.findall(pattern, html)
        urls.extend(matches)

        # <iframe> 中的视频
        iframes = parser.extract_list(html, "iframe[src]", "src")
        for src in iframes:
            if "youtube.com" in src or "bilibili.com" in src:
                logger.info(f"[iframe] 发现第三方视频: {src}")
        urls.extend(iframes)

        # 去重
        seen = set()
        unique = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        return unique

    # ================================================================
    # 工具方法
    # ================================================================

    def _auto_name(self, url: str) -> str:
        """根据 URL 自动生成文件名"""
        # 取其 MD5 前 12 位 + 从 URL 推断的扩展名
        hash_part = hashlib.md5(url.encode()).hexdigest()[:12]
        if ".m3u8" in url:
            return f"{hash_part}.mp4"
        if ".mp4" in url:
            return f"{hash_part}.mp4"
        if ".webm" in url:
            return f"{hash_part}.webm"
        if ".flv" in url:
            return f"{hash_part}.flv"
        return f"{hash_part}.mp4"
