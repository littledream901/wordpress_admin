"""TaskRunner 基类单元测试"""

import asyncio

import pytest

from app.core.exceptions import (
    ExternalAPIError,
    OnePanelError,
    ProviderConfigError,
    ResourceBusyError,
    TaskExecutionError,
)
from app.services.tasks.runner import TaskRunner, _ACTION_PROVIDER


class TestClassifyError:
    """错误分类测试"""

    def test_config_error(self):
        exc = ProviderConfigError("onepanel", "url")
        result = TaskRunner._classify_error(exc)
        assert result["category"] == "config"
        assert result["recoverable"] is False

    def test_external_api_error(self):
        exc = OnePanelError("create site")
        result = TaskRunner._classify_error(exc)
        assert result["category"] == "external_api"
        assert result["recoverable"] is True

    def test_resource_busy(self):
        exc = ResourceBusyError("site", 1)
        result = TaskRunner._classify_error(exc)
        assert result["category"] == "resource_busy"
        assert result["recoverable"] is False

    def test_timeout(self):
        exc = asyncio.TimeoutError()
        result = TaskRunner._classify_error(exc)
        assert result["category"] == "timeout"
        assert result["recoverable"] is True

    def test_network_error(self):
        for err_cls in [ConnectionError, OSError]:
            result = TaskRunner._classify_error(err_cls("boom"))
            assert result["category"] == "network"
            assert result["recoverable"] is True

    def test_timeout_error(self):
        result = TaskRunner._classify_error(TimeoutError("boom"))
        assert result["category"] == "timeout"
        assert result["recoverable"] is True

    def test_asyncio_timeout_error(self):
        result = TaskRunner._classify_error(asyncio.TimeoutError("boom"))
        assert result["category"] == "timeout"
        assert result["recoverable"] is True

    def test_unknown_error(self):
        exc = ValueError("something")
        result = TaskRunner._classify_error(exc)
        assert result["category"] == "unknown"
        assert result["recoverable"] is False


class TestFormatError:
    """错误格式化测试"""

    def test_business_exception_format(self):
        exc = ProviderConfigError("cloudflare", "CF_API_TOKEN")
        formatted = TaskRunner._format_error(exc)
        assert "[cloudflare]" in formatted.lower()
        # 业务异常不应包含堆栈
        assert "Traceback" not in formatted

    def test_generic_exception_format(self):
        try:
            raise ValueError("test error")
        except ValueError as exc:
            formatted = TaskRunner._format_error(exc)
        assert "ValueError" in formatted
        assert "test error" in formatted


class TestWithTrace:
    """trace_id 生成测试"""

    def test_generates_trace_id(self, reset_trace):
        tid = TaskRunner._with_trace(42, "provision")
        assert "provision" in tid
        assert "42" in tid
        # trace_id 应包含 8 位 hex
        parts = tid.split("-")
        assert len(parts[-1]) == 8

    def test_sets_context_var(self, reset_trace):
        from app.log.log import get_trace_id
        tid = TaskRunner._with_trace(1, "dns")
        assert get_trace_id() == tid


class TestProviderType:
    """action_type → provider_type 映射测试"""

    def test_known_actions(self):
        mock_job = type("Job", (), {"action_type": "dns"})()
        runner = TaskRunner()
        assert runner._provider_type(mock_job) == "cloudflare"

        mock_job.action_type = "provision"
        assert runner._provider_type(mock_job) == "onepanel"

        mock_job.action_type = "woo_import"
        assert runner._provider_type(mock_job) == "woo"

    def test_unknown_action(self):
        mock_job = type("Job", (), {"action_type": "unknown_xyz"})()
        runner = TaskRunner()
        assert runner._provider_type(mock_job) == ""


class TestActionProviderMapping:
    """验证 _ACTION_PROVIDER 映射的完整性"""

    def test_all_values_are_non_empty(self):
        for k, v in _ACTION_PROVIDER.items():
            assert v, f"action_type '{k}' has empty provider mapping"
