"""HubStudio 代理配置功能测试

测试覆盖：
1. 数据库表结构验证
2. 代理配置查询优先级
3. 字段映射正确性
"""
import asyncio
from tortoise import Tortoise
from app.settings.config import settings


async def test_proxy_table_exists():
    """测试代理配置表是否存在"""
    print("\n=== 测试 1: 验证数据库表结构 ===")
    await Tortoise.init(config=settings.TORTOISE_ORM)
    
    conn = Tortoise.get_connection("default")
    
    # 检查 hubstudio_proxy_config 表
    result = await conn.execute_query_dict(
        "SELECT COUNT(*) as cnt FROM information_schema.tables "
        "WHERE table_name = 'hubstudio_proxy_config'"
    )
    
    if result and result[0]['cnt'] > 0:
        print("✓ hubstudio_proxy_config 表存在")
        
        # 检查关键字段
        fields = await conn.execute_query_dict(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'hubstudio_proxy_config' "
            "AND column_name IN ('reference_country_code', 'reference_city', 'reference_region_code', "
            "'link_code', 'ip_database_channel', 'ip_protocol_type')"
        )
        
        field_names = [f['column_name'] for f in fields]
        expected = ['reference_country_code', 'reference_city', 'reference_region_code', 
                    'link_code', 'ip_database_channel', 'ip_protocol_type']
        
        for field in expected:
            if field in field_names:
                print(f"  ✓ 字段 {field} 存在")
            else:
                print(f"  ✗ 字段 {field} 缺失")
    else:
        print("✗ hubstudio_proxy_config 表不存在，请先执行 SQL 迁移脚本")
    
    # 检查 Site 表字段
    result = await conn.execute_query_dict(
        "SELECT COUNT(*) as cnt FROM information_schema.columns "
        "WHERE table_name = 'site_pipeline_site' AND column_name = 'proxy_config_id'"
    )
    
    if result and result[0]['cnt'] > 0:
        print("✓ Site 表 proxy_config_id 字段存在")
    else:
        print("✗ Site 表 proxy_config_id 字段缺失")
    
    await Tortoise.close_connections()


async def test_proxy_priority():
    """测试代理配置查询优先级"""
    print("\n=== 测试 2: 代理配置查询优先级 ===")
    await Tortoise.init(config=settings.TORTOISE_ORM)
    
    from app.models.hubstudio_proxy import HubStudioProxyConfig
    
    # 查询全局默认代理
    global_proxy = await HubStudioProxyConfig.get_or_none(
        provider_id=0,
        is_default=True,
        status='active'
    )
    
    if global_proxy:
        print(f"✓ 找到全局默认代理: {global_proxy.name}")
        print(f"  - 代理地址: {global_proxy.proxy_host}:{global_proxy.proxy_port}")
        print(f"  - 国家代码: {global_proxy.reference_country_code}")
        print(f"  - 城市: {global_proxy.reference_city}")
        print(f"  - 省份: {global_proxy.reference_region_code}")
    else:
        print("✗ 未找到全局默认代理，请插入默认配置")
    
    # 统计所有代理配置
    total = await HubStudioProxyConfig.all().count()
    print(f"\n当前代理配置总数: {total}")
    
    await Tortoise.close_connections()


async def test_field_mapping():
    """测试字段映射正确性"""
    print("\n=== 测试 3: 字段映射正确性 ===")
    
    from app.services.hubstudio.tasks.update_env import PROXY_FIELD_MAP
    
    # 模拟代理配置数据（数据库格式）
    mock_proxy = {
        "proxy_type_name": "HTTP",
        "proxy_host": "server.iphtml.biz",
        "proxy_port": 15000,
        "proxy_account": "uid-27498-zone-hubstudio",
        "proxy_password": "test123",
        "reference_country_code": "US",
        "reference_city": "New York",
        "reference_region_code": "CA",
        "as_dynamic_type": 0,
        "ip_get_rule_type": 1,
        "link_code": "",
        "ip_database_channel": 0,
        "ip_protocol_type": 0,
    }
    
    # 测试字段映射（模拟 build_proxy_config 的逻辑）
    mapped = {}
    for api_key, db_key in PROXY_FIELD_MAP.items():
        if db_key in mock_proxy:
            mapped[api_key] = mock_proxy[db_key]
    
    expected_keys = [
        'proxyTypeName', 'proxyHost', 'proxyPort', 
        'proxyAccount', 'proxyPassword',
        'referenceCountryCode', 'referenceCity', 'referenceRegionCode',
        'asDynamicType', 'ipGetRuleType', 'linkCode',
        'ipDatabaseChannel', 'ipProtocolType'
    ]
    
    all_ok = True
    for key in expected_keys:
        if key in mapped:
            print(f"✓ {key}: {mapped[key]}")
        else:
            print(f"✗ {key}: 缺失")
            all_ok = False
    
    if all_ok:
        print("\n✓ 所有字段映射正确")
    else:
        print("\n✗ 存在字段映射问题")


async def main():
    """运行所有测试"""
    print("=" * 60)
    print("HubStudio 代理配置功能测试")
    print("=" * 60)
    
    try:
        await test_proxy_table_exists()
        await test_proxy_priority()
        await test_field_mapping()
        
        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(main())
