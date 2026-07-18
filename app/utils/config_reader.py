"""同步配置读取器 —— 委托 ProviderResolver，兼容 MySQL/SQLite

所有同步服务类通过此模块读取配置，内部全部委托 ProviderResolver，
不再直接使用 raw SQLite 连接。
"""

from app.utils.provider_resolver import ProviderResolver, _run_sync

# 旧 key 前缀 → provider_type
_PREFIX_TYPE_MAP = {
    "CF_": "cloudflare",
    "DYNADOT_": "dynadot",
    "OP_": "onepanel",
    "WP_": "onepanel",
    "HUBSTUDIO_": "hubstudio",
    "WOO_": "woo",
    "SHOPIFY_": "shopify",
}

# 旧 category 名 → provider_type
_CATEGORY_TYPE_MAP = {
    "cloudflare": "cloudflare",
    "dynadot": "dynadot",
    "onepanel": "onepanel",
    "hubstudio": "hubstudio",
    "woo": "woo",
    "shopify": "shopify",
}

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

# 反向映射（新 key → 旧 key），按 provider_type 分组
_REVERSE_KEY_MAP_BY_TYPE: dict = {}
for _old_key, _new_key in _KEY_MAP.items():
    for _prefix, _ptype in _PREFIX_TYPE_MAP.items():
        if _old_key.startswith(_prefix):
            _REVERSE_KEY_MAP_BY_TYPE.setdefault(_ptype, {})[_new_key] = _old_key
            break


def _resolve_old_key(name: str) -> tuple[str | None, str]:
    """解析旧 key 名称 → (provider_type, new_key)"""
    provider_type = None
    for prefix, ptype in _PREFIX_TYPE_MAP.items():
        if name.startswith(prefix):
            provider_type = ptype
            break
    new_key = _KEY_MAP.get(name, name)
    return provider_type, new_key


def get_provider_info(provider_type: str) -> dict:
    """同步获取当前解析到的 Provider 信息（用于日志记录）

    Returns:
        {"provider_id": int, "provider_name": str} 或 {} 如果无 Provider
    """
    async def _fetch():
        from app.models.config_provider import ConfigProvider
        p = await ConfigProvider.get_default(provider_type)
        if p:
            return {"provider_id": p.id, "provider_name": p.provider_name}
        return {}

    try:
        return _run_sync(_fetch())
    except Exception:
        return {}


def get_config(name: str, default: str = "") -> str:
    """同步获取单个配置值

    优先级：
    1. provider_config_item（通过 _KEY_MAP 转换旧 key → 新 key）
    2. 旧 config 表（fallback）
    3. 返回 default
    """
    provider_type, new_key = _resolve_old_key(name)

    async def _fetch():
        if provider_type:
            p = await ConfigProvider.get_default(provider_type)
            if p:
                item = await ProviderConfigItem.filter(
                    provider_id=p.id, config_key=new_key
                ).first()
                if item and item.config_value:
                    return item.config_value.strip().strip('`')
        # Fallback 到旧 config 表
        from app.models.config import Config
        row = await Config.filter(name=name, is_enabled=True).first()
        return row.value if row else default

    try:
        return _run_sync(_fetch())
    except Exception:
        return default


def get_config_map(category: str) -> dict:
    """同步获取某类别下所有配置项 → {旧_key: value}

    返回值 key 为旧命名格式（如 OP_URL），兼容现有 service
    """
    provider_type = _CATEGORY_TYPE_MAP.get(category, category)

    async def _fetch():
        result = {}
        from app.models.config_provider import ConfigProvider
        from app.models.config import Config

        p = await ConfigProvider.get_default(provider_type)
        if p:
            items = await ProviderConfigItem.filter(provider_id=p.id).all()
            if items:
                reverse_map = _REVERSE_KEY_MAP_BY_TYPE.get(provider_type, {})
                for item in items:
                    old_key = reverse_map.get(item.config_key, item.config_key)
                    result[old_key] = item.config_value.strip().strip('`')

                # 补充旧 config 表中 provider 缺失的 key
                old_rows = await Config.filter(
                    category=category, is_enabled=True
                ).order_by("sort_order").all()
                for row in old_rows:
                    if row.name not in result:
                        result[row.name] = row.value
                return result

        # Fallback 到旧 config 表
        rows = await Config.filter(category=category, is_enabled=True).order_by("sort_order").all()
        return {r.name: r.value for r in rows}

    try:
        return _run_sync(_fetch())
    except Exception:
        return {}

# 重新导出以便调用方统一引用
from app.utils.provider_resolver import ProviderResolver  # noqa: E402, F401
