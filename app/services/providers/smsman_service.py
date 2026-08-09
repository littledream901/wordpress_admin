"""SMSMan 短信验证服务

职责：
- 获取虚拟手机号码（get-number）
- 轮询接收 SMS 验证码（get-sms）
- 设置号码状态（set-status）

API 文档：https://sms-man.com/api
认证方式：token 参数
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

import httpx

from app.utils.provider_resolver import ProviderResolver
from app.utils.http_retry import retry_request, retry_request_async

logger = logging.getLogger(__name__)


class SmsManService:
    """SMSMan API v2.0 客户端 — 配置延迟加载"""

    def __init__(self):
        self._config_loaded = False

    def _ensure_config(self):
        if self._config_loaded:
            return
        self.api_token = ProviderResolver.sync_get_config('smsman', 'api_token', '')
        self.base_url = ProviderResolver.sync_get_config('smsman', 'api_url', '') or "https://api.sms-man.com/control"
        self.timeout_val = int(ProviderResolver.sync_get_config('smsman', 'timeout', '') or "30")
        self.timeout = httpx.Timeout(self.timeout_val)
        self._config_loaded = True

    def _call(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """调用 SMSMan API 并归一化响应"""
        self._ensure_config()
        url = f"{self.base_url}/{endpoint}"
        params = params or {}
        params["token"] = self.api_token
        logger.debug("SMSMan 请求: %s params=%s", endpoint, {k: v for k, v in params.items() if k != 'token'})

        def _req():
            return httpx.get(url, params=params, timeout=self.timeout)

        try:
            resp = retry_request(_req, max_retries=3, context=f"SMSMan {endpoint}")
            resp.raise_for_status()
            data = resp.json()
            
            # SMSMan 成功响应不含 success 字段，失败响应含 error_code
            if "error_code" in data:
                error_msg = data.get("error_msg", data.get("error_code", "Unknown error"))
                logger.warning("SMSMan API 错误: %s", error_msg)
                return {"success": False, "error": error_msg, "error_code": data.get("error_code"), "raw": data}
            
            # 成功响应直接返回数据字段 + success 标记
            return {**data, "success": True}
        except httpx.HTTPStatusError as e:
            logger.error("SMSMan HTTP 错误: %s", e)
            try:
                err_data = e.response.json()
                error_msg = err_data.get("error_msg", str(e))
            except Exception:
                error_msg = str(e)
            return {"success": False, "error": error_msg, "status_code": e.response.status_code}
        except Exception as e:
            logger.error("SMSMan 请求异常: %s", str(e))
            return {"success": False, "error": str(e)}

    async def _call_async(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """异步版本"""
        self._ensure_config()
        url = f"{self.base_url}/{endpoint}"
        params = params or {}
        params["token"] = self.api_token
        logger.debug("SMSMan 异步请求: %s", endpoint)

        async def _req():
            async with httpx.AsyncClient() as client:
                return await client.get(url, params=params, timeout=self.timeout)

        try:
            resp = await retry_request_async(_req, max_retries=3, context=f"SMSMan {endpoint}")
            resp.raise_for_status()
            data = resp.json()
            
            if "error_code" in data:
                error_msg = data.get("error_msg", data.get("error_code", "Unknown error"))
                logger.warning("SMSMan API 错误: %s", error_msg)
                return {"success": False, "error": error_msg, "error_code": data.get("error_code"), "raw": data}
            
            return {**data, "success": True}
        except httpx.HTTPStatusError as e:
            logger.error("SMSMan HTTP 错误: %s", e)
            try:
                err_data = e.response.json()
                error_msg = err_data.get("error_msg", str(e))
            except Exception:
                error_msg = str(e)
            return {"success": False, "error": error_msg, "status_code": e.response.status_code}
        except Exception as e:
            logger.error("SMSMan 请求异常: %s", str(e))
            return {"success": False, "error": str(e)}

    # ── 获取号码 ──

    def get_number(
        self,
        country_id: Optional[int] = None,
        application_id: Optional[int] = None,
        max_price: Optional[int] = None,
    ) -> Dict[str, Any]:
        """请求一个虚拟手机号

        Args:
            country_id: 国家 ID（0=随机，1=俄罗斯，...）
            application_id: 服务 ID（2=Google，...）
            max_price: 最高价格（分）

        Returns:
            成功: {"success": True, "request_id": 123, "number": "79001234567", "country_id": 1, "application_id": 2}
            失败: {"success": False, "error": "...", "error_code": "no_numbers"}
        """
        params = {}
        if country_id is not None:
            params["country_id"] = country_id
        if application_id is not None:
            params["application_id"] = application_id
        if max_price is not None:
            params["maxPrice"] = max_price
        
        return self._call("get-number", params)

    # ── 获取 SMS ──

    def get_sms(self, request_id: int) -> Dict[str, Any]:
        """查询 SMS 验证码

        Args:
            request_id: get-number 返回的 request_id

        Returns:
            验证码已到: {"success": True, "request_id": 123, "number": "79001234567", "sms_code": "1234", ...}
            等待中: {"success": False, "error": "Still waiting...", "error_code": "wait_sms"}
        """
        return self._call("get-sms", {"request_id": request_id})

    async def get_sms_async(self, request_id: int) -> Dict[str, Any]:
        """异步版本 get-sms"""
        return await self._call_async("get-sms", {"request_id": request_id})

    # ── 设置状态 ──

    def set_status(self, request_id: int, status: str) -> Dict[str, Any]:
        """设置号码使用状态

        Args:
            request_id: get-number 返回的 request_id
            status: 状态值
                - ready: 准备接收短信
                - close: 关闭（取消，退款）
                - reject: 拒绝（无法接收短信）
                - used: 已使用（扣款确认）

        Returns:
            {"success": True, "request_id": 123}
        """
        return self._call("set-status", {"request_id": request_id, "status": status})

    # ── 轮询等待 SMS ──

    async def wait_for_sms_async(self, request_id: int, timeout: int = 300, interval: int = 10) -> Optional[str]:
        """异步轮询等待 SMS 验证码

        Args:
            request_id: get-number 返回的 request_id
            timeout: 最长等待秒数
            interval: 轮询间隔秒数

        Returns:
            验证码字符串，超时返回 None
        """
        start = time.time()
        logger.info("SMSMan 开始轮询 SMS: request_id=%s timeout=%ss", request_id, timeout)
        
        while time.time() - start < timeout:
            result = await self.get_sms_async(request_id)
            
            if result.get("success") and result.get("sms_code"):
                code = result["sms_code"]
                logger.info("SMSMan 收到验证码: request_id=%s code=%s", request_id, code)
                return code
            
            # error_code=wait_sms 表示还在等待
            if result.get("error_code") == "wait_sms":
                logger.debug("SMSMan 等待中: request_id=%s 已等待 %.0fs", request_id, time.time() - start)
                await asyncio.sleep(interval)
                continue
            
            # 其他错误直接退出
            if not result.get("success"):
                logger.error("SMSMan 轮询失败: request_id=%s error=%s", request_id, result.get("error"))
                return None
        
        logger.warning("SMSMan 轮询超时: request_id=%s timeout=%ss", request_id, timeout)
        return None

    # ── 余额查询 ──

    def get_balance(self) -> Dict[str, Any]:
        """查询账户余额

        Returns:
            {"success": True, "balance": "123.45"}
        """
        return self._call("get-balance")


smsman_service = SmsManService()
