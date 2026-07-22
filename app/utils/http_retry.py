"""
轻量级 HTTP 重试工具。

用法：
    from app.utils.http_retry import retry_request

    ok, data = retry_request(
        lambda: httpx.get(url, timeout=30),
        max_retries=3,
    )

或用于装饰原生 HTTP 调用，统一处理超时 / 5xx 自动重试 / 降级。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, TypeVar

import httpx

from app.log import logger

T = TypeVar("T")

_RETRYABLE_STATUSES = {429, 502, 503, 504}
_DEGRADE_STATUSES = {401, 403, 404}


def _is_retryable(err: Exception) -> bool:
    """判断异常是否可重试（网络层超时/连接错误）。"""
    if isinstance(err, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError)):
        return True
    if isinstance(err, OSError):
        return True
    return False


def retry_request(
    fn: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    context: str = "",
) -> T:
    """同步版：执行 fn，5xx/429/网络错误自动重试（指数退避）。

    fn: 无参 Callable，返回结果或抛异常。
    max_retries: 最大重试次数（含首次，共 max_retries 次尝试）。
    base_delay: 首次重试等待秒数，后续指数递增。
    context: 日志标识。
    """
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            result = fn()
            # 如果是 httpx.Response，检查状态码
            if isinstance(result, httpx.Response):
                status = result.status_code
                if status < 400:
                    return result
                if status in _DEGRADE_STATUSES:
                    logger.warning(
                        "[http_retry] %s 第 %d 次请求返回 %d（不可重试），直接降级",
                        context, attempt, status,
                    )
                    raise RuntimeError(f"HTTP {status}: non-retryable")
                if status in _RETRYABLE_STATUSES:
                    delay = base_delay * (2 ** (attempt - 1))
                    if status == 429:
                        retry_after = result.headers.get("Retry-After", "")
                        if retry_after and retry_after.isdigit():
                            delay = int(retry_after)
                        else:
                            # 无 Retry-After 头时，指数退避 5s/10s/20s
                            delay = 5 * (2 ** (attempt - 1))
                    logger.warning(
                        "[http_retry] %s 第 %d 次请求返回 %d，准备重试（等待 %.0f 秒）",
                        context, attempt, status, delay,
                    )
                    if attempt < max_retries:
                        time.sleep(delay)
                    continue
                # 其他 4xx 不重试
                raise RuntimeError(f"HTTP {status}")
            return result
        except RuntimeError:
            raise  # 不重试的错误直接抛
        except Exception as exc:
            if not _is_retryable(exc):
                raise
            last_err = exc
            logger.warning(
                "[http_retry] %s 第 %d/%d 次请求异常：%s",
                context, attempt, max_retries, exc,
            )
            if attempt < max_retries:
                time.sleep(base_delay * (2 ** (attempt - 1)))
    raise last_err or RuntimeError(f"[http_retry] {context} 重试耗尽")


async def retry_request_async(
    fn: Callable[[], Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    context: str = "",
) -> Any:
    """异步版 retry_request。"""
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            coro = fn()
            result = await coro if asyncio.iscoroutine(coro) else coro
            if isinstance(result, httpx.Response):
                status = result.status_code
                if status < 400:
                    return result
                if status in _DEGRADE_STATUSES:
                    logger.warning(
                        "[http_retry] %s 第 %d 次请求返回 %d（不可重试），直接降级",
                        context, attempt, status,
                    )
                    raise RuntimeError(f"HTTP {status}: non-retryable")
                if status in _RETRYABLE_STATUSES:
                    delay = base_delay * (2 ** (attempt - 1))
                    if status == 429:
                        retry_after = result.headers.get("Retry-After", "")
                        if retry_after and retry_after.isdigit():
                            delay = int(retry_after)
                        else:
                            delay = 5 * (2 ** (attempt - 1))
                    logger.warning(
                        "[http_retry] %s 第 %d 次请求返回 %d，准备重试（等待 %.0f 秒）",
                        context, attempt, status, delay,
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(delay)
                    continue
                raise RuntimeError(f"HTTP {status}")
            return result
        except RuntimeError:
            raise
        except Exception as exc:
            if not _is_retryable(exc):
                raise
            last_err = exc
            logger.warning(
                "[http_retry] %s 第 %d/%d 次请求异常：%s",
                context, attempt, max_retries, exc,
            )
            if attempt < max_retries:
                await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
    raise last_err or RuntimeError(f"[http_retry] {context} 重试耗尽")
