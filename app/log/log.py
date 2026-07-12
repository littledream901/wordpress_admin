"""
统一日志模块 —— 基于 loguru，支持结构化输出、文件轮转、trace_id 追踪。

用法:
    from app.log import logger
    logger.info("用户登录", site_id=123, trace_id="abc-123")
    logger.error("建站失败", exc_info=True, site_id=456)

配置说明:
    - DEBUG=true   → 控制台 DEBUG 级别
    - DEBUG=false  → 控制台 INFO 级别 + 文件持久化（保留 30 天）
"""

import os
import sys
import uuid
from contextvars import ContextVar

from loguru import logger as loguru_logger

from app.settings import settings

# ── trace_id 上下文变量（跨协程传播） ──
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")


def get_trace_id() -> str:
    """获取当前请求/任务的 trace_id，不存在则生成一个"""
    tid = _trace_id.get()
    if not tid:
        tid = str(uuid.uuid4())[:12]
        _trace_id.set(tid)
    return tid


def set_trace_id(tid: str):
    """设置当前上下文的 trace_id"""
    _trace_id.set(tid)


# ── 日志格式 ──
_console_fmt = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

_file_fmt = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} | "
    "{extra[trace_id]} | {message}"
)


def _trace_filter(record: dict) -> bool:
    """注入 trace_id 到 extra 字段"""
    tid = _trace_id.get()
    record["extra"]["trace_id"] = tid or "-"
    return True


class LogConfig:
    def __init__(self):
        self.debug = settings.DEBUG
        self.level = "DEBUG" if self.debug else "INFO"
        self.logs_dir = os.path.join(settings.BASE_DIR, "app", "logs")

    def setup(self):
        loguru_logger.remove()

        # ── 控制台输出 ──
        loguru_logger.add(
            sink=sys.stdout,
            level=self.level,
            format=_console_fmt,
            filter=_trace_filter,
            colorize=True,
            backtrace=True,
            diagnose=self.debug,
        )

        # ── 文件输出（生产环境持久化，按天轮转，保留 30 天）──
        if not self.debug:
            os.makedirs(self.logs_dir, exist_ok=True)
            loguru_logger.add(
                sink=os.path.join(self.logs_dir, "app_{time:YYYY-MM-DD}.log"),
                level="INFO",
                format=_file_fmt,
                filter=_trace_filter,
                rotation="00:00",
                retention="30 days",
                compression="gz",
                encoding="utf-8",
                backtrace=True,
                diagnose=False,
            )
            # 错误日志单独文件
            loguru_logger.add(
                sink=os.path.join(self.logs_dir, "error_{time:YYYY-MM-DD}.log"),
                level="ERROR",
                format=_file_fmt,
                filter=_trace_filter,
                rotation="00:00",
                retention="90 days",
                compression="gz",
                encoding="utf-8",
                backtrace=True,
                diagnose=True,
            )

        return loguru_logger


log_config = LogConfig()
logger = log_config.setup()
