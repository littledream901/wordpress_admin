"""Dynadot 域名注册商 API 服务

职责：
- 修改域名 Nameserver（set_nameserver）
- 后续可扩展：域名信息查询、域名状态查询、到期时间查询

API 文档：https://www.dynadot.com/developers/api3.html
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from app.utils.provider_resolver import ProviderResolver
from app.utils.http_retry import retry_request

logger = logging.getLogger(__name__)


class DynadotService:
    """Dynadot JSON API 客户端（api3.json）— 配置延迟加载"""

    def __init__(self):
        self._config_loaded = False

    def _ensure_config(self):
        if self._config_loaded:
            return
        self.api_key = ProviderResolver.sync_get_config('dynadot', 'api_key', '')
        self.base_url = ProviderResolver.sync_get_config('dynadot', 'api_url', '') or "https://api.dynadot.com/api3.json"
        self.timeout_val = int(ProviderResolver.sync_get_config('dynadot', 'timeout', '') or "30")
        self.timeout = httpx.Timeout(self.timeout_val)
        self._config_loaded = True

    def _call(self, command: str, **params) -> Dict[str, Any]:
        """调用 Dynadot JSON API"""
        self._ensure_config()
        params["key"] = self.api_key
        params["command"] = command
        logger.debug("Dynadot 请求: command=%s domain=%s", command, params.get("domain", ""))
        try:
            resp = httpx.get(self.base_url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return self._parse_json_response(resp.json())
        except httpx.HTTPError as e:
            logger.error("Dynadot API 请求异常: %s", str(e))
            return {"success": False, "error": str(e), "response_code": "-1"}
        except json.JSONDecodeError as e:
            logger.error("Dynadot JSON 解析异常: %s", str(e))
            return {"success": False, "error": f"JSON parse error: {e}", "response_code": "-1"}

    def _parse_json_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """解析 Dynadot JSON API 响应

        响应格式（以 SetNs 为例）：
        {
            "SetNsResponse": {
                "ResponseCode": "0",
                "Status": "success"
            }
        }
        """
        result = {"success": False, "raw": json.dumps(data)[:500]}

        # 遍历可能的响应键（SetNsResponse / SearchResponse 等）
        for key, body in data.items():
            if isinstance(body, dict):
                code = body.get("ResponseCode", -1)
                status_text = body.get("Status", "")
                result["response_code"] = str(code)
                result["message"] = body.get("Error", "") or status_text
                result["success"] = (code == 0 or str(code) == "0") and status_text == "success"
                break

        if not result["success"]:
            result["error"] = result.get("message") or f"ResponseCode={result.get('response_code')}"

        return result

    def set_nameserver(self, domain: str, ns_list: List[str]) -> Dict[str, Any]:
        """修改域名的 Nameserver 记录

        Args:
            domain: 域名（如 example.com）
            ns_list: NS 服务器列表（通常 2 个）

        Returns:
            {'success': True/False, 'response_code': '0', ...}
        """
        params = {"domain": domain}
        for i, ns in enumerate(ns_list[:13]):  # Dynadot 最多支持 13 个 NS
            params[f"ns{i}"] = ns
        return self._call("set_ns", **params)

    def set_ns_and_wait(self, domain: str, ns_list: List[str], wait_sec: int = 60, interval: int = 5) -> Dict[str, Any]:
        """修改 NS 并通过 API 轮询验证生效。

        Args:
            domain: 域名
            ns_list: 目标 NS 服务器列表
            wait_sec: 最长等待秒数（默认 60s）
            interval: 轮询间隔（默认 5s）

        Returns:
            同 set_nameserver；若轮询超时，result 中附带 'ns_verified': False
        """
        result = self.set_nameserver(domain, ns_list)
        if not result.get("success"):
            return result

        # API 验证 NS 已生效（轮询，间隔 interval 秒，最多 wait_sec 秒）
        start = time.time()
        target_set = set(n.strip().rstrip('.') for n in ns_list)
        while time.time() - start < wait_sec:
            search_result = self._call("search", domain=domain)
            if search_result.get("success") and isinstance(search_result.get("raw"), str):
                # 尝试从 raw JSON 中提取当前 NS
                try:
                    raw_data = json.loads(search_result["raw"])
                    for _key, body in raw_data.items():
                        if isinstance(body, dict):
                            current_ns = body.get("NameServers") or body.get("NameServer") or ""
                            if current_ns:
                                current_set = set(str(n).strip().rstrip('.') for n in (
                                    current_ns if isinstance(current_ns, list) else current_ns.split(",")
                                ))
                                if current_set == target_set:
                                    result["ns_verified"] = True
                                    logger.info("Dynadot NS 已确认生效: domain=%s", domain)
                                    return result
                except Exception:
                    pass
            time.sleep(interval)

        logger.warning("Dynadot NS 验证超时（%ss），继续执行: domain=%s", wait_sec, domain)
        result["ns_verified"] = False
        return result
