"""异常体系单元测试"""

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from tortoise.exceptions import DoesNotExist

from app.core.exceptions import (
    CloudflareError,
    DynadotError,
    ExternalAPIError,
    HubStudioError,
    OnePanelError,
    ProviderConfigError,
    ProvisionTimeoutError,
    ResourceBusyError,
    SettingNotFound,
    TaskExecutionError,
    # 异常处理器
    DoesNotExistHandle,
    HttpExcHandle,
    IntegrityHandle,
    ProviderConfigErrorHandle,
    RequestValidationHandle,
    ResourceBusyHandle,
    ResponseValidationHandle,
    ServiceErrorHandle,
)


# ── 异常类实例化测试 ──

class TestProviderConfigError:
    def test_basic(self):
        exc = ProviderConfigError("onepanel", "url")
        assert exc.provider == "onepanel"
        assert exc.key == "url"
        assert "[onepanel] 缺少配置项: url" in str(exc)

    def test_with_detail(self):
        exc = ProviderConfigError("cloudflare", "CF_API_TOKEN", "请在 .env 中配置")
        assert exc.detail == "请在 .env 中配置"
        assert "CF_API_TOKEN" in str(exc)


class TestExternalAPIError:
    def test_minimal(self):
        exc = ExternalAPIError("1Panel")
        assert exc.provider == "1Panel"
        assert exc.action == ""
        assert exc.status_code is None

    def test_full(self):
        exc = ExternalAPIError("1Panel", "create site", 500, "Internal Server Error", {"error": "boom"})
        assert exc.provider == "1Panel"
        assert exc.action == "create site"
        assert exc.status_code == 500
        assert exc.detail == "Internal Server Error"
        assert exc.response_body == {"error": "boom"}
        assert "HTTP 500" in str(exc)
        assert "create site 失败" in str(exc)

    def test_subclass_shortcuts(self):
        # 子类自动设置 provider 名称
        cf = CloudflareError("dns update", "timeout")
        assert cf.provider == "Cloudflare"
        assert "[Cloudflare]" in str(cf)

        op = OnePanelError("ssl deploy")
        assert op.provider == "1Panel"
        assert "[1Panel]" in str(op)

        hub = HubStudioError("start browser")
        assert hub.provider == "HubStudio"
        assert "[HubStudio]" in str(hub)

        dy = DynadotError("set ns")
        assert dy.provider == "Dynadot"
        assert "[Dynadot]" in str(dy)


class TestTaskExecutionError:
    def test_full(self):
        exc = TaskExecutionError("provision", "restore_db", 42, "DB connection failed", True)
        assert exc.action_type == "provision"
        assert exc.step == "restore_db"
        assert exc.site_id == 42
        assert exc.recoverable is True
        assert "task=42" in str(exc).lower() or "site=42" in str(exc)
        assert "restore_db" in str(exc)

    def test_default_recoverable(self):
        exc = TaskExecutionError("dns")
        assert exc.recoverable is False


class TestResourceBusyError:
    def test_basic(self):
        exc = ResourceBusyError("site", 100)
        assert exc.resource_type == "site"
        assert exc.resource_id == 100
        assert "100" in str(exc)


class TestProvisionTimeoutError:
    def test_basic(self):
        exc = ProvisionTimeoutError(1, "ssl", 15.5)
        assert exc.site_id == 1
        assert exc.step == "ssl"
        assert exc.provider == "1Panel"
        assert "超时" in str(exc)


class TestSettingNotFound:
    def test_basic(self):
        exc = SettingNotFound("MISSING_KEY")
        assert isinstance(exc, Exception)


# ── 异常处理器测试 ──

class TestExceptionHandlers:
    """测试 FastAPI 异常处理器返回正确的状态码和响应"""

    @pytest.mark.asyncio
    async def test_does_not_exist_handle(self, mock_request):
        resp = await DoesNotExistHandle(mock_request, DoesNotExist("not found"))
        assert resp.status_code == 404
        assert resp.body
        import json
        body = json.loads(resp.body)
        assert body["code"] == 404

    @pytest.mark.asyncio
    async def test_integrity_handle(self, mock_request):
        from tortoise.exceptions import IntegrityError
        resp = await IntegrityHandle(mock_request, IntegrityError("duplicate"))
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_http_exc_handle(self, mock_request):
        exc = HTTPException(status_code=403, detail="Forbidden")
        resp = await HttpExcHandle(mock_request, exc)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_request_validation_handle(self, mock_request):
        resp = await RequestValidationHandle(mock_request, RequestValidationError(errors=[]))
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_service_error_handle(self, mock_request):
        exc = OnePanelError("create site", "failed")
        resp = await ServiceErrorHandle(mock_request, exc)
        assert resp.status_code == 502
        import json
        body = json.loads(resp.body)
        assert body["data"]["provider"] == "1Panel"

    @pytest.mark.asyncio
    async def test_resource_busy_handle(self, mock_request):
        exc = ResourceBusyError("site", 1, "建站中")
        resp = await ResourceBusyHandle(mock_request, exc)
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_provider_config_error_handle(self, mock_request):
        exc = ProviderConfigError("onepanel", "url")
        resp = await ProviderConfigErrorHandle(mock_request, exc)
        assert resp.status_code == 500
        import json
        body = json.loads(resp.body)
        assert body["data"]["provider"] == "onepanel"
        assert body["data"]["key"] == "url"


# ── error_code 响应验证 ──

class TestErrorCodeInResponse:
    """验证所有业务异常处理器在响应中包含 error_code"""

    @pytest.mark.asyncio
    async def test_provider_config_includes_error_code(self, mock_request):
        import json
        exc = ProviderConfigError("onepanel", "url")
        resp = await ProviderConfigErrorHandle(mock_request, exc)
        body = json.loads(resp.body)
        assert body["error_code"] is not None
        assert body["error_code"] == 40002  # PROVIDER_CONFIG_MISSING

    @pytest.mark.asyncio
    async def test_service_error_includes_error_code(self, mock_request):
        import json
        exc = OnePanelError("create site")
        resp = await ServiceErrorHandle(mock_request, exc)
        body = json.loads(resp.body)
        assert body["error_code"] is not None
        assert body["error_code"] == 50010  # ONEPANEL_ERROR

    @pytest.mark.asyncio
    async def test_not_found_includes_error_code(self, mock_request):
        import json
        resp = await DoesNotExistHandle(mock_request, DoesNotExist("not found"))
        body = json.loads(resp.body)
        assert body["error_code"] == 10002  # NOT_FOUND

    @pytest.mark.asyncio
    async def test_validation_includes_error_code(self, mock_request):
        import json
        resp = await RequestValidationHandle(mock_request, RequestValidationError(errors=[]))
        body = json.loads(resp.body)
        assert body["error_code"] == 10001  # VALIDATION_ERROR

    @pytest.mark.asyncio
    async def test_integrity_includes_error_code(self, mock_request):
        import json
        from tortoise.exceptions import IntegrityError
        resp = await IntegrityHandle(mock_request, IntegrityError("dup"))
        body = json.loads(resp.body)
        assert body["error_code"] == 10003  # INTEGRITY_ERROR

    @pytest.mark.asyncio
    async def test_resource_busy_includes_error_code(self, mock_request):
        import json
        exc = ResourceBusyError("site", 1)
        resp = await ResourceBusyHandle(mock_request, exc)
        body = json.loads(resp.body)
        assert body["error_code"] is not None  # RESOURCE_BUSY


# ── 异常层级测试 ──

class TestExceptionHierarchy:
    """验证异常类的继承关系"""

    def test_external_api_subclasses(self):
        assert issubclass(CloudflareError, ExternalAPIError)
        assert issubclass(OnePanelError, ExternalAPIError)
        assert issubclass(HubStudioError, ExternalAPIError)
        assert issubclass(DynadotError, ExternalAPIError)
        assert issubclass(ProvisionTimeoutError, ExternalAPIError)

    def test_exception_is_catchable_as_base(self):
        """子类异常可以被基类 except 捕获"""
        try:
            raise OnePanelError("test")
        except ExternalAPIError as e:
            assert e.provider == "1Panel"
