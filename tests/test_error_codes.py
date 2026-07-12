"""ErrorCode 枚举和领域异常测试"""

import pytest

from app.core.exceptions import (
    BusinessError,
    ErrorCode,
    ProviderConfigError,
    ExternalAPIError,
    OnePanelError,
    CloudflareError,
    HubStudioError,
    DynadotError,
    SiteNotFoundError,
    DomainAlreadyExistsError,
    TaskExecutionError,
    ResourceBusyError,
    ProvisionTimeoutError,
    WordPressOperationError,
    SettingNotFound,
)


# ══════════════════════════════════════════════════════════════════════════
#  ErrorCode 枚举测试
# ══════════════════════════════════════════════════════════════════════════

class TestErrorCodes:
    """验证所有 ErrorCode 值在正确分段内"""

    def test_segment_1xxxx_general(self):
        assert ErrorCode.UNKNOWN.value == 10000
        assert ErrorCode.VALIDATION_ERROR.value == 10001
        assert ErrorCode.NOT_FOUND.value == 10002
        assert ErrorCode.INTEGRITY_ERROR.value == 10003

    def test_segment_2xxxx_auth(self):
        assert ErrorCode.AUTH_FAILED.value == 20001
        assert ErrorCode.TOKEN_EXPIRED.value == 20002
        assert ErrorCode.PERMISSION_DENIED.value == 20003

    def test_segment_3xxxx_resource(self):
        assert ErrorCode.SITE_NOT_FOUND.value == 30001
        assert ErrorCode.DOMAIN_ALREADY_EXISTS.value == 30002
        assert ErrorCode.JOB_NOT_FOUND.value == 30003
        assert ErrorCode.RESOURCE_BUSY.value == 30004
        assert ErrorCode.TASK_EXECUTION_FAILED.value == 30005
        assert ErrorCode.TASK_TIMEOUT.value == 30006

    def test_segment_4xxxx_config(self):
        assert ErrorCode.SETTING_MISSING.value == 40001
        assert ErrorCode.PROVIDER_CONFIG_MISSING.value == 40002

    def test_segment_5xxxx_external_service(self):
        assert ErrorCode.EXTERNAL_API_ERROR.value == 50001
        assert ErrorCode.ONEPANEL_ERROR.value == 50010
        assert ErrorCode.CLOUDFLARE_ERROR.value == 50020
        assert ErrorCode.HUBSTUDIO_ERROR.value == 50030
        assert ErrorCode.DYNADOT_ERROR.value == 50040
        assert ErrorCode.WOOCOMMERCE_ERROR.value == 50050

    def test_segment_6xxxx_wordpress(self):
        assert ErrorCode.WP_OPERATION_ERROR.value == 60001
        assert ErrorCode.WP_FILE_RESTORE_ERROR.value == 60002
        assert ErrorCode.WP_DOMAIN_REPLACE_ERROR.value == 60003
        assert ErrorCode.WP_WOO_KEY_ERROR.value == 60004
        assert ErrorCode.WP_FEED_ERROR.value == 60005
        assert ErrorCode.WP_HEALTH_CHECK_ERROR.value == 60006
        assert ErrorCode.PROVISION_FAILED.value == 60010

    def test_no_duplicate_values(self):
        """所有 ErrorCode 值必须唯一"""
        values = [e.value for e in ErrorCode]
        assert len(values) == len(set(values))


# ══════════════════════════════════════════════════════════════════════════
#  BusinessError 基类测试
# ══════════════════════════════════════════════════════════════════════════

class TestBusinessError:
    """验证所有业务异常都携带 error_code"""

    def test_setting_not_found_has_code(self):
        exc = SettingNotFound("TEST")
        assert exc.error_code == ErrorCode.SETTING_MISSING

    def test_provider_config_has_code(self):
        exc = ProviderConfigError("onepanel", "url")
        assert exc.error_code == ErrorCode.PROVIDER_CONFIG_MISSING

    def test_external_api_has_code(self):
        exc = ExternalAPIError("test")
        assert exc.error_code == ErrorCode.EXTERNAL_API_ERROR

    def test_each_subclass_has_unique_code(self):
        """每个子类使用不同的 error_code"""
        codes = {
            OnePanelError: ErrorCode.ONEPANEL_ERROR,
            CloudflareError: ErrorCode.CLOUDFLARE_ERROR,
            HubStudioError: ErrorCode.HUBSTUDIO_ERROR,
            DynadotError: ErrorCode.DYNADOT_ERROR,
        }
        for cls, expected in codes.items():
            exc = cls()
            assert exc.error_code == expected


# ══════════════════════════════════════════════════════════════════════════
#  站点领域异常测试
# ══════════════════════════════════════════════════════════════════════════

class TestSiteExceptions:
    """测试站点相关的领域异常"""

    def test_site_not_found_with_id(self):
        exc = SiteNotFoundError(site_id=42)
        assert exc.site_id == 42
        assert exc.error_code == ErrorCode.SITE_NOT_FOUND
        assert "42" in str(exc)

    def test_site_not_found_with_domain(self):
        exc = SiteNotFoundError(domain="example.com")
        assert exc.domain == "example.com"
        assert "example.com" in str(exc)

    def test_site_not_found_with_both(self):
        exc = SiteNotFoundError(site_id=1, domain="test.com")
        assert "1" in str(exc)
        assert "test.com" in str(exc)

    def test_domain_already_exists(self):
        exc = DomainAlreadyExistsError("example.com", site_id=5)
        assert exc.domain == "example.com"
        assert exc.site_id == 5
        assert exc.error_code == ErrorCode.DOMAIN_ALREADY_EXISTS
        assert "example.com" in str(exc)

    def test_site_exceptions_are_business_errors(self):
        assert isinstance(SiteNotFoundError(1), BusinessError)
        assert isinstance(DomainAlreadyExistsError("x.com"), BusinessError)


# ══════════════════════════════════════════════════════════════════════════
#  WordPress 领域异常测试
# ══════════════════════════════════════════════════════════════════════════

class TestWordPressExceptions:
    """测试 WordPress 相关的领域异常"""

    def test_basic(self):
        exc = WordPressOperationError("restore files", "example.com", "disk full")
        assert exc.action == "restore files"
        assert exc.domain == "example.com"
        assert exc.error_code == ErrorCode.WP_OPERATION_ERROR
        assert "restore files" in str(exc)
        assert "example.com" in str(exc)

    def test_minimal(self):
        exc = WordPressOperationError("domain replace")
        assert exc.domain == ""
        assert exc.error_code == ErrorCode.WP_OPERATION_ERROR

    def test_is_business_error(self):
        exc = WordPressOperationError("test")
        assert isinstance(exc, BusinessError)


# ══════════════════════════════════════════════════════════════════════════
#  任务异常测试
# ══════════════════════════════════════════════════════════════════════════

class TestTaskExceptions:
    """测试任务相关的异常"""

    def test_task_execution_has_code(self):
        exc = TaskExecutionError("provision")
        assert exc.error_code == ErrorCode.TASK_EXECUTION_FAILED

    def test_resource_busy_has_code(self):
        exc = ResourceBusyError("site", 1)
        assert exc.error_code == ErrorCode.RESOURCE_BUSY

    def test_provision_timeout_has_code(self):
        exc = ProvisionTimeoutError(1)
        assert exc.error_code == ErrorCode.TASK_TIMEOUT


# ══════════════════════════════════════════════════════════════════════════
#  继承层级测试
# ══════════════════════════════════════════════════════════════════════════

class TestExceptionHierarchy:
    """验证异常类层级关系"""

    def test_all_business_errors_are_business_error(self):
        """所有自定义异常都应继承自 BusinessError"""
        business_classes = [
            SettingNotFound("x"),
            ProviderConfigError("p", "k"),
            ExternalAPIError("p"),
            SiteNotFoundError(1),
            DomainAlreadyExistsError("d"),
            TaskExecutionError("a"),
            ResourceBusyError("s", 1),
            WordPressOperationError("a"),
            ProvisionTimeoutError(1),
        ]
        for exc in business_classes:
            assert isinstance(exc, BusinessError), f"{type(exc).__name__} should be BusinessError"

    def test_external_api_subclasses(self):
        assert issubclass(OnePanelError, ExternalAPIError)
        assert issubclass(CloudflareError, ExternalAPIError)
        assert issubclass(HubStudioError, ExternalAPIError)
        assert issubclass(DynadotError, ExternalAPIError)
        assert issubclass(ProvisionTimeoutError, ExternalAPIError)

    def test_catch_by_base(self):
        """子类可被基类 except 捕获"""
        try:
            raise OnePanelError("test")
        except ExternalAPIError as e:
            assert "[1Panel]" in str(e)
