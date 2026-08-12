"""网关防御 Admin-API 客户端

封装对网关管理后台（admin-api）的 HTTP 调用，包含以下接口：

- ``GET  /v2/sites``                          站点列表（裸分页体）
- ``POST /v2/sites``                          创建站点（SuccessResponse 包裹）
- ``GET  /v2/rules``                          规则列表（SuccessResponse 包裹）
- ``POST /v2/rules/bind-to-site/{site_id}``   绑定规则（SuccessResponse 包裹）

认证统一使用 ``Authorization: Bearer <fy_...>``。各端点返回外层结构不一致，
这里统一归一化后再返回业务数据，并做错误归一化与日志脱敏（不打印 API Key）。
"""

import json
import logging
from typing import Any, Optional

import httpx

from app.settings.config import settings

_log = logging.getLogger(__name__)

_TIMEOUT = 15.0


class GatewayAdminError(RuntimeError):
    """网关 admin-api 调用失败。"""


class GatewayAdminClient:
    """网关 admin-api 客户端。"""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or settings.GATEWAY_ADMIN_BASE_URL).rstrip('/')
        self.api_key = api_key or settings.GATEWAY_ADMIN_API_KEY

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        payload: Optional[dict] = None,
    ) -> dict[str, Any]:
        if not self.base_url:
            raise GatewayAdminError("GATEWAY_ADMIN_BASE_URL 未配置")
        if not self.api_key:
            raise GatewayAdminError("GATEWAY_ADMIN_API_KEY 未配置")

        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                resp = await client.request(
                    method, url, params=params, json=payload, headers=self._headers()
                )
            except httpx.HTTPError as exc:
                _log.error("网关 admin-api 请求异常 %s %s: %s", method, path, exc)
                raise GatewayAdminError(f"网关 admin-api 请求异常: {exc}") from exc

        body = self._body(resp)
        if resp.is_error:
            _log.error(
                "网关 admin-api 返回错误 %s %s -> HTTP %s: %s",
                method, path, resp.status_code, json.dumps(body, ensure_ascii=False),
            )
            raise GatewayAdminError(
                f"{method} {path} -> HTTP {resp.status_code}: "
                f"{json.dumps(body, ensure_ascii=False)}"
            )
        return body

    @staticmethod
    def _body(resp: httpx.Response) -> dict[str, Any]:
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    @staticmethod
    def _unwrap(body: dict[str, Any]) -> dict[str, Any]:
        """SuccessResponse 包裹体：{code, message, request_id, data} -> data。"""
        code = body.get("code")
        if code is not None and code not in (0, 200):
            raise GatewayAdminError(
                f"网关接口返回业务错误: code={code} message={body.get('message')}"
            )
        return body.get("data") or {}

    # ── 站点 ──
    async def list_sites(self, app_id: int, keyword: str = "") -> list[dict[str, Any]]:
        """站点列表（GET /v2/sites 直接返回裸分页体，无 SuccessResponse 包裹）。"""
        params: dict[str, Any] = {"page": 1, "pageSize": 100}
        if app_id:
            params["appId"] = app_id
        if keyword:
            params["keyword"] = keyword
        body = await self._request("GET", "/v2/sites", params=params)
        return body.get("items") or []

    async def create_site(
        self,
        app_id: int,
        name: str,
        domain: str,
        *,
        access_mode: str = "sdk",
        remark: Optional[str] = None,
    ) -> dict[str, Any]:
        """创建站点（POST /v2/sites），返回 SiteDetailResponse（含 site_secret）。"""
        payload: dict[str, Any] = {
            "app_id": app_id,
            "name": name,
            "domain": domain,
            "alt_domains": [],
            "access_mode": access_mode,
            "sdk_version": None,
            "gateway_url": None,
            "clock_stats_enabled": True,
            "log_retention_days": 30,
            "remark": remark or "由站点管理批量创建",
        }
        body = await self._request("POST", "/v2/sites", payload=payload)
        return self._unwrap(body)

    # ── 规则 ──
    async def list_rules(
        self,
        keyword: str = "",
        status: str = "published",
        page: int = 1,
        page_size: int = 200,
    ) -> tuple[list[dict[str, Any]], int]:
        """规则列表（GET /v2/rules），返回 (items, total)。"""
        params: dict[str, Any] = {"page": page, "pageSize": page_size}
        if keyword:
            params["keyword"] = keyword
        if status:
            params["status"] = status
        body = await self._request("GET", "/v2/rules", params=params)
        data = self._unwrap(body)
        return data.get("items") or [], data.get("total") or 0

    async def bind_rules(self, site_id: int, rule_ids: list[int]) -> dict[str, Any]:
        """绑定规则（POST /v2/rules/bind-to-site/{site_id}），返回 {bound, conflicts}。"""
        body = await self._request(
            "POST", f"/v2/rules/bind-to-site/{site_id}", payload={"rule_ids": rule_ids}
        )
        return self._unwrap(body)
