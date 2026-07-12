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

from app.utils.config_reader import get_config

logger = logging.getLogger(__name__)


class DynadotService:
    """Dynadot JSON API 客户端（api3.json）"""

    def __init__(self):
        self.api_key = get_config("DYNADOT_API_KEY")
        self.base_url = get_config("DYNADOT_API_URL") or "https://api.dynadot.com/api3.json"
        self.timeout_val = int(get_config("DYNADOT_TIMEOUT") or "30")
        self.timeout = httpx.Timeout(self.timeout_val)

    def _call(self, command: str, **params) -> Dict[str, Any]:
        """调用 Dynadot JSON API"""
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

    def set_ns_and_wait(self, domain: str, ns_list: List[str], wait_sec: int = 10) -> Dict[str, Any]:
        """修改 NS 并等待（简单延迟）"""
        result = self.set_nameserver(domain, ns_list)
        if result.get("success"):
            time.sleep(wait_sec)
        return result
