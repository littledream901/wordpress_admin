"""Gmail 企业邮箱注册 Service — 封装第三方 API 调用与业务编排"""

from typing import Any, Dict

from app.services.providers.improvmx_service import improvmx_service
from app.services.providers.smsman_service import smsman_service


class GmailRegistrationService:
    """Gmail 注册业务流程的 Service 层

    Controller 负责 CRUD + 状态更新，Service 负责第三方调用 + 复杂编排。
    """

    # ── 步骤 2: ImprovMX 转发邮箱 ──

    @staticmethod
    def create_forwarding_email(domain: str, alias: str, forward_to: str) -> Dict[str, Any]:
        """调用 ImprovMX 创建转发别名，返回结果 dict"""
        result = improvmx_service.create_alias(
            domain=domain,
            alias=alias,
            forward=forward_to,
        )
        if result.get("success"):
            alias_data = result.get("alias", {})
            return {
                "success": True,
                "improvmx_alias_id": str(alias_data.get("id", "")),
            }
        return {"success": False, "error": f"ImprovMX 失败: {result}"}

    # ── 步骤 3: HubStudio 环境 ──

    @staticmethod
    def create_environment(alias: str, domain: str, full_name: str) -> Dict[str, Any]:
        """调用 HubStudio 创建浏览器环境，返回结果 dict"""
        from app.services.hubstudio.tasks.create_gmail_env import create_gmail_environment
        return create_gmail_environment(alias, domain, full_name)

    # ── 步骤 4a: SMS 号码 ──

    @staticmethod
    def get_phone_number(
        country_id: int = None,
        application_id: int = None,
        max_price: int = None,
    ) -> Dict[str, Any]:
        """调用 SMSMan 获取号码，返回结果 dict"""
        result = smsman_service.get_number(
            country_id=country_id,
            application_id=application_id,
            max_price=max_price,
        )
        if "request_id" in result:
            return {
                "success": True,
                "request_id": int(result["request_id"]),
                "phone_number": str(result.get("number", "")),
                "country_id": result.get("country_id"),
                "application_id": result.get("application_id"),
            }
        return {"success": False, "error": f"获取号码失败: {result}"}

    # ── 步骤 4b: 等待 SMS ──

    @staticmethod
    async def wait_for_sms(request_id: int, timeout: int = 300, interval: int = 10) -> Dict[str, Any]:
        """等待 SMS 验证码，返回结果 dict"""
        code = await smsman_service.wait_for_sms_async(
            request_id=request_id,
            timeout=timeout,
            interval=interval,
        )
        return {"success": True, "code": code}

    # ── 步骤 4c: 确认 SMS ──

    @staticmethod
    def confirm_sms(request_id: int, status: str = "used") -> Dict[str, Any]:
        """确认 SMS 状态，返回结果 dict"""
        smsman_service.set_status(request_id=request_id, status=status)
        return {"success": True}


gmail_registration_service = GmailRegistrationService()
