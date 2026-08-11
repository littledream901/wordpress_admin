"""HubStudio 本地执行器 — 编排层

按 job_type 分发到独立的任务模块执行。
"""

import json
from typing import Any, Dict, Optional, Tuple

from .runtime import HubStudioRuntime
from .tasks import (
    create_account,
    create_env,
    gmc_check,
    open_env,
    update_env,
    wp_login,
)

# ══════════════════════════════════════════════════════════════════════════
# 为了从旧 hubstudio_executor.py 拆分后保持向后兼容，
# 这些常量/函数同样在 __init__.py 中 re-export
# ══════════════════════════════════════════════════════════════════════════

from .tasks._common import REMARK_FIELD_MAP
# 从 create_env 导出的工具函数
from .tasks.create_env import (
    build_container_name,
    get_existing_env_by_domain,
    get_tag_code_by_name,
)
# 从 create_account 导出的工具函数
from .tasks.create_account import (
    ADD_ACCOUNT_HOST,
    ADD_ACCOUNT_PATH,
    ADD_ACCOUNT_PORT,
    ADD_ACCOUNT_TIMEOUT,
    calc_backoff,
    is_retryable_error,
)


class HubStudioLocalExecutor:
    """本地执行器：按 job_type 分发到任务模块

    代理配置优先级（从高到低）：
    1. payload.proxy_config — 站点绑定的代理配置
    2. payload.proxy_type_name 等散落字段 — 逐字段传入
    3. 空 — 使用 HubStudio Provider 默认代理
    """

    def __init__(self, runtime: HubStudioRuntime):
        self.rt = runtime
        self.logger = runtime.logger
        self.default_proxy_type = "不使用代理"
        self.default_ui_language = "en"
        self.admin_site_name = "自定义平台"
        self.admin_site_alias = "WordPress后台"
        self.admin_account_name = "admin"
        self.admin_account_password = ""

    # ── 执行入口 ──

    def execute(self, job: dict) -> dict:
        """根据 job_type 分发到任务模块执行"""
        job_type = job.get("job_type", "")
        payload = job.get("payload") or job.get("payload_json", {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}

        _map = {
            "create_env": create_env.execute_create_env,
            "create_gmail_env": create_env.execute_create_env,  # 复用统一逻辑
            "create_account": create_account.execute_create_account,
            "update_env": update_env.execute_update_env,
            "wp_login": wp_login.execute_wp_login,
            "gmc_check": gmc_check.execute_gmc_check,
            "open_env": open_env.execute_open_env,
        }
        handler = _map.get(job_type)
        if handler:
            return handler(self, job, payload)
        return {"status": "failed", "error": f"Unsupported job_type: {job_type}"}

    # ── 向后兼容：保留旧方法名，委托到新模块 ──

    def execute_create_env(self, job: dict, payload: dict) -> dict:
        return create_env.execute_create_env(self, job, payload)

    def execute_create_account(self, job: dict, payload: dict) -> dict:
        return create_account.execute_create_account(self, job, payload)

    def execute_update_env(self, job: dict, payload: dict) -> dict:
        return update_env.execute_update_env(self, job, payload)

    def execute_wp_login(self, job: dict, payload: dict) -> dict:
        return wp_login.execute_wp_login(self, job, payload)

    def execute_gmc_check(self, job: dict, payload: dict) -> dict:
        return gmc_check.execute_gmc_check(self, job, payload)

    # ── 工具方法（向后兼容） ──

    build_container_name = staticmethod(build_container_name)
    get_tag_code_by_name = get_tag_code_by_name
    get_existing_env_by_domain = get_existing_env_by_domain

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        return is_retryable_error(error)

    @staticmethod
    def _calc_backoff(attempt: int, base: float = 2.0, max_delay: float = 20.0) -> float:
        return calc_backoff(attempt, base, max_delay)

    def _call_add_account_direct(self, create_data: dict, max_retries: int = 5) -> dict:
        return create_account.call_add_account_direct(self, create_data, max_retries)

    def _build_proxy_config(self, payload: dict) -> dict:
        return update_env.build_proxy_config(self, payload)

    def _query_gmc_status(self, browser) -> dict:
        return gmc_check._query_gmc_status(browser, self)

    # 常量别名（向后兼容）
    ADD_ACCOUNT_HOST = ADD_ACCOUNT_HOST
    ADD_ACCOUNT_PORT = ADD_ACCOUNT_PORT
    ADD_ACCOUNT_PATH = ADD_ACCOUNT_PATH
    ADD_ACCOUNT_TIMEOUT = ADD_ACCOUNT_TIMEOUT
    REMARK_FIELD_MAP = REMARK_FIELD_MAP


def create_executor_from_config(config: dict) -> Tuple[HubStudioRuntime, HubStudioLocalExecutor]:
    """从配置字典创建执行器实例"""
    from .logger import get_agent_logger

    logger = get_agent_logger()
    runtime = HubStudioRuntime(config, logger)
    executor = HubStudioLocalExecutor(runtime)

    executor.default_proxy_type = config.get("default_proxy_type_name", "不使用代理")
    executor.default_ui_language = config.get("default_ui_language", "en")
    executor.admin_site_name = config.get("admin_site_name", "自定义平台")
    executor.admin_site_alias = config.get("admin_site_alias", "WordPress后台")
    executor.admin_account_name = config.get("admin_account_name", "admin")
    executor.admin_account_password = config.get("admin_account_password", "")

    logger.info("执行器初始化完成: 代理配置将优先使用站点绑定的代理，未绑定时使用 Provider 默认代理")
    return runtime, executor
