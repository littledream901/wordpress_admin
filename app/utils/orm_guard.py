"""
Tortoise ORM 跨线程污染检测工具

由于 Tortoise ORM 的数据库连接绑定到 asyncio 事件循环，跨线程共享 ORM 模型实例
或在非主事件循环的线程中执行 asyncio.run() 访问 ORM 会导致：
- 数据静默丢失
- 连接状态错乱
- "Task attached to a different loop" 错误

本模块提供运行时检测能力，帮助快速定位跨线程 ORM 污染问题。
"""

import asyncio
import logging
import threading
from functools import wraps
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)

_log = logging.getLogger(__name__)

# ── 主事件循环线程标识（启动时自动记录） ──

_main_event_loop_id: int | None = None
_main_loop_thread_id: int | None = None


def _capture_main_loop():
    """记录主事件循环的线程 ID 和 loop ID（应在 FastAPI 启动时调用一次）"""
    global _main_event_loop_id, _main_loop_thread_id
    try:
        loop = asyncio.get_running_loop()
        _main_event_loop_id = id(loop)
        _main_loop_thread_id = threading.get_ident()
    except RuntimeError:
        _log.warning("[orm_guard] 未能捕获主事件循环（当前没有运行中的事件循环）")


def is_safe_for_orm() -> bool:
    """检查当前上下文是否可以安全访问 Tortoise ORM

    安全条件：
    - 在主事件循环线程中（协程内）
    - 不在任何事件循环中（纯同步脚本，会调用 asyncio.run()）

    危险条件：
    - 在非主事件循环的线程中运行了 asyncio.run() → 跨线程 ORM 污染
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return True  # 无事件循环 → 纯同步上下文，安全

    if _main_loop_thread_id is not None:
        if threading.get_ident() != _main_loop_thread_id:
            return False  # 在非主线程的事件循环中
    return True


def assert_safe_for_orm(caller: str = "") -> None:
    """断言当前上下文可以安全访问 ORM，否则抛出带诊断信息的 RuntimeError"""
    if is_safe_for_orm():
        return

    t = threading.current_thread()
    msg = (
        f"\n{'='*60}"
        f"\n[orm_guard] 检测到跨线程 ORM 访问！"
        f"\n  调用者: {caller or '未知'}"
        f"\n  当前线程: id={t.ident} name={t.name}"
        f"\n  主事件循环线程: id={_main_loop_thread_id} loop={_main_event_loop_id}"
        f"\n"
        f"\n  可能原因:"
        f"\n  1. 在 ThreadPoolExecutor 线程中直接或间接访问了 Tortoise ORM"
        f"\n  2. 在 run_in_executor 的 lambda/闭包中捕获了 ORM 模型实例"
        f"\n  3. 在事件循环内调用了 asyncio.run() 创建嵌套事件循环"
        f"\n"
        f"\n  修复方案:"
        f"\n  - run_in_executor 的闭包只做纯 HTTP 调用 / 纯计算"
        f"\n  - ORM 操作放回 async 上下文执行"
        f"\n  - 使用 loop.run_in_executor 前提取纯数据（str/int/dict），不传模型实例"
        f"\n{'='*60}"
    )
    _log.critical(msg)
    raise RuntimeError(msg)


def guard_thread_pool(fn: Callable[..., F]) -> Callable[..., F]:
    """装饰器：标记同步函数在线程池中运行，异常时自动记录诊断信息

    用法:
        @guard_thread_pool
        def _run_dns_sync(domain, platform, server_ip):
            ...
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            _log.error(
                "[orm_guard] 线程池函数 '%s' 异常（请确认未访问 ORM）: thread=%s",
                fn.__name__, threading.current_thread().name,
                exc_info=True,
            )
            raise

    return wrapper  # type: ignore[return-value]


def get_orm_diagnostics() -> dict:
    """返回当前 ORM 隔离状态的诊断报告

    返回:
        {main_loop_id, main_loop_thread_id, current_thread_id,
         current_thread_name, current_safe, has_running_loop, current_loop_id}
    """
    try:
        loop = asyncio.get_running_loop()
        has_running_loop = True
        current_loop_id = id(loop)
    except RuntimeError:
        has_running_loop = False
        current_loop_id = None

    return {
        "main_loop_id": _main_event_loop_id,
        "main_loop_thread_id": _main_loop_thread_id,
        "current_thread_id": threading.get_ident(),
        "current_thread_name": threading.current_thread().name,
        "current_safe": is_safe_for_orm(),
        "has_running_loop": has_running_loop,
        "current_loop_id": current_loop_id,
    }
