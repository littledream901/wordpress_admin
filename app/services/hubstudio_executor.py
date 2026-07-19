"""HubStudio 本地执行器 — 适配层

本文件为 PyInstaller 打包的单一入口（Agent 通过 importlib 直接加载）。
内部委托到拆分后的 services/hubstudio/ 包，通过 importlib + sys.modules 注册
使包内相对导入正常工作，同时保持绕过 app/__init__.py。
"""

import importlib.util
import os
import sys
import types

_BASE = os.path.dirname(os.path.abspath(__file__))


def _register_package(name: str, path: str) -> types.ModuleType:
    """注册一个包到 sys.modules，使相对导入可用"""
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _register_module(name: str, path: str) -> types.ModuleType:
    """注册一个普通模块到 sys.modules"""
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=None,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── 1. 注册包模块（必须先于子模块，否则相对导入解析失败） ──

_register_package("hubstudio",         os.path.join(_BASE, "hubstudio", "__init__.py"))
_register_package("hubstudio.tasks",   os.path.join(_BASE, "hubstudio", "tasks", "__init__.py"))

# ── 2. 注册普通模块 ──

_register_module("hubstudio.client",            os.path.join(_BASE, "hubstudio", "client.py"))
_register_module("hubstudio.logger",            os.path.join(_BASE, "hubstudio", "logger.py"))
_register_module("hubstudio.runtime",           os.path.join(_BASE, "hubstudio", "runtime.py"))
_register_module("hubstudio.tasks.create_env",       os.path.join(_BASE, "hubstudio", "tasks", "create_env.py"))
_register_module("hubstudio.tasks.update_env",       os.path.join(_BASE, "hubstudio", "tasks", "update_env.py"))
_register_module("hubstudio.tasks.create_account",   os.path.join(_BASE, "hubstudio", "tasks", "create_account.py"))
_register_module("hubstudio.tasks.wp_login",  os.path.join(_BASE, "hubstudio", "tasks", "wp_login.py"))
_register_module("hubstudio.tasks.gmc_check",        os.path.join(_BASE, "hubstudio", "tasks", "gmc_check.py"))
_register_module("hubstudio.tasks.open_env",       os.path.join(_BASE, "hubstudio", "tasks", "open_env.py"))
_register_module("hubstudio.executor",         os.path.join(_BASE, "hubstudio", "executor.py"))

# ── Re-export 全部公开接口（与原单体文件完全一致） ──

_hub = sys.modules["hubstudio.executor"]
HubStudioLocalExecutor = _hub.HubStudioLocalExecutor
create_executor_from_config = _hub.create_executor_from_config

_log = sys.modules["hubstudio.logger"]
get_agent_logger = _log.get_agent_logger

_rt = sys.modules["hubstudio.runtime"]
HubStudioRuntime = _rt.HubStudioRuntime

_cl = sys.modules["hubstudio.client"]
HubStudioAPIError = _cl.HubStudioAPIError
HubStudioClient = _cl.HubStudioClient

__all__ = [
    "HubStudioAPIError",
    "HubStudioClient",
    "HubStudioLocalExecutor",
    "HubStudioRuntime",
    "create_executor_from_config",
    "get_agent_logger",
]
