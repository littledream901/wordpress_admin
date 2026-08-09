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
        """调用 ImprovMX 创建转发别名，返回结果 dict"""
        result = improvmx_service.create_alias(
            domain=domain,
            alias=alias,
            forward=forward_to,
        )
        if result.get("success"):
            alias_data = result.get("alias") or {}
            return {
                "success": True,
                "improvmx_alias_id": str(alias_data.get("id", "")),
            }
        return {"success": False, "error": f"ImprovMX 失败: {result.get('error', result)}"}

    # ── 步骤 2: HubStudio 环境 ──

    @staticmethod
    async def create_environment(
        alias: str,
        domain: str,
        full_name: str,
        site_id: int = 0,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """派发 HubStudio create_gmail_env 任务并同步执行

        复用 hubstudio_service 的派发链路，统一 provider 配置、Connector 探活、
        任务记录与结果回报，避免在此处重复实现执行器构建逻辑。
        """
        from app.services.hubstudio_service import hubstudio_service

        payload: Dict[str, Any] = {
            "alias": alias,
            "domain": domain,
            "full_name": full_name,
        }
        if extra_payload:
            payload.update(extra_payload)

        try:
            if site_id:
                job, result = await hubstudio_service.dispatch_for_site(
                    site_id=site_id,
                    job_type="create_gmail_env",
                    payload=payload,
                    execute_now=True,
                    agent_worker="gmail-registration",
                )
            else:
                # 无站点情况：直接创建任务，传 site_id=0（占位），不依赖站点查询
                job = await hubstudio_service.create_job(
                    site_id=0,
                    domain=domain,
                    job_type="create_gmail_env",
                    payload=payload,
                    provider_id=0,  # 需显式提供，避免 _resolve_provider_id(0) 查不到站点
                )
                result = await hubstudio_service._execute_job_sync(job, "gmail-registration")
        except Exception as e:
            logger.error(f"[gmail_reg] 创建环境失败: domain={domain} err={e}")
            return {"success": False, "error": str(e)}

        result = result or {}
        if result.get("status") == "success":
            return {
                "success": True,
                "env_id": result.get("env_id", ""),
                "container_name": result.get("containerName", ""),
                "action": result.get("action", ""),
                "job_id": job.id,
            }
        return {"success": False, "error": result.get("error") or "创建环境失败", "job_id": job.id}

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
