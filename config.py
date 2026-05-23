"""
统一配置中心 —— 所有可调参数收拢在这里
"""
import os
from pathlib import Path

# ============================================================
# 项目路径
# ============================================================
ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
(ROOT_DIR / "logs").mkdir(exist_ok=True)

# ============================================================
# 爬虫通用配置
# ============================================================
DEFAULT_DELAY = 1.5              # 请求间隔（秒）
DEFAULT_TIMEOUT = 20              # 请求超时（秒）
MAX_RETRIES = 3                   # 最大重试次数
MAX_CONCURRENT = 10               # 异步并发数
MAX_PAGES = 0                     # 最大翻页数（0=不限制）
USER_AGENT_ROTATION = True        # 是否启用 UA 轮换

# ============================================================
# TLS 指纹反检测 (curl_cffi)
# ============================================================
# 模拟目标浏览器。curl_cffi 可用时生效。
# 可选值: "chrome124", "chrome123", "chrome120", "firefox125", "safari17_0", "edge124"
IMPERSONATE_TARGET = "chrome124"
USE_CURL_CFFI = True              # 是否优先使用 curl_cffi（False 则只用 httpx）

# ============================================================
# HTTP 请求头
# ============================================================
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
}

# ============================================================
# 代理池 (留空则直连, 填入则随机选取)
# ============================================================
PROXY_LIST = [
    # "http://127.0.0.1:7890",    # 本地代理
    # "http://user:pass@host:port",
]

# ============================================================
# 视频下载配置
# ============================================================
VIDEO_DIR = DATA_DIR / "videos"
VIDEO_CHUNK_SIZE = 1024 * 1024    # 分片下载块大小 (1MB)
VIDEO_MAX_WORKERS = 8             # ts 分片并发下载数
FFMPEG_PATH = "ffmpeg"            # ffmpeg 路径（需在 PATH 中）

# ============================================================
# 存储配置
# ============================================================
DB_PATH = DATA_DIR / "db" / "crawler.db"
JSON_DIR = DATA_DIR / "json"
CSV_DIR = DATA_DIR / "csv"
JSON_DIR.mkdir(exist_ok=True)
CSV_DIR.mkdir(exist_ok=True)

# ============================================================
# 断点续爬
# ============================================================
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
CHECKPOINT_INTERVAL = 3            # 每隔 N 页保存一次检查点
CHECKPOINT_ENABLED = True          # 是否启用断点续爬

# ============================================================
# 自适应元素重定位
# ============================================================
ADAPTIVE_FINGERPRINT_DIR = DATA_DIR / "fingerprints"
ADAPTIVE_ENABLED = True            # 是否启用自适应重定位
ADAPTIVE_SIMILARITY_THRESHOLD = 0.6  # 文本相似度阈值 (0-1)

# ============================================================
# 日志
# ============================================================
LOG_LEVEL = "INFO"
LOG_FILE = ROOT_DIR / "logs" / "crawler.log"
LOG_ROTATION = "10 MB"
