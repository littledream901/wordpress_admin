"""
异常分层体系 —— HTTP 层、业务层、外部服务层三级分类，统一错误码。

用法:
    from app.core.exceptions import (
        ErrorCode, ProviderConfigError, ExternalAPIError,
        OnePanelError, SiteNotFoundError, WordPressOperationError,
    )

    raise ProviderConfigError("onepanel", "url")
    raise OnePanelError("create site", status_code=500, detail="...")
    raise SiteNotFoundError(site_id=123, domain="example.com")

特性:
    - 所有业务异常携带 error_code + provider/action/context 结构化信息
    - 自动被 FastAPI exception_handler 捕获并转为统一 JSON 响应
    - 支持 exc_info 格式化为可搜索的日志键
"""

from enum import Enum
from typing import Any, Optional


# ══════════════════════════════════════════════════════════════════════════
#  统一错误码
# ══════════════════════════════════════════════════════════════════════════

class ErrorCode(Enum):
    """业务错误码，5 位数字，按领域分段：

    1xxxx — 通用 / 参数校验
    2xxxx — 认证 / 权限
    3xxxx — 资源（站点 / 任务）
    4xxxx — 配置 / Provider
    5xxxx — 外部服务
    6xxxx — 建站 / WordPress
    """
    # ── 通用 ──
    UNKNOWN = 10000
    VALIDATION_ERROR = 10001
    NOT_FOUND = 10002
    INTEGRITY_ERROR = 10003

    # ── 认证 ──
    AUTH_FAILED = 20001
    TOKEN_EXPIRED = 20002
    PERMISSION_DENIED = 20003

    # ── 资源 ──
    SITE_NOT_FOUND = 30001
    DOMAIN_ALREADY_EXISTS = 30002
    JOB_NOT_FOUND = 30003
    RESOURCE_BUSY = 30004
    TASK_EXECUTION_FAILED = 30005
    TASK_TIMEOUT = 30006

    # ── 配置 ──
    SETTING_MISSING = 40001
    PROVIDER_CONFIG_MISSING = 40002

    # ── 外部服务 ──
    EXTERNAL_API_ERROR = 50001
    ONEPANEL_ERROR = 50010
    CLOUDFLARE_ERROR = 50020
    HUBSTUDIO_ERROR = 50030
    DYNADOT_ERROR = 50040
    WOOCOMMERCE_ERROR = 50050

    # ── WordPress / 建站 ──
    WP_OPERATION_ERROR = 60001
    WP_FILE_RESTORE_ERROR = 60002
    WP_DOMAIN_REPLACE_ERROR = 60003
    WP_WOO_KEY_ERROR = 60004
    WP_FEED_ERROR = 60005
    WP_HEALTH_CHECK_ERROR = 60006
    PROVISION_FAILED = 60010


# ══════════════════════════════════════════════════════════════════════════
#  业务异常基类
# ══════════════════════════════════════════════════════════════════════════

class BusinessError(Exception):
    """所有业务异常基类 —— 携带 error_code"""
    error_code: ErrorCode = ErrorCode.UNKNOWN

    def __init__(self, *args, **kwargs):
        super().__init__(*args)


# ══════════════════════════════════════════════════════════════════════════
#  配置异常
# ══════════════════════════════════════════════════════════════════════════

class SettingNotFound(BusinessError):
    """环境变量/配置文件缺失"""
    error_code = ErrorCode.SETTING_MISSING


class ProviderConfigError(BusinessError):
    """提供商配置缺失或无效 —— 阻止操作继续"""
    error_code = ErrorCode.PROVIDER_CONFIG_MISSING

    def __init__(self, provider: str, key: str, detail: str = ""):
        self.provider = provider
        self.key = key
        self.detail = detail
        msg = f"[{provider}] 缺少配置项: {key}"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


# ══════════════════════════════════════════════════════════════════════════
#  外部服务异常
# ══════════════════════════════════════════════════════════════════════════

class ExternalAPIError(BusinessError):
    """上游服务调用失败（1Panel / Cloudflare / HubStudio / Dynadot 等）"""
    error_code = ErrorCode.EXTERNAL_API_ERROR

    def __init__(
        self,
        provider: str,
        action: str = "",
        status_code: Optional[int] = None,
        detail: str = "",
        response_body: Any = None,
    ):
        self.provider = provider
        self.action = action
        self.status_code = status_code
        self.detail = detail
        self.response_body = response_body
        parts = [f"[{provider}]"]
        if action:
            parts.append(f" {action} 失败")
        if status_code:
            parts.append(f" HTTP {status_code}")
        if detail:
            parts.append(f": {detail[:200]}")
        super().__init__("".join(parts))


class CloudflareError(ExternalAPIError):
    """Cloudflare API 调用失败"""
    error_code = ErrorCode.CLOUDFLARE_ERROR
    def __init__(self, action: str = "", detail: str = "", **kwargs):
        super().__init__("Cloudflare", action=action, detail=detail, **kwargs)


class OnePanelError(ExternalAPIError):
    """1Panel API 调用失败"""
    error_code = ErrorCode.ONEPANEL_ERROR
    def __init__(self, action: str = "", detail: str = "", **kwargs):
        super().__init__("1Panel", action=action, detail=detail, **kwargs)


class HubStudioError(ExternalAPIError):
    """HubStudio API 调用失败"""
    error_code = ErrorCode.HUBSTUDIO_ERROR
    def __init__(self, action: str = "", detail: str = "", **kwargs):
        super().__init__("HubStudio", action=action, detail=detail, **kwargs)


class DynadotError(ExternalAPIError):
    """Dynadot API 调用失败"""
    error_code = ErrorCode.DYNADOT_ERROR
    def __init__(self, action: str = "", detail: str = "", **kwargs):
        super().__init__("Dynadot", action=action, detail=detail, **kwargs)


# ══════════════════════════════════════════════════════════════════════════
#  领域异常 —— 站点
# ══════════════════════════════════════════════════════════════════════════

class SiteNotFoundError(BusinessError):
    """站点不存在"""
    error_code = ErrorCode.SITE_NOT_FOUND

    def __init__(self, site_id: int = 0, domain: str = ""):
        self.site_id = site_id
        self.domain = domain
        parts = ["站点不存在"]
        if site_id:
            parts.append(f" id={site_id}")
        if domain:
            parts.append(f" domain={domain}")
        super().__init__("".join(parts))


class DomainAlreadyExistsError(BusinessError):
    """域名已被占用"""
    error_code = ErrorCode.DOMAIN_ALREADY_EXISTS

    def __init__(self, domain: str, site_id: int = 0, onepanel_site_id: int = 0):
        self.domain = domain
        self.site_id = site_id
        self.onepanel_site_id = onepanel_site_id
        super().__init__(f"域名已存在站点: {domain}")


# ══════════════════════════════════════════════════════════════════════════
#  领域异常 —— 任务
# ══════════════════════════════════════════════════════════════════════════

class TaskExecutionError(BusinessError):
    """任务执行失败 —— 携带 site_id / action_type / step 上下文"""
    error_code = ErrorCode.TASK_EXECUTION_FAILED

    def __init__(
        self,
        action_type: str,
        step: str = "",
        site_id: int = 0,
        error: str = "",
        recoverable: bool = False,
    ):
        self.action_type = action_type
        self.step = step
        self.site_id = site_id
        self.recoverable = recoverable
        parts = [f"任务失败 [{action_type}]"]
        if site_id:
            parts.append(f" site={site_id}")
        if step:
            parts.append(f" step={step}")
        if error:
            parts.append(f": {error[:200]}")
        super().__init__("".join(parts))
        self.error = error


class ResourceBusyError(BusinessError):
    """资源被占用 —— 如建站任务正在执行中"""
    error_code = ErrorCode.RESOURCE_BUSY

    def __init__(self, resource_type: str = "site", resource_id: int = 0, detail: str = ""):
        self.resource_type = resource_type
        self.resource_id = resource_id
        msg = f"{resource_type}#{resource_id} 正忙"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


class ProvisionTimeoutError(ExternalAPIError):
    """建站超时"""
    error_code = ErrorCode.TASK_TIMEOUT
    def __init__(self, site_id: int, step: str = "", elapsed_minutes: float = 0):
        self.site_id = site_id
        self.step = step
        super().__init__(
            provider="1Panel",
            action="provision",
            detail=f"site={site_id} step={step} 超时({elapsed_minutes:.0f}分钟)",
        )


# ══════════════════════════════════════════════════════════════════════════
#  领域异常 —— WordPress / 建站操作
# ══════════════════════════════════════════════════════════════════════════

class WordPressOperationError(BusinessError):
    """WordPress 站点操作失败（文件/数据库/域名替换等）"""
    error_code = ErrorCode.WP_OPERATION_ERROR

    def __init__(self, action: str, domain: str = "", detail: str = ""):
        self.action = action
        self.domain = domain
        msg = f"WordPress {action} 失败"
        if domain:
            msg += f" [{domain}]"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
