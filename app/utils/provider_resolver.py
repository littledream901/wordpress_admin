"""ProviderResolver — 统一配置读取器

所有服务通过此类读取配置，不再直接依赖 get_config / get_config_map。
查询优先级：
1. resource_provider_bindings（资源绑定首选 provider）
2. config_provider.is_default（默认 provider）
3. 优先级最高的 active provider

类型安全方法（推荐使用）：
- get_str()  → 字符串
- get_int()  → int，转换失败返回 default
- get_bool() → bool，转换失败返回 default
- get_float()→ float，转换失败返回 default
"""

import asyncio
import concurrent.futures
import logging
from typing import Union

from app.models.config_provider import ConfigProvider, ProviderConfigItem

_log = logging.getLogger(__name__)


def _run_sync(coro):
    """在同步上下文中安全执行 async 协程（兼容事件循环内外场景）"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # 已在事件循环内 → 用线程池隔离执行
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=30)


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

    # ── 类型安全的便捷方法 ──

    @classmethod
    async def get_int(cls, provider_type: str, config_key: str,
                      resource_type: str = "", resource_id: int = 0, default: int = 0) -> int:
        """获取 int 配置，转换失败返回 default"""
        raw = await cls.get_config(provider_type, config_key, resource_type, resource_id, default=str(default))
        try:
            return int(raw)
        except (ValueError, TypeError):
            _log.warning(f"[ProviderResolver] {provider_type}.{config_key} 值 '{raw}' 无法转为 int，使用默认值 {default}")
            return default

    @classmethod
    async def get_bool(cls, provider_type: str, config_key: str,
                       resource_type: str = "", resource_id: int = 0, default: bool = False) -> bool:
        """获取 bool 配置，转换失败返回 default"""
        raw = await cls.get_config(provider_type, config_key, resource_type, resource_id, default=str(default).lower())
        if isinstance(raw, bool):
            return raw
        return raw.lower() in ("true", "1", "yes", "on")

    @classmethod
    async def get_float(cls, provider_type: str, config_key: str,
                        resource_type: str = "", resource_id: int = 0, default: float = 0.0) -> float:
        """获取 float 配置，转换失败返回 default"""
        raw = await cls.get_config(provider_type, config_key, resource_type, resource_id, default=str(default))
        try:
            return float(raw)
        except (ValueError, TypeError):
            _log.warning(f"[ProviderResolver] {provider_type}.{config_key} 值 '{raw}' 无法转为 float，使用默认值 {default}")
            return default

    @classmethod
    async def get_str(cls, provider_type: str, config_key: str,
                      resource_type: str = "", resource_id: int = 0, default: str = "") -> str:
        """获取字符串配置（等同 get_config）"""
        return await cls.get_config(provider_type, config_key, resource_type, resource_id, default=default)

    @classmethod
    def sync_get_config(cls, provider_type: str, config_key: str, default: str = "") -> str:
        """同步版本 — Tortoise 未初始化时静默返回 default"""
        try:
            return _run_sync(cls.get_config(provider_type, config_key, default=default))
        except Exception:
            return default

    @classmethod
    def sync_get_config_map(cls, provider_type: str) -> dict:
        """同步版本 — Tortoise 未初始化时静默返回 {}"""
        try:
            return _run_sync(cls.get_config_map(provider_type))
        except Exception:
            return {}
