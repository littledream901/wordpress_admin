"""pytest 全局配置和 fixtures"""

import os as _os
import sys as _sys

# ═══ 必须在任何 app 导入之前设置 ────────────────────────
_os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-12345678")
_os.environ.setdefault("DEFAULT_PASSWORD", "test-password")
_os.environ.setdefault("DB_URL", "sqlite://:memory:")
_os.environ.setdefault("DEBUG", "true")

# 确保项目根目录在 sys.path 中
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))


from unittest.mock import MagicMock

import pytest
from fastapi import Request


@pytest.fixture(autouse=True)
def reset_trace():
    """每个测试前重置 trace_id ContextVar"""
    from app.log.log import _trace_id
    token = _trace_id.set("")
    yield
    _trace_id.reset(token)


@pytest.fixture
def mock_request():
    """创建一个 mock FastAPI Request 用于异常处理器测试"""
    req = MagicMock(spec=Request)
    req.query_params = {}
    return req
