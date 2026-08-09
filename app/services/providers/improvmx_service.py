"""ImprovMX 邮件转发服务

职责：
- 创建/更新/删除邮件转发别名
- 管理域名（添加、验证、删除）

API 文档：https://api.improvmx.com/v3
认证方式：HTTP Basic Auth，用户名 "api"，密码为 API Key
"""

import json
import logging
from typing import Any, Dict, Optional

import httpx

from app.utils.provider_resolver import ProviderResolver
from app.utils.http_retry import retry_request

logger = logging.getLogger(__name__)


class ImprovMxService:
    """ImprovMX API v3 客户端 — 配置延迟加载"""

    def __init__(self):
        self._config_loaded = False

    def _ensure_config(self):
        if self._config_loaded:
            return
        self.api_key = ProviderResolver.sync_get_config('improvmx', 'api_key', '')
        self.base_url = ProviderResolver.sync_get_config('improvmx', 'api_url', '') or "https://api.improvmx.com/v3"
        self.timeout_val = int(ProviderResolver.sync_get_config('improvmx', 'timeout', '') or "30")
        self.timeout = httpx.Timeout(self.timeout_val)
        self._config_loaded = True

    def _call(self, method: str, path: str, json_body: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict[str, Any]:
        """调用 ImprovMX API 并归一化响应"""
        self._ensure_config()
        url = f"{self.base_url}{path}"
        logger.debug("ImprovMX 请求: %s %s", method, path)

        def _req():
            return httpx.request(
                method=method,
                url=url,
                json=json_body,
                params=params,
                auth=("api", self.api_key),
                timeout=self.timeout,
            )

        try:
            resp = retry_request(_req, max_retries=3, context=f"ImprovMX {method} {path}")
            resp.raise_for_status()
            data = resp.json()
            if data.get("success"):
                # 合并业务字段（alias / domain / records / aliases ...）便于调用方直接取用
                return {**data, "success": True}
            else:
                errors = data.get("errors", {})
                error_msg = json.dumps(errors) if errors else data.get("error", "Unknown error")
                return {"success": False, "error": error_msg, "raw": json.dumps(data)[:500]}
        except httpx.HTTPStatusError as e:
            logger.error("ImprovMX HTTP 错误: %s", e)
            try:
                err_data = e.response.json()
                error_msg = json.dumps(err_data.get("errors", {})) or err_data.get("error", str(e))
            except Exception:
                error_msg = str(e)
            return {"success": False, "error": error_msg, "status_code": e.response.status_code}
        except Exception as e:
            logger.error("ImprovMX 请求异常: %s", str(e))
            return {"success": False, "error": str(e)}

    # ── 别名管理 ──

    def create_alias(self, domain: str, alias: str, forward: str) -> Dict[str, Any]:
        """创建邮件转发别名

        Args:
            domain: 域名（如 example.com）
            alias: 别名本地部分（如 admin）
            forward: 转发目标邮箱

        Returns:
            {'success': True/False, 'alias': {...}, ...}
        """
        return self._call("POST", f"/domains/{domain}/aliases", json_body={"alias": alias, "forward": forward})

    def update_alias(self, domain: str, alias: str, forward: str) -> Dict[str, Any]:
        """更新别名转发目标

        Args:
            domain: 域名
            alias: 别名（可以是字符串或 ID）
            forward: 新的转发目标

        Returns:
            {'success': True/False, 'alias': {...}, ...}
        """
        return self._call("PUT", f"/domains/{domain}/aliases/{alias}", json_body={"forward": forward})

    def get_alias(self, domain: str, alias: str) -> Dict[str, Any]:
        """获取单个别名

        Args:
            domain: 域名
            alias: 别名（可以是字符串或 ID）

        Returns:
            {'success': True/False, 'alias': {...}, ...}
        """
        return self._call("GET", f"/domains/{domain}/aliases/{alias}")

    def delete_alias(self, domain: str, alias: str) -> Dict[str, Any]:
        """删除别名

        Args:
            domain: 域名
            alias: 别名（可以是字符串或 ID）

        Returns:
            {'success': True/False, ...}
        """
        return self._call("DELETE", f"/domains/{domain}/aliases/{alias}")

    def list_aliases(self, domain: str, page: int = 1, limit: int = 100) -> Dict[str, Any]:
        """列出域名下所有别名

        Args:
            domain: 域名
            page: 页码（从 1 开始）
            limit: 每页数量（最大 100）

        Returns:
            {'success': True/False, 'aliases': [...], 'total': N, ...}
        """
        return self._call("GET", f"/domains/{domain}/aliases", params={"page": page, "limit": limit})

    # ── 域名管理 ──

    def add_domain(self, domain: str, notification_email: str = "") -> Dict[str, Any]:
        """添加域名到 ImprovMX

        Args:
            domain: 域名
            notification_email: 通知邮箱（可选）

        Returns:
            {'success': True/False, 'domain': {...}, ...}
        """
        body = {"domain": domain}
        if notification_email:
            body["notification_email"] = notification_email
        return self._call("POST", "/domains", json_body=body)

    def get_domain(self, domain: str) -> Dict[str, Any]:
        """获取域名详情

        Args:
            domain: 域名

        Returns:
            {'success': True/False, 'domain': {...}, ...}
        """
        return self._call("GET", f"/domains/{domain}")

    def check_domain(self, domain: str) -> Dict[str, Any]:
        """验证域名 DNS 配置（MX/SPF/DKIM/DMARC）

        Args:
            domain: 域名

        Returns:
            {'success': True/False, 'records': {...}, ...}
        """
        return self._call("GET", f"/domains/{domain}/check")

    def delete_domain(self, domain: str) -> Dict[str, Any]:
        """删除域名

        Args:
            domain: 域名

        Returns:
            {'success': True/False, ...}
        """
        return self._call("DELETE", f"/domains/{domain}")


improvmx_service = ImprovMxService()
