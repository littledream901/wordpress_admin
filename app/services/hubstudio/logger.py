"""Agent 日志工厂"""

import logging
import os
from datetime import datetime


def get_agent_logger(name: str = "HubStudioAgent") -> logging.Logger:
    """获取 agent 日志器（仅写文件，控制台输出由 loguru 桥接统一处理）

    StreamHandler 已移除 —— agent 进程中若 loguru 桥接被意外激活
    （通过 app/__init__.py 依赖链），两条路线同时写控制台会导致重复日志。
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        log_dir = os.getenv("HUB_AGENT_LOG_DIR", "./logs/hubstudio")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"agent_{datetime.now().strftime('%Y%m%d')}.log")
        fmt = logging.Formatter("%(asctime)s | %(levelname)-6s | %(message)s")
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        # 安全网：如果 loguru 桥接未被激活（未来依赖链可能变化），
        # 追加 StreamHandler 确保控制台有输出
        if not _is_loguru_bridge_active():
            sh = logging.StreamHandler()
            sh.setFormatter(fmt)
            logger.addHandler(sh)
    return logger


def _is_loguru_bridge_active() -> bool:
    """检测 loguru 桥接（_InterceptHandler）是否已安装到根日志器"""
    for h in logging.getLogger().handlers:
        if type(h).__name__ == "_InterceptHandler":
            return True
    return False
