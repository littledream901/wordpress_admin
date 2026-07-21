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

import logging as std_logging
import os
import sys
import threading
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

# 文件日志带线程上下文，用于跨线程 ORM 污染事后排查
_file_fmt = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} | "
    "{extra[trace_id]} | {extra[thread_ctx]} | {message}"
)


def _trace_filter(record: dict) -> bool:
    """注入 trace_id；文件格式额外注入线程上下文（跨线程 ORM 污染排查用）"""
    import asyncio

    tid = _trace_id.get()
    record["extra"]["trace_id"] = tid or "-"

    t = threading.current_thread()
    try:
        loop = asyncio.get_running_loop()
        loop_info = f"loop={id(loop)}"
    except RuntimeError:
        loop_info = "no_loop"
    record["extra"]["thread_ctx"] = f"{t.name}(main={t is threading.main_thread()}) {loop_info}"

    return True


# ── 标准 logging → loguru 桥接 ──

class _InterceptHandler(std_logging.Handler):
    """将标准 logging 日志重定向到 loguru，统一输出格式"""

    def emit(self, record: std_logging.LogRecord):
        # 找到调用栈中第一个非 logging 模块的帧作为 caller
        try:
            level = loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = std_logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == std_logging.__file__:
            frame = frame.f_back
            depth += 1

        loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


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

        # ── 将标准 logging 重定向到 loguru ──
        root_logger = std_logging.getLogger()
        root_logger.handlers = [_InterceptHandler()]
        root_logger.setLevel(self.level)

        # 抑制第三方库噪音
        std_logging.getLogger("asyncmy").setLevel(std_logging.WARNING)
        std_logging.getLogger("tortoise.db_client").setLevel(std_logging.WARNING)
        # uvicorn 有自己的 LOGGING_CONFIG，不做额外处理（避免重复日志）

        return loguru_logger


log_config = LogConfig()
logger = log_config.setup()
