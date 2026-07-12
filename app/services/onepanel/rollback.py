import logging
from typing import Callable, List, Tuple

from .utils import _log


class RollbackManager:
    """回滚管理器：按执行顺序逆向回滚已完成的步骤"""
    def __init__(self, name: str = ""):
        self.name = name
        self.steps: List[Tuple[Callable, tuple, dict]] = []

    def add(self, fn: Callable, *args, **kwargs):
        self.steps.append((fn, args, kwargs))

    def run(self):
        _log.info("回滚 %s: 共 %s 步", self.name or "unnamed", len(self.steps))
        for fn, args, kwargs in reversed(self.steps):
            try:
                _log.info("回滚步骤: %s", fn.__name__)
                fn(*args, **kwargs)
            except Exception as exc:
                _log.error("回滚步骤 %s 失败（继续执行后续回滚）: %s", fn.__name__, exc)
