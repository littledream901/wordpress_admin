"""OnePanel API 客户端单元测试 — 使用 pytest-httpx mock"""

import hashlib
import time

import httpx
import pytest

from app.services.onepanel.client import OnePanelAPI
from app.core.exceptions import ProviderConfigError


class TestOnePanelAPIInit:
    """测试客户端初始化"""

    def test_unconfigured_does_not_raise(self, monkeypatch):
        """未配置时初始化不抛异常"""
        monkeypatch.setattr(
            "app.services.onepanel.client.ProviderResolver.sync_get_config_map",
            lambda _: {},
        )
        api = OnePanelAPI()
        assert api._configured is False

    def test_configured_with_url(self, monkeypatch):
        """正常配置"""
        monkeypatch.setattr(
            "app.services.onepanel.client.ProviderResolver.sync_get_config_map",
            lambda _: {"url": "https://panel.example.com", "api_key": "test-key"},
        )
        api = OnePanelAPI()
        assert api._configured is True
        assert api.base == "https://panel.example.com/api/v2"
        assert api.api_key == "test-key"

    def test_url_without_protocol_logs_warning(self, monkeypatch, caplog):
        """缺少协议头的 URL 应产生警告"""
        monkeypatch.setattr(
            "app.services.onepanel.client.ProviderResolver.sync_get_config_map",
            lambda _: {"url": "panel.example.com", "api_key": "test-key"},
        )
        import logging
        caplog.set_level(logging.WARNING)
        OnePanelAPI()
        assert any("缺少协议头" in r.message for r in caplog.records)


class TestHeaders:
    """测试认证头生成"""

    def test_generates_token_and_timestamp(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.onepanel.client.ProviderResolver.sync_get_config_map",
            lambda _: {"url": "https://x.com", "api_key": "my-secret"},
        )
        api = OnePanelAPI()
        headers = api.headers()
        assert "1Panel-Token" in headers
        assert "1Panel-Timestamp" in headers
        assert "application/json" in headers["Accept"]

    def test_token_is_valid_md5(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.onepanel.client.ProviderResolver.sync_get_config_map",
            lambda _: {"url": "https://x.com", "api_key": "test-key"},
        )
        api = OnePanelAPI()
        ts = str(int(time.time()))
        expected = hashlib.md5(f"1paneltest-key{ts}".encode()).hexdigest()
        headers = api.headers()
        assert headers["1Panel-Token"] == expected

    def test_no_json_content_type_when_disabled(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.onepanel.client.ProviderResolver.sync_get_config_map",
            lambda _: {"url": "https://x.com", "api_key": "x"},
        )
        api = OnePanelAPI()
        headers = api.headers(json_content=False)
        assert "Content-Type" not in headers


class TestRequest:
    """测试 _request 方法 — 使用 pytest-httpx mock HTTP"""

    def _mock_config(self, monkeypatch, **overrides):
        cfg = {"url": "https://panel.example.com", "api_key": "test-key"}
        cfg.update(overrides)
        monkeypatch.setattr(
            "app.services.onepanel.client.ProviderResolver.sync_get_config_map",
            lambda _: cfg,
        )

    def test_unconfigured_raises(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.onepanel.client.ProviderResolver.sync_get_config_map",
            lambda _: {},
        )
        api = OnePanelAPI()
        with pytest.raises(ProviderConfigError, match="面板地址未配置"):
            api._request("GET", "/test")

    def test_success_response(self, monkeypatch, httpx_mock):
        self._mock_config(monkeypatch)
        httpx_mock.add_response(
            method="POST",
            url="https://panel.example.com/api/v2/test",
            json={"code": 200, "data": {"id": 1}},
        )
        api = OnePanelAPI()
        ok, data = api.post("/test", {})
        assert ok is True
        assert data == {"id": 1}

    def test_non_200_code(self, monkeypatch, httpx_mock):
        self._mock_config(monkeypatch)
        httpx_mock.add_response(
            method="POST",
            url="https://panel.example.com/api/v2/test",
            json={"code": 400, "message": "Bad Request"},
        )
        api = OnePanelAPI()
        ok, msg = api.post("/test", {})
        assert ok is False
        assert "400" in str(msg)
        assert "Bad Request" in str(msg)

    def test_5xx_retries(self, monkeypatch, httpx_mock):
        self._mock_config(monkeypatch, max_retries="3", retry_interval="0")
        httpx_mock.add_response(
            method="POST",
            url="https://panel.example.com/api/v2/test",
            status_code=502,
            is_reusable=True,
        )
        api = OnePanelAPI()
        ok, err = api.post("/test", {})
        assert ok is False
        # 502 会触发重试
        assert len(httpx_mock.get_requests()) == 3

    def test_http_error_retries(self, monkeypatch, httpx_mock):
        self._mock_config(monkeypatch, max_retries="2", retry_interval="0")
        httpx_mock.add_exception(
            httpx.ConnectError("connection refused"),
            method="POST",
            url="https://panel.example.com/api/v2/test",
            is_reusable=True,
        )
        api = OnePanelAPI()
        ok, err = api.post("/test", {})
        assert ok is False
        assert "connection refused" in str(err).lower()
        # 应重试 2 次
        assert len(httpx_mock.get_requests()) == 2


class TestDownloadFile:
    def test_download_success(self, monkeypatch, httpx_mock):
        monkeypatch.setattr(
            "app.services.onepanel.client.ProviderResolver.sync_get_config_map",
            lambda _: {
                "url": "https://panel.example.com", "api_key": "test-key",
                "max_retries": "1", "panel_base": "/opt/1panel",
            },
        )
        httpx_mock.add_response(
            method="GET",
            url="https://panel.example.com/api/v2/files/download?path=%2Fopt%2F1panel%2Fbackup%2Ftest.zip",
            content=b"fake-zip-content",
        )
        api = OnePanelAPI()
        data = api.download_file("test.zip")
        assert data == b"fake-zip-content"
