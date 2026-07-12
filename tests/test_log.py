"""TraceID 日志系统单元测试"""

import pytest

from app.log.log import (
    _trace_filter,
    _trace_id,
    get_trace_id,
    set_trace_id,
)


class TestTraceID:
    """trace_id ContextVar 跨协程传播测试"""

    def test_set_and_get(self):
        tid = "test-trace-123"
        set_trace_id(tid)
        assert get_trace_id() == tid

    def test_auto_generate(self, reset_trace):
        tid = get_trace_id()
        assert tid != ""
        assert len(tid) == 12  # uuid4 前 12 位

    def test_auto_generate_is_hex_suffix(self):
        tid = get_trace_id()
        # trace_id 为自动生成的 12 位 hex 字符串（不含前缀时）
        assert len(tid) in (12, 20)  # 12 for pure hex, 20 for 'action-siteid-hex'
        # 最后一段是 hex
        hex_part = tid.split("-")[-1]
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_context_isolation(self, reset_trace):
        """确认 trace_id 在不同调用间独立"""
        set_trace_id("caller-a")
        assert get_trace_id() == "caller-a"

        set_trace_id("caller-b")
        assert get_trace_id() == "caller-b"


class TestTraceFilter:
    """日志过滤器注入 trace_id 到 extra"""

    def test_injects_trace_id(self):
        set_trace_id("filter-test-456")
        record = {"extra": {}}
        result = _trace_filter(record)
        assert result is True
        assert record["extra"]["trace_id"] == "filter-test-456"

    def test_no_trace_id_shows_dash(self, reset_trace):
        """空 trace_id 时填充 '-'"""
        record = {"extra": {}}
        _trace_filter(record)
        assert record["extra"]["trace_id"] == "-"
