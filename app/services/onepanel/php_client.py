"""
PHP 站点 HTTP 客户端 —— 统一请求封装

职责:
  - 超时控制
  - 5xx / 连接超时 / 网络错误 → 指数退避重试（最多 3 次）
  - 4xx / 业务失败 → 不重试，立即抛异常
  - JSON 解析容错
  - 日志脱敏

使用示例:
    from app.services.onepanel.php_client import PHPClient

    client = PHPClient(verify_ssl=True)
    data = client.fetch_json(
        url="https://example.com/script.php?token=xxx",
        success_check=lambda d: d.get("code") == 200,
        retries=3,
    )
"""

import logging
import time
from typing import Any, Callable, Optional

import httpx

_log = logging.getLogger(__name__)


# ── 异常层级 ──

class PHPClientError(Exception):
    """PHP 客户端基础异常"""

    def __init__(self, message: str, *, url: str = "", step: str = ""):
        self.url = url
        self.step = step
        super().__init__(message)


class PHPClientServerError(PHPClientError):
    """HTTP 5xx → 可重试"""


class PHPClientNetworkError(PHPClientError):
    """连接超时 / 网络错误 / DNS 失败 → 可重试"""


class PHPClientResponseError(PHPClientError):
    """4xx / 非 JSON 响应 / 业务返回 failure → 不重试"""


# ── 重试策略 ──

RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
)

DEFAULT_TIMEOUT = 20.0
DEFAULT_MAX_RETRIES = 3


def _mask_token(url: str) -> str:
    """脱敏 URL 中的 token 参数"""
    import re
    return re.sub(r'(token=)[^&\s]+', r'\1***', url)


# ── 客户端类 ──

class PHPClient:
    """PHP 站点 HTTP 请求客户端，封装重试、错误处理和日志脱敏。"""

    def __init__(self, verify_ssl: bool = True, default_timeout: float = DEFAULT_TIMEOUT):
        self.verify_ssl = verify_ssl
        self.default_timeout = default_timeout
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.default_timeout,
                verify=self.verify_ssl,
                follow_redirects=True,
            )
        return self._client

    def close(self):
        if self._client:
            self._client.close()
            self._client = None

    # ── 核心方法：单次请求（含解析 + 错误分类）──

    def _request_once(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """执行单次 HTTP 请求，网络错误和 5xx 向上抛可重试异常"""
        try:
            resp = self.client.request(method=method, url=url, **kwargs)
        except RETRYABLE_EXCEPTIONS as e:
            raise PHPClientNetworkError(
                f"网络错误: {e}", url=_mask_token(url)
            ) from e
        except Exception as e:
            raise PHPClientNetworkError(
                f"请求异常: {e}", url=_mask_token(url)
            ) from e

        if resp.status_code in RETRYABLE_STATUS_CODES:
            body_snippet = (resp.text or "")[:200]
            raise PHPClientServerError(
                f"HTTP {resp.status_code}: {body_snippet}", url=_mask_token(url)
            )

        return resp

    # ── 低层方法：带重试的原始 HTTP 请求（不解析 JSON）──

    def raw_request(
        self,
        method: str,
        url: str,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> httpx.Response:
        """带重试的原始 HTTP 请求，返回 Response 对象。

        仅对 5xx / 网络错误重试，4xx 和业务成功均直接返回 Response。
        调用方自行判断 status_code / body。
        """
        if timeout is not None:
            kwargs["timeout"] = timeout

        last_exc: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                resp = self._request_once(method, url, **kwargs)
                return resp
            except PHPClientResponseError:
                raise
            except (PHPClientServerError, PHPClientNetworkError) as e:
                last_exc = e
                if attempt >= max_retries:
                    break
                backoff = 2 ** (attempt - 1)
                _log.debug(
                    "[php_client] raw_request %s，%ds 后重试 (第 %s/%s 次)",
                    e, backoff, attempt + 1, max_retries,
                )
                time.sleep(backoff)

        raise PHPClientNetworkError(
            f"raw_request 失败（已重试 {max_retries} 次）: {last_exc}",
            url=_mask_token(url),
        )

    # ── 核心方法：带重试的 JSON 获取 ──

    def fetch_json(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Optional[dict[str, str]] = None,
        json_body: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        success_check: Optional[Callable[[dict[str, Any]], bool]] = None,
        step: str = "",
    ) -> dict[str, Any]:
        """带重试的 JSON API 调用。

        Args:
            url: 请求地址
            method: HTTP 方法
            success_check: 可选的成功判断函数，返回 True 表示业务成功。
                           默认仅检查 JSON 是否为 dict。
            step: 流程标识（用于错误上下文字段）
            max_retries: 最大重试次数（仅对可重试异常生效）

        Returns:
            解析后的 JSON dict

        Raises:
            PHPClientResponseError: 4xx / 非 JSON / 业务失败
            PHPClientError: 重试耗尽后的网络/服务端错误
        """
        kwargs: dict[str, Any] = {}
        if headers:
            kwargs["headers"] = headers
        if json_body is not None:
            kwargs["json"] = json_body
        if data is not None:
            kwargs["data"] = data
        if timeout is not None:
            kwargs["timeout"] = timeout

        last_exc: Optional[PHPClientError] = None

        for attempt in range(1, max_retries + 1):
            try:
                resp = self._request_once(method, url, **kwargs)

                # ── 状态码分类 ──
                if resp.is_client_error:
                    raise PHPClientResponseError(
                        f"HTTP {resp.status_code}", url=_mask_token(url), step=step
                    )

                # ── JSON 解析 ──
                try:
                    payload = resp.json()
                except Exception as e:
                    body = (resp.text or "")[:500]
                    raise PHPClientResponseError(
                        f"非 JSON 响应: {body}", url=_mask_token(url), step=step
                    ) from e

                if not isinstance(payload, dict):
                    raise PHPClientResponseError(
                        f"响应不是 JSON 对象: {type(payload).__name__}",
                        url=_mask_token(url), step=step,
                    )

                # ── 业务成功检查 ──
                if success_check is not None:
                    if not success_check(payload):
                        raise PHPClientResponseError(
                            f"业务返回失败: {payload.get('msg', payload.get('message', str(payload)[:200]))}",
                            url=_mask_token(url), step=step,
                        )
                else:
                    # 默认：success: false 视为失败
                    if payload.get("success") is False:
                        raise PHPClientResponseError(
                            f"业务返回失败: {payload.get('message', payload.get('msg', ''))}",
                            url=_mask_token(url), step=step,
                        )

                return payload

            except PHPClientResponseError:
                # 4xx / 业务失败不重试，直接上抛
                raise

            except (PHPClientServerError, PHPClientNetworkError) as e:
                last_exc = e
                if attempt >= max_retries:
                    break
                backoff = 2 ** (attempt - 1)  # 1s → 2s → 4s
                _log.warning(
                    "[php_client] %s，%ds 后重试 (第 %s/%s 次)",
                    e, backoff, attempt + 1, max_retries,
                )
                time.sleep(backoff)

        raise PHPClientError(
            f"请求失败（已重试 {max_retries} 次）: {last_exc}",
            url=_mask_token(url), step=step,
        )

    # ── 便捷方法：HTTPS→HTTP 兜底请求 ──

    def fetch_with_fallback(
        self,
        domain: str,
        path: str,
        *,
        method: str = "GET",
        max_retries: int = DEFAULT_MAX_RETRIES,
        success_check: Optional[Callable[[dict[str, Any]], bool]] = None,
        https_first: bool = True,
        step: str = "",
        **kwargs,
    ) -> dict[str, Any]:
        """按 https → http 顺序尝试请求。

        Args:
            domain: 域名（不含协议）
            path: 路径（如 'script.php?token=xxx'）
            https_first: 是否优先 HTTPS（默认 True）
        """
        protocols = ["https", "http"] if https_first else ["http", "https"]

        for proto in protocols:
            url = f"{proto}://{domain}/{path.lstrip('/')}"
            try:
                verify = self.verify_ssl if proto == "https" else False
                # 临时覆盖 SSL 验证
                saved_verify = self.verify_ssl
                self.verify_ssl = verify

                result = self.fetch_json(
                    url, method=method, max_retries=max_retries,
                    success_check=success_check, step=step, **kwargs,
                )
                self.verify_ssl = saved_verify
                return result

            except PHPClientResponseError:
                # 4xx / 业务失败不尝试另一个协议
                self.verify_ssl = saved_verify
                raise

            except PHPClientError:
                self.verify_ssl = saved_verify
                _log.debug("[php_client] %s 失败，尝试下一个协议", proto)

        raise PHPClientNetworkError(
            f"所有协议均失败: {_mask_token(path)}", step=step,
        )
