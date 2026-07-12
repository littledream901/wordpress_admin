"""
onepanel_service.py 适配层

本文件已不再包含业务逻辑。所有代码已拆分到 onepanel/ 包中：
  - onepanel/utils.py          工具函数（mask_secret, normalize_domain, safe_alias 等）
  - onepanel/client.py         OnePanelAPI（HTTP 客户端）
  - onepanel/file_manager.py   OnePanelFileManager（文件操作）
  - onepanel/site_manager.py   OnePanelSiteManager（站点管理、WordPress 创建）
  - onepanel/ssl_manager.py    OnePanelSSLManager（SSL 证书）
  - onepanel/db_restorer.py    OnePanelDatabaseRestorer（数据库恢复）
  - onepanel/wp_restorer.py    OnePanelWordPressRestorer（WP 文件恢复/域名替换/Woo Key/CTX）
  - onepanel/rollback.py       RollbackManager（回滚管理器）

本适配层通过 importlib 动态加载拆分的模块，并注册到 sys.modules
以支持包内相对导入，同时保持外部 ``from app.services.onepanel_service import ...`` 的兼容性。
"""

import importlib.util
import os
import sys
import types

_BASE = os.path.dirname(os.path.abspath(__file__))
_PKG_DIR = os.path.join(_BASE, "onepanel")


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


# 注册包
_register_package("onepanel", os.path.join(_PKG_DIR, "__init__.py"))

# 注册子模块
_modules = {
    "onepanel.utils":           os.path.join(_PKG_DIR, "utils.py"),
    "onepanel.client":          os.path.join(_PKG_DIR, "client.py"),
    "onepanel.file_manager":    os.path.join(_PKG_DIR, "file_manager.py"),
    "onepanel.site_manager":    os.path.join(_PKG_DIR, "site_manager.py"),
    "onepanel.ssl_manager":     os.path.join(_PKG_DIR, "ssl_manager.py"),
    "onepanel.db_restorer":     os.path.join(_PKG_DIR, "db_restorer.py"),
    "onepanel.wp_restorer":     os.path.join(_PKG_DIR, "wp_restorer.py"),
    "onepanel.rollback":        os.path.join(_PKG_DIR, "rollback.py"),
}

for name, path in _modules.items():
    _register_module(name, path)

# 重新导出所有公开 API，保持外部导入兼容
from app.services.onepanel import *  # noqa: E402, F403
