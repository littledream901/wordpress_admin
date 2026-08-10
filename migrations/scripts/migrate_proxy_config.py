"""数据迁移脚本：从 ProviderConfigItem 迁移代理配置到 HubStudioProxyConfig 表

功能：
- 扫描所有 provider_type='hubstudio' 的 ConfigProvider
- 读取其关联的代理配置项（proxy_host, proxy_port 等）
- 创建对应的 HubStudioProxyConfig 记录
- 设置为该 Provider 的默认代理

执行方式：
    python -m migrations.scripts.migrate_proxy_config

注意：
- 脚本具有幂等性，已存在的代理配置会跳过
- 不会删除原有的 ProviderConfigItem 数据（可以保留作为备份）
"""
import asyncio
from tortoise import Tortoise
from app.settings.config import settings
from app.models.config_provider import ConfigProvider, ProviderConfigItem
from app.models.hubstudio_proxy import HubStudioProxyConfig

# 需要迁移的代理配置 key（含旧字段名，兼容历史数据）
PROXY_KEYS = [
    'use_fixed_proxy',
    'proxy_type_name',
    'proxy_host',
    'proxy_port',
    'proxy_account',
    'proxy_password',
    'as_dynamic_type',
    'ip_get_rule_type',
    'link_code',
    'ip_database_channel',
    'ip_protocol_type',
    # 新字段名
    'reference_country_code',
    'reference_city',
    'reference_region_code',
    # 旧字段名（迁移前的历史数据）
    'proxy_country_code',
    'proxy_city',
    'proxy_province',
]


def pick(data: dict, *keys: str, default=''):
    """按优先级取第一个非空值，兼容新旧字段名"""
    for key in keys:
        val = data.get(key)
        if val is not None and str(val).strip() != '':
            return val
    return default


def to_int(val, default: int = 0) -> int:
    """安全转 int"""
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return default


async def migrate_proxy_configs():
    """迁移代理配置"""
    print("=" * 80)
    print("HubStudio 代理配置迁移脚本")
    print("=" * 80)
    
    # 初始化数据库连接
    await Tortoise.init(config=settings.TORTOISE_ORM)
    await Tortoise.generate_schemas()
    
    # 查找所有 HubStudio Provider
    providers = await ConfigProvider.filter(provider_type='hubstudio').all()
    print(f"\n找到 {len(providers)} 个 HubStudio Provider\n")
    
    success_count = 0
    skip_count = 0
    error_count = 0
    
    for provider in providers:
        print(f"处理 Provider: {provider.provider_name} (ID: {provider.id})")
        
        # 读取所有代理配置项
        config_items = await ProviderConfigItem.filter(
            provider_id=provider.id,
            config_key__in=PROXY_KEYS
        ).all()
        
        if not config_items:
            print(f"  ⊗ 无代理配置项，跳过")
            skip_count += 1
            continue
        
        # 组装配置字典
        proxy_data = {}
        for item in config_items:
            proxy_data[item.config_key] = item.config_value
        
        print(f"  找到 {len(config_items)} 个代理配置项")
        
        # 检查必填字段
        if not all(k in proxy_data for k in ['proxy_host', 'proxy_port']):
            print(f"  ⊗ 缺少必填字段 (proxy_host/proxy_port)，跳过")
            error_count += 1
            continue
        
        # 检查是否已存在
        code = f"provider_{provider.id}_default"
        exists = await HubStudioProxyConfig.get_or_none(code=code)
        
        if exists:
            print(f"  ⊗ 已存在代理配置 {code}，跳过")
            skip_count += 1
            continue
        
        # 创建 HubStudioProxyConfig（兼容新旧字段名）
        try:
            proxy_config = await HubStudioProxyConfig.create(
                name=f"{provider.provider_name} - 默认代理",
                code=code,
                description=f"从 Provider {provider.id} 自动迁移",
                
                # 核心参数
                proxy_type_name=proxy_data.get('proxy_type_name', 'HTTP'),
                proxy_host=proxy_data['proxy_host'],
                proxy_port=to_int(proxy_data['proxy_port'], 15000),
                proxy_account=proxy_data.get('proxy_account', ''),
                proxy_password=proxy_data.get('proxy_password', ''),
                
                # 地理位置（优先使用新字段名，回退到旧字段名）
                reference_country_code=pick(proxy_data, 'reference_country_code', 'proxy_country_code', default='US'),
                reference_city=pick(proxy_data, 'reference_city', 'proxy_city', default=''),
                reference_region_code=pick(proxy_data, 'reference_region_code', 'proxy_province', default=''),
                
                # 动态代理
                use_fixed_proxy=proxy_data.get('use_fixed_proxy', 'true').lower() == 'true',
                as_dynamic_type=to_int(proxy_data.get('as_dynamic_type', 0)),
                ip_get_rule_type=to_int(proxy_data.get('ip_get_rule_type', 1)),
                link_code=proxy_data.get('link_code', ''),
                ip_database_channel=to_int(proxy_data.get('ip_database_channel', 0)),
                ip_protocol_type=to_int(proxy_data.get('ip_protocol_type', 0)),
                
                # 管理字段
                status='active',
                is_default=True,
                provider_id=provider.id
            )
            
            print(f"  ✓ 创建代理配置: {proxy_config.name} (ID: {proxy_config.id})")
            print(f"    - 代理地址: {proxy_config.proxy_host}:{proxy_config.proxy_port}")
            print(f"    - 代理类型: {proxy_config.proxy_type_name}")
            print(f"    - 国家: {proxy_config.reference_country_code}")
            success_count += 1
            
        except Exception as e:
            print(f"  ✗ 创建失败: {e}")
            error_count += 1
    
    await Tortoise.close_connections()
    
    # 统计结果
    print("\n" + "=" * 80)
    print("迁移完成！")
    print("=" * 80)
    print(f"总计: {len(providers)} 个 Provider")
    print(f"成功: {success_count} 个")
    print(f"跳过: {skip_count} 个")
    print(f"失败: {error_count} 个")
    print("=" * 80)
    print("\n提示：")
    print("1. 原有的 ProviderConfigItem 数据仍然保留，可作为备份")
    print("2. 新系统会优先使用 HubStudioProxyConfig 表的代理配置")
    print("3. 可以通过后台管理界面 /api/v1/hubstudio-proxy/list 查看迁移结果")
    print()


if __name__ == '__main__':
    asyncio.run(migrate_proxy_configs())
