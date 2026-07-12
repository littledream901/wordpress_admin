"""Agent 日志工厂"""

import logging
import os
from datetime import datetime


def get_agent_logger(name: str = "HubStudioAgent") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        log_dir = os.getenv("HUB_AGENT_LOG_DIR", "./logs/hubstudio")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"agent_{datetime.now().strftime('%Y%m%d')}.log")
        fmt = logging.Formatter("%(asctime)s | %(levelname)-6s | %(message)s")
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger
