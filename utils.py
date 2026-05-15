"""
工具模块：缓存、限速、日志、重试
"""
import os
import time
import random
import logging
import functools
import hashlib
import json
import pickle
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import diskcache

from config import CACHE_DIR, CACHE_TTL, REQUEST_DELAY, MAX_RETRIES, USER_AGENTS

# ── 日志配置 ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("market_tracker.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("market_tracker")

# ── 磁盘缓存 ─────────────────────────────────────────────
_cache = diskcache.Cache(str(CACHE_DIR), size_limit=512 * 1024 * 1024)  # 512 MB

def cache_key(*args, **kwargs) -> str:
    """生成缓存key"""
    raw = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()

def cached(ttl: int = CACHE_TTL, prefix: str = ""):
    """磁盘缓存装饰器，支持TTL"""
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = f"{prefix}:{func.__name__}:{cache_key(*args, **kwargs)}"
            if key in _cache:
                logger.debug(f"缓存命中: {func.__name__}")
                return _cache[key]
            result = func(*args, **kwargs)
            if result is not None:
                _cache.set(key, result, expire=ttl)
            return result
        return wrapper
    return decorator

def clear_cache(prefix: str = ""):
    """清除指定前缀的缓存"""
    if prefix:
        for key in list(_cache):
            if str(key).startswith(prefix):
                del _cache[key]
    else:
        _cache.clear()
    logger.info(f"缓存已清除: prefix={prefix or '全部'}")

# ── 限速器 ───────────────────────────────────────────────
class RateLimiter:
    """令牌桶限速器"""
    def __init__(self, delay: float = REQUEST_DELAY, jitter: float = 0.5):
        self.delay = delay
        self.jitter = jitter
        self._last_call = 0.0

    def wait(self):
        now = time.time()
        elapsed = now - self._last_call
        wait_time = self.delay + random.uniform(0, self.jitter)
        if elapsed < wait_time:
            time.sleep(wait_time - elapsed)
        self._last_call = time.time()

_rate_limiter = RateLimiter()

def rate_limited(func: Callable):
    """限速装饰器"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        _rate_limiter.wait()
        return func(*args, **kwargs)
    return wrapper

# ── 重试装饰器 ────────────────────────────────────────────
def retry(max_retries: int = MAX_RETRIES, backoff: float = 2.0,
          exceptions=(Exception,)):
    """指数退避重试"""
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries - 1:
                        logger.error(f"{func.__name__} 失败 ({max_retries}次): {e}")
                        return None
                    wait = backoff ** attempt + random.uniform(0, 1)
                    logger.warning(f"{func.__name__} 第{attempt+1}次失败，{wait:.1f}s后重试: {e}")
                    time.sleep(wait)
        return wrapper
    return decorator

# ── 随机User-Agent ────────────────────────────────────────
def random_ua() -> str:
    return random.choice(USER_AGENTS)

# ── 日期工具 ─────────────────────────────────────────────
def last_n_trading_days(n: int) -> str:
    """返回n个自然日前的日期字符串 YYYYMMDD"""
    return (datetime.now() - timedelta(days=n)).strftime("%Y%m%d")

def format_pct(val: float, decimals: int = 2) -> str:
    """格式化百分比"""
    if val is None or (isinstance(val, float) and not val == val):
        return "/"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.{decimals}f}%"

def safe_float(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default

# ── 进度日志 ─────────────────────────────────────────────
class ProgressLogger:
    def __init__(self, total: int, desc: str = ""):
        self.total = total
        self.current = 0
        self.desc = desc
        logger.info(f"开始: {desc} (共{total}项)")

    def step(self, name: str = ""):
        self.current += 1
        pct = self.current / self.total * 100
        logger.info(f"[{self.current}/{self.total}] {pct:.0f}% — {name}")

    def done(self):
        logger.info(f"完成: {self.desc}")
