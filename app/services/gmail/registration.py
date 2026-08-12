"""Gmail 企业邮箱注册 Service — 封装第三方 API 调用与业务编排"""

from typing import Any, Dict, Optional

from app.log import logger
from app.services.providers.improvmx_service import improvmx_service
from app.services.providers.smsman_service import smsman_service


class GmailRegistrationService:
    """Gmail 注册业务流程的 Service 层

    Controller 负责 CRUD + 状态更新，Service 负责第三方调用 + 复杂编排。
    """

    # ── 步骤 1: ImprovMX 转发邮箱 ──

    @staticmethod
    def create_forwarding_email(domain: str, alias: str, forward_to: str) -> Dict[str, Any]:
        """ImprovMX 转发步骤已废弃"""
        logger.info(f"[gmail_reg] ImprovMX 转发服务已废弃")
        return {"success": False, "error": "ImprovMX 转发步骤已废弃"}

    # ── 步骤 3: SMS 号码 ──

    @staticmethod
    def get_phone_number(
        country_id: Optional[int] = None,
        application_id: Optional[int] = None,
        max_price: Optional[int] = None,
    ) -> Dict[str, Any]:
        """调用 SMSMan 获取号码，返回结果 dict"""
        result = smsman_service.get_number(
            country_id=country_id,
            application_id=application_id,
            max_price=max_price,
        )
        if result.get("success") and result.get("request_id") is not None:
            return {
                "success": True,
                "request_id": int(result["request_id"]),
                "phone_number": str(result.get("number", "")),
                "country_id": result.get("country_id"),
                "application_id": result.get("application_id"),
            }
        return {"success": False, "error": f"获取号码失败: {result.get('error', result)}"}

    # ── 步骤 4: 等待 SMS ──

    @staticmethod
    async def wait_for_sms(request_id: int, timeout: int = 300, interval: int = 10) -> Dict[str, Any]:
        """等待 SMS 验证码，返回结果 dict"""
        code = await smsman_service.wait_for_sms_async(
            request_id=request_id,
            timeout=timeout,
            interval=interval,
        )
        if not code:
            return {"success": False, "error": f"等待验证码超时或失败（{timeout}s）"}
        return {"success": True, "code": code}

    # ── 步骤 5: 确认 SMS ──

    @staticmethod
    def confirm_sms(request_id: int, status: str = "used") -> Dict[str, Any]:
        """确认 SMS 状态，返回结果 dict"""
        result = smsman_service.set_status(request_id=request_id, status=status)
        if result.get("success"):
            return {"success": True}
        return {"success": False, "error": result.get("error", "确认 SMS 状态失败")}


gmail_registration_service = GmailRegistrationService()
