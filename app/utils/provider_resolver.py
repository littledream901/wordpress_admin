"""ProviderResolver — 统一配置读取器

所有服务通过此类读取配置，不再直接依赖 get_config / get_config_map。
查询优先级：
1. resource_provider_bindings（资源绑定首选 provider）
2. config_provider.is_default（默认 provider）
3. 优先级最高的 active provider
"""

from app.models.config_provider import ConfigProvider, ProviderConfigItem, ResourceProviderBinding


class ProviderResolver:
    """统一配置解析器"""

    @classmethod
    async def get_config(cls, provider_type: str, config_key: str,
                         resource_type: str = "", resource_id: int = 0, default: str = "") -> str:
        """获取配置值

        Args:
            provider_type: 提供者类型 (cloudflare/onepanel/dynadot/...)
            config_key: 配置键名
            resource_type: 资源类型（可选，用于绑定查询）
            resource_id: 资源ID（可选）
            default: 默认值

        Returns:
            配置值字符串
        """
        provider = None
        if resource_type and resource_id:
            provider = await ConfigProvider.get_for_resource(resource_type, resource_id, provider_type)
        if not provider:
            provider = await ConfigProvider.get_default(provider_type)
        if not provider:
            return default

        item = await ProviderConfigItem.filter(provider_id=provider.id, config_key=config_key).first()
        return item.config_value if item else default

    @classmethod
    async def get_config_map(cls, provider_type: str,
                              resource_type: str = "", resource_id: int = 0) -> dict:
        """获取某 provider 类型的所有配置项 → {config_key: config_value}

        Args:
            provider_type: 提供者类型
            resource_type: 资源类型（可选）
            resource_id: 资源ID（可选）

        Returns:
            配置键值字典
        """
        provider = None
        if resource_type and resource_id:
            provider = await ConfigProvider.get_for_resource(resource_type, resource_id, provider_type)
        if not provider:
            provider = await ConfigProvider.get_default(provider_type)
        if not provider:
            return {}

        return await ProviderConfigItem.get_map(provider.id)

    @classmethod
    def sync_get_config(cls, provider_type: str, config_key: str, default: str = "") -> str:
        """同步版本 — 用于非 async 服务类 __init__"""
        import sqlite3
        db_path = "db.sqlite3"
        conn = sqlite3.connect(db_path)
        try:
            # 获取默认 provider
            row = conn.execute(
                "SELECT id FROM config_provider WHERE provider_type=? AND is_default=1 AND status='active' LIMIT 1",
                (provider_type,)
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT id FROM config_provider WHERE provider_type=? AND status='active' ORDER BY priority DESC, id LIMIT 1",
                    (provider_type,)
                ).fetchone()
            if not row:
                return default
            provider_id = row[0]
            val_row = conn.execute(
                "SELECT config_value FROM provider_config_item WHERE provider_id=? AND config_key=?",
                (provider_id, config_key)
            ).fetchone()
            return val_row[0].strip().strip('`') if val_row else default
        finally:
            conn.close()

    @classmethod
    def sync_get_config_map(cls, provider_type: str) -> dict:
        """同步版本 — 获取 provider 所有配置"""
        import sqlite3
        db_path = "db.sqlite3"
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT id FROM config_provider WHERE provider_type=? AND is_default=1 AND status='active' LIMIT 1",
                (provider_type,)
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT id FROM config_provider WHERE provider_type=? AND status='active' ORDER BY priority DESC, id LIMIT 1",
                    (provider_type,)
                ).fetchone()
            if not row:
                return {}
            provider_id = row[0]
            items = conn.execute(
                "SELECT config_key, config_value FROM provider_config_item WHERE provider_id=?",
                (provider_id,)
            ).fetchall()
            return {k: v.strip().strip('`') if isinstance(v, str) else v for k, v in items}
        finally:
            conn.close()
