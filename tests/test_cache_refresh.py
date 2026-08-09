"""快速验证 Provider 配置缓存刷新机制

用法：
    python tests/test_cache_refresh.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_cache_refresh():
    from tortoise import Tortoise
    from app.settings.config import settings
    from app.utils.provider_resolver import ProviderResolver
    from app.models.config_provider import ProviderConfigItem

    await Tortoise.init(config=settings.TORTOISE_ORM)

    print("\n" + "=" * 60)
    print("Provider 配置缓存刷新机制验证")
    print("=" * 60)

    # 1. 预加载配置到缓存
    print("\n[步骤 1] 预加载配置缓存...")
    await ProviderResolver.reload_cache()
    
    # 2. 读取 onepanel api_key 配置
    print("\n[步骤 2] 读取 onepanel api_key...")
    api_key_before = ProviderResolver.sync_get_config('onepanel', 'api_key', '')
    if api_key_before:
        print(f"  当前 API Key: {api_key_before[:8]}...{api_key_before[-4:]}")
    else:
        print("  [WARN] API Key 未配置")
    
    # 3. 模拟通过数据库直接修改配置
    print("\n[步骤 3] 模拟数据库直接修改配置（不触发缓存刷新）...")
    from app.models.config_provider import ConfigProvider
    provider = await ConfigProvider.filter(provider_type='onepanel', status='active').first()
    
    if not provider:
        print("  [FAIL] 未找到 active 状态的 onepanel Provider")
        await Tortoise.close_connections()
        return
    
    item = await ProviderConfigItem.filter(provider_id=provider.id, config_key='api_key').first()
    if item:
        original_value = item.config_value
        test_value = "TEST_KEY_" + original_value[-20:] if original_value else "TEST_KEY_12345678"
        item.config_value = test_value
        await item.save()
        print(f"  已将 API Key 临时改为: {test_value[:8]}...")
    else:
        print("  [FAIL] 未找到 api_key 配置项")
        await Tortoise.close_connections()
        return
    
    # 4. 从缓存读取（应该还是旧值）
    print("\n[步骤 4] 从缓存读取（未刷新，应该是旧值）...")
    api_key_cached = ProviderResolver.sync_get_config('onepanel', 'api_key', '')
    if api_key_cached == api_key_before:
        print(f"  [OK] 缓存未刷新，仍是旧值: {api_key_cached[:8]}...")
    else:
        print(f"  [WARN] 缓存值已变化（不应该）: {api_key_cached[:8]}...")
    
    # 5. 调用 reload_cache 刷新
    print("\n[步骤 5] 调用 reload_cache() 刷新缓存...")
    await ProviderResolver.reload_cache()
    
    # 6. 再次从缓存读取（应该是新值）
    print("\n[步骤 6] 从缓存读取（已刷新，应该是新值）...")
    api_key_refreshed = ProviderResolver.sync_get_config('onepanel', 'api_key', '')
    if api_key_refreshed == test_value:
        print(f"  [OK] 缓存已刷新，读到新值: {api_key_refreshed[:8]}...")
    else:
        print(f"  [FAIL] 缓存未生效，仍是: {api_key_refreshed[:8]}...")
    
    # 7. 恢复原始值
    print("\n[步骤 7] 恢复原始配置...")
    item.config_value = original_value
    await item.save()
    await ProviderResolver.reload_cache()
    print(f"  [OK] 已恢复为原始值")
    
    await Tortoise.close_connections()

    print("\n" + "=" * 60)
    if api_key_refreshed == test_value:
        print("验证结果: [PASS] 缓存刷新机制工作正常")
    else:
        print("验证结果: [FAIL] 缓存刷新机制异常")
    print("=" * 60 + "\n")


if __name__ == '__main__':
    asyncio.run(test_cache_refresh())
