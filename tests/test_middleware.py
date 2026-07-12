"""中间件单元测试"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.middlewares import TraceIDMiddleware


class TestTraceIDMiddleware:
    """TraceIDMiddleware 测试（SimpleBaseMiddleware 接口）"""

    @pytest.fixture
    def mock_app(self):
        app = AsyncMock()
        app.return_value = AsyncMock()
        return app

    def _make_mock_request(self, headers: dict = None, path: str = "/test"):
        """构造符合 SimpleBaseMiddleware 接口的 mock Request"""
        headers = headers or {}
        request = MagicMock()
        request.headers = MagicMock()
        # headers.get 是大小写不敏感的，这里同时处理两边的 case
        request.headers.get = MagicMock()
        request.headers.get.side_effect = lambda k, d=None: \
            headers.get(k) or headers.get(k.lower()) or headers.get(k.upper()) or d
        request.url = MagicMock()
        request.url.path = path
        request.state = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        return request

    @pytest.mark.asyncio
    async def test_injects_x_trace_id_header(self, mock_app):
        """无 X-Trace-ID 时自动生成 12 位 trace_id"""
        middleware = TraceIDMiddleware(mock_app)
        req = self._make_mock_request()

        await middleware.before_request(req)

        from app.log.log import get_trace_id
        tid = get_trace_id()
        assert tid != ""
        assert len(tid) == 12
        assert req.state.trace_id == tid

    @pytest.mark.asyncio
    async def test_reads_existing_x_trace_id(self, mock_app):
        """从请求头读取已有 X-Trace-ID"""
        middleware = TraceIDMiddleware(mock_app)
        req = self._make_mock_request({"x-trace-id": "existing-tid-123"})

        await middleware.before_request(req)

        from app.log.log import get_trace_id
        assert get_trace_id() == "existing-tid-123"
        assert req.state.trace_id == "existing-tid-123"

    @pytest.mark.asyncio
    async def test_non_http_scope_passthrough(self, mock_app):
        """WebSocket 等非 HTTP scope 直接透传"""
        scope = {"type": "websocket", "path": "/ws"}
        middleware = TraceIDMiddleware(mock_app)

        async def _receive():
            return {"type": "websocket.connect"}

        await middleware(scope, _receive, AsyncMock())
        mock_app.assert_called_once()
