"""同步配置读取器 —— 兼容旧服务，内部委托 ProviderResolver

所有同步服务类通过此模块读取配置，不再直接访问 settings 或硬编码常量。
异步代码请直接使用 ProviderResolver。

旧 key → 新 key 映射：
- 旧：CF_API_TOKEN、OP_URL、HUBSTUDIO_BASE_URL 等（带前缀，兼容旧 config 表）
- 新：api_token、url、base_url 等（无前缀，存于 provider_config_items）
"""

import sqlite3
import os


# 数据库路径与 settings.BASE_DIR 一致：项目根目录下的 db.sqlite3
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(_BASE_DIR, "db.sqlite3")

# 旧 key → 新 key 映射（旧 config 表前缀 → provider_config_items 的 config_key）
_KEY_MAP = {
    # Cloudflare
    "CF_API_TOKEN": "api_token",
    "CF_ACCOUNT_ID": "account_id",
    "CF_PROXIED": "proxied",
    "CF_TTL": "ttl",
    "CF_TIMEOUT": "timeout",
    # Dynadot
    "DYNADOT_API_KEY": "api_key",
    "DYNADOT_API_URL": "api_url",
    "DYNADOT_TIMEOUT": "timeout",
    # 1Panel
    "OP_URL": "url",
    "OP_API_KEY": "api_key",
    "OP_WEBSITE_GROUP_ID": "website_group_id",
    "OP_WP_APP_ID": "wp_app_id",
    "OP_WP_APP_DETAIL_ID": "wp_app_detail_id",
    "OP_WP_APP_KEY": "wp_app_key",
    "OP_WP_APP_TYPE": "wp_app_type",
    "OP_WP_VERSION": "wp_version",
    "OP_MAX_RETRIES": "max_retries",
    "OP_RETRY_INTERVAL": "retry_interval",
    "OP_TIMEOUT": "timeout",
    "OP_AUTO_CLEAN_CONFLICT": "auto_clean_conflict_site",
    "OP_DELETE_SLEEP": "delete_sleep",
    "OP_OLD_SOURCE_DOMAIN": "old_source_domain",
    "OP_BACKUP_ACCOUNT_ID": "backup_account_id",
    "OP_TEMPLATE_BACKUP_PATH": "template_backup_path",
    "OP_DB_BACKUP_PATH": "db_backup_path",
    "OP_PANEL_BASE": "panel_base",
    "OP_WP_APP_ROOT": "wp_app_root",
    "OP_RESTORE_MODE": "restore_mode",
    "OP_AUTO_DETECT_WP_APP": "auto_detect_wp_app",
    "OP_WP_ADMIN_USER": "wp_admin_user",
    "OP_WP_ADMIN_EMAIL_PREFIX": "wp_admin_email_prefix",
    "OP_ENABLE_SSL": "enable_ssl",
    "OP_FORCE_HTTPS": "force_https",
    "OP_SSL_READY_TIMEOUT": "ssl_ready_timeout",
    "OP_RESTORE_ROOT_FILES": "restore_root_files",
    "OP_WOO_SCRIPT": "woo_script",
    "OP_CTX_SCRIPT": "ctx_script",
    "OP_WOO_FETCH_RETRIES": "woo_fetch_retries",
    "OP_WOO_FETCH_INTERVAL": "woo_fetch_interval",
    "OP_CTK_TOKEN": "ctk_token",
    "WP_CONTAINER_MEMORY_LIMIT": "wp_container_memory_limit",
    "WP_CONTAINER_MEMORY_UNIT": "wp_container_memory_unit",
    # HubStudio
    "HUBSTUDIO_BASE_URL": "base_url",
    "HUBSTUDIO_APP_ID": "app_id",
    "HUBSTUDIO_APP_SECRET": "app_secret",
    "HUBSTUDIO_GROUP_CODE": "group_code",
    "HUBSTUDIO_TIMEOUT": "timeout",
    "HUBSTUDIO_CONNECTOR_DIR": "connector_dir",
    "HUBSTUDIO_EXE_NAME": "exe_name",
    "HUBSTUDIO_HTTP_PORT": "http_port",
    "HUBSTUDIO_DEFAULT_PROXY_TYPE_NAME": "default_proxy_type_name",
    "HUBSTUDIO_DEFAULT_UI_LANGUAGE": "default_ui_language",
    "HUBSTUDIO_REAL_KERNEL_VERSION": "real_kernel_version",
    "HUBSTUDIO_ADMIN_SITE_NAME": "admin_site_name",
    "HUBSTUDIO_ADMIN_SITE_ALIAS": "admin_site_alias",
    "HUBSTUDIO_ADMIN_ACCOUNT_NAME": "admin_account_name",
    "HUBSTUDIO_ADMIN_ACCOUNT_PASSWORD": "admin_account_password",
    # Shopify
    "SHOPIFY_API_TIMEOUT": "request_timeout",
    "SHOPIFY_MAX_PRODUCTS_PER_SOURCE": "default_max_products",
}

# 旧 provider_type 名 → 新 provider_type（category 名称兼容）
_CATEGORY_TYPE_MAP = {
    "cloudflare": "cloudflare",
    "dynadot": "dynadot",
    "onepanel": "onepanel",
    "hubstudio": "hubstudio",
    "woo": "woo",
    "shopify": "shopify",
}

# 旧 key 前缀 → provider_type（WP_ 归属 pipeline，PIPELINE_ 归属 pipeline 等）
_PREFIX_TYPE_MAP = {
    "CF_": "cloudflare",
    "DYNADOT_": "dynadot",
    "OP_": "onepanel",
    "WP_": "pipeline",
    "HUBSTUDIO_": "hubstudio",
    "WOO_": "woo",
    "SHOPIFY_": "shopify",
    "PIPELINE_": "pipeline",
}

# 反向映射（新 key → 旧 key），按 provider_type 分组，避免同名 key（如 timeout）被覆盖
_REVERSE_KEY_MAP_BY_TYPE: dict = {}
for _old_key, _new_key in _KEY_MAP.items():
    for _prefix, _ptype in _PREFIX_TYPE_MAP.items():
        if _old_key.startswith(_prefix):
            _REVERSE_KEY_MAP_BY_TYPE.setdefault(_ptype, {})[_new_key] = _old_key
            break


def _get_provider_id(conn, provider_type: str) -> int:
    """获取默认 provider_id"""
    row = conn.execute(
        "SELECT id FROM config_provider WHERE provider_type=? AND is_default=1 AND status='active' LIMIT 1",
        (provider_type,)
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT id FROM config_provider WHERE provider_type=? AND status='active' ORDER BY priority DESC, id LIMIT 1",
            (provider_type,)
        ).fetchone()
    return row[0] if row else None


def get_provider_info(provider_type: str) -> dict:
    """同步获取当前解析到的 Provider 信息（用于日志记录）

    Returns:
        {"provider_id": int, "provider_name": str} 或 {} 如果无 Provider
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        pid = _get_provider_id(conn, provider_type)
        if not pid:
            return {}
        row = conn.execute(
            "SELECT provider_name FROM config_provider WHERE id=?", (pid,)
        ).fetchone()
        return {"provider_id": pid, "provider_name": row[0] if row else str(pid)}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


def get_config(name: str, default: str = "") -> str:
    """同步获取单个配置值

    优先级：
    1. provider_config_item（通过 _KEY_MAP 转换旧 key → 新 key）
    2. 旧 config 表（fallback）
    3. 返回 default
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        # 解析 provider_type
        provider_type = None
        for prefix, ptype in _PREFIX_TYPE_MAP.items():
            if name.startswith(prefix):
                provider_type = ptype
                break

        if provider_type:
            pid = _get_provider_id(conn, provider_type)
            if pid:
                # 先尝试用新 key 查
                new_key = _KEY_MAP.get(name, name)
                row = conn.execute(
                    "SELECT config_value FROM provider_config_item WHERE provider_id=? AND config_key=?",
                    (pid, new_key)
                ).fetchone()
                if row and row[0]:
                    return row[0].strip().strip('`')

        # Fallback 到旧 config 表
        row = conn.execute("SELECT value FROM config WHERE name=? AND is_enabled=1", (name,)).fetchone()
        return row[0] if row else default
    except sqlite3.OperationalError:
        return default
    finally:
        conn.close()


def get_config_map(category: str) -> dict:
    """同步获取某类别下所有配置项 → {旧_key: value}

    返回值 key 为旧命名格式（如 OP_URL），兼容现有 service
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        provider_type = _CATEGORY_TYPE_MAP.get(category, category)
        pid = _get_provider_id(conn, provider_type)
        if pid:
            rows = conn.execute(
                "SELECT config_key, config_value FROM provider_config_item WHERE provider_id=?",
                (pid,)
            ).fetchall()
            if rows:
                reverse_map = _REVERSE_KEY_MAP_BY_TYPE.get(provider_type, {})
                result = {}
                for new_key, value in rows:
                    old_key = reverse_map.get(new_key, new_key)
                    result[old_key] = value.strip().strip('`') if isinstance(value, str) else value

                # 合并旧 config 表中的数据（补充 provider 中缺失的 key）
                old_rows = conn.execute(
                    "SELECT name, value FROM config WHERE category=? AND is_enabled=1 ORDER BY sort_order",
                    (category,)
                ).fetchall()
                for old_key, old_value in old_rows:
                    if old_key not in result:
                        result[old_key] = old_value
                return result

        # Fallback 到旧 config 表
        rows = conn.execute(
            "SELECT name, value FROM config WHERE category=? AND is_enabled=1 ORDER BY sort_order",
            (category,)
        ).fetchall()
        return {k: v.strip().strip('`') if isinstance(v, str) else v for k, v in rows}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()
