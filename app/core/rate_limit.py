"""分布式限流中间件 —— Redis 优先，内存回退。

配置:
    REDIS_URL=redis://localhost:6379/0   # 启用 Redis 分布式限流
    REDIS_URL=""                          # 留空则使用内存限流（单实例）
"""

import time
from collections import defaultdict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.settings import settings


class MemoryRateLimiter:
    """基于客户端 IP 的内存滑动窗口限流（单实例场景）"""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients: dict[str, list[float]] = defaultdict(list)

    async def is_rate_limited(self, client_ip: str) -> bool:
        now = time.time()
        window_start = now - self.window_seconds
        # 清理过期记录
        self._clients[client_ip] = [t for t in self._clients[client_ip] if t > window_start]
        if len(self._clients[client_ip]) >= self.max_requests:
            return True
        self._clients[client_ip].append(now)
        return False


class RedisRateLimiter:
    """基于 Redis 的分布式滑动窗口限流"""

    _LUA_SCRIPT = """
    local key = KEYS[1]
    local max_requests = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])
    local window_start = now - window

    redis.call('ZREMRANGEBYSCORE', key, 0, window_start)
    local count = redis.call('ZCARD', key)
    if count >= max_requests then
        return 1
    end
    redis.call('ZADD', key, now, now .. '-' .. count)
    redis.call('EXPIRE', key, math.ceil(window))
    return 0
    """

    def __init__(self, redis_url: str, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._redis = None
        self._redis_url = redis_url
        self._script_sha = None

    async def _ensure_redis(self):
        if self._redis is not None:
            return
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            self._script_sha = await self._redis.script_load(self._LUA_SCRIPT)
        except Exception:
            self._redis = False  # 标记为不可用，后续回退到 None 检查

    async def is_rate_limited(self, client_ip: str) -> bool:
        await self._ensure_redis()
        if not self._redis:
            return False  # Redis 不可用时放行，由上层回退到内存模式

        try:
            key = f"rate_limit:{client_ip}"
            now = time.time()
            result = await self._redis.evalsha(
                self._script_sha, 1, key,
                str(self.max_requests), str(self.window_seconds), str(now),
            )
            return result == 1
        except Exception:
            return False  # Redis 异常时放行


class RateLimitMiddleware(BaseHTTPMiddleware):
    """分布式限流中间件 —— Redis 优先，内存回退。

    自动检测 REDIS_URL 配置：
    - 有值：启用 Redis 分布式限流（多 worker / 多实例共享）
    - 空值：回退到内存限流（单 worker 模式）
    """

    def __init__(self, app):
        super().__init__(app)
        self.max_requests = settings.RATE_LIMIT_MAX_REQUESTS
        self.window_seconds = settings.RATE_LIMIT_WINDOW_SECONDS

        if settings.REDIS_URL:
            self._redis_limiter = RedisRateLimiter(
                settings.REDIS_URL, self.max_requests, self.window_seconds
            )
        else:
            self._redis_limiter = None

        # 内存回退始终可用
        self._memory_limiter = MemoryRateLimiter(self.max_requests, self.window_seconds)

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"

        limited = False
        if self._redis_limiter:
            limited = await self._redis_limiter.is_rate_limited(client_ip)

        if not self._redis_limiter or limited:
            # Redis 未配置，或 Redis 返回限流 → 内存兜底验证
            limited = await self._memory_limiter.is_rate_limited(client_ip)

        if limited:
            return JSONResponse(
                status_code=429,
                content={
                    "code": 429,
                    "msg": f"请求过于频繁，请 {self.window_seconds} 秒后重试",
                    "data": None,
                },
            )

        return await call_next(request)
