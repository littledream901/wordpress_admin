"""测试代理批量操作、软删除、回收站功能"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from tortoise import Tortoise
from app.settings.config import settings
from app.models.hubstudio_proxy import HubStudioProxyConfig
from app.models.site_pipeline import Site
from app.controllers.hubstudio_proxy import hubstudio_proxy_controller
from app.schemas.hubstudio_proxy import ProxyBatchDelete, ProxyBatchCheck


async def init_db():
    """初始化数据库连接"""
    await Tortoise.init(config=settings.TORTOISE_ORM)


async def cleanup():
    """清理测试数据"""
    await Tortoise.close_connections()


async def test_batch_delete():
    """测试批量软删除"""
    print("\n=== 测试批量软删除 ===")
    
    # 创建测试代理
    proxy1 = await HubStudioProxyConfig.create(
        proxy_host="test1.example.com",
        proxy_port=8001,
        proxy_account="user1",
        proxy_password="pass1",
        description="测试代理1"
    )
    proxy2 = await HubStudioProxyConfig.create(
        proxy_host="test2.example.com",
        proxy_port=8002,
        proxy_account="user2",
        proxy_password="pass2",
        description="测试代理2"
    )
    
    print(f"✓ 创建测试代理: #{proxy1.id}, #{proxy2.id}")
    
    # 批量删除
    result = await hubstudio_proxy_controller.batch_delete(
        ProxyBatchDelete(proxy_ids=[proxy1.id, proxy2.id])
    )
    print(f"✓ 批量删除结果: {result}")
    
    # 验证软删除
    p1 = await HubStudioProxyConfig.get(id=proxy1.id)
    p2 = await HubStudioProxyConfig.get(id=proxy2.id)
    assert p1.is_deleted == True, "代理1应该被标记为软删除"
    assert p2.is_deleted == True, "代理2应该被标记为软删除"
    assert p1.deleted_at is not None, "代理1应该有删除时间"
    print(f"✓ 验证软删除状态: is_deleted=True, deleted_at={p1.deleted_at}")
    
    # 验证不出现在普通列表
    total, data = await hubstudio_proxy_controller.list_proxies(page=1, page_size=100)
    proxy_ids = [item['id'] for item in data]
    assert proxy1.id not in proxy_ids, "软删除的代理不应该出现在普通列表"
    print("✓ 软删除的代理已从普通列表隐藏")
    
    # 清理
    await proxy1.delete()
    await proxy2.delete()
    print("✓ 清理测试数据完成\n")


async def test_batch_check():
    """测试批量检测代理"""
    print("\n=== 测试批量检测代理 ===")
    
    # 创建测试代理（使用无效地址）
    proxy1 = await HubStudioProxyConfig.create(
        proxy_host="invalid-proxy-1.test",
        proxy_port=9001,
        proxy_account="test",
        proxy_password="test",
        description="无效代理1"
    )
    proxy2 = await HubStudioProxyConfig.create(
        proxy_host="invalid-proxy-2.test",
        proxy_port=9002,
        proxy_account="test",
        proxy_password="test",
        description="无效代理2"
    )
    
    print(f"✓ 创建测试代理: #{proxy1.id}, #{proxy2.id}")
    
    # 批量检测（预期失败）
    result = await hubstudio_proxy_controller.batch_check(
        ProxyBatchCheck(proxy_ids=[proxy1.id, proxy2.id])
    )
    print(f"✓ 批量检测结果: 成功={result['success_count']}, 失败={result['failed_count']}")
    if result['results']:
        print(f"  示例结果: {result['results'][0]}")  # 打印第一个结果
    
    # 验证状态更新
    p1 = await HubStudioProxyConfig.get(id=proxy1.id)
    assert p1.status in ['testing', 'failed', 'disabled'], f"代理状态应该更新，当前: {p1.status}"
    print(f"✓ 代理状态已更新: {p1.status}")
    
    # 清理
    await proxy1.delete()
    await proxy2.delete()
    print("✓ 清理测试数据完成\n")


async def test_single_check():
    """测试单条代理检测"""
    print("\n=== 测试单条代理检测 ===")
    
    proxy = await HubStudioProxyConfig.create(
        proxy_host="single-test.invalid",
        proxy_port=7777,
        proxy_account="test",
        proxy_password="test",
        description="单条检测测试"
    )
    print(f"✓ 创建测试代理: #{proxy.id}")
    
    result = await hubstudio_proxy_controller.check_single_proxy(proxy.id)
    print(f"✓ 检测结果: status={result.status}, latency={result.response_time}ms")
    print(f"  消息: {result.error_message}")
    
    # 清理
    await proxy.delete()
    print("✓ 清理测试数据完成\n")


async def test_assigned_sites():
    """测试获取分配站点列表"""
    print("\n=== 测试获取分配站点列表 ===")
    
    # 创建测试代理
    proxy = await HubStudioProxyConfig.create(
        proxy_host="test-assigned.example.com",
        proxy_port=8888,
        description="分配测试代理"
    )
    print(f"✓ 创建测试代理: #{proxy.id}")
    
    # 查找现有站点并分配代理
    sites = await Site.filter(is_deleted=False).limit(2)
    if sites:
        for site in sites:
            site.proxy_config_id = proxy.id
            await site.save(update_fields=['proxy_config_id'])
        print(f"✓ 将 {len(sites)} 个站点分配给代理")
        
        # 获取分配站点列表
        assigned = await hubstudio_proxy_controller.get_assigned_sites(proxy.id)
        print(f"✓ 获取分配站点: {len(assigned['sites'])} 个")
        if assigned['sites']:
            print(f"  示例: {assigned['sites'][0]}")
        
        # 恢复站点代理配置
        for site in sites:
            site.proxy_config_id = 0
            await site.save(update_fields=['proxy_config_id'])
    else:
        print("! 没有可用站点，跳过分配测试")
    
    # 清理
    await proxy.delete()
    print("✓ 清理测试数据完成\n")


async def test_recycle_workflow():
    """测试完整回收站流程"""
    print("\n=== 测试回收站完整流程 ===")
    
    # 1. 创建代理
    proxy = await HubStudioProxyConfig.create(
        proxy_host="recycle-test.example.com",
        proxy_port=6666,
        description="回收站测试"
    )
    print(f"✓ 创建测试代理: #{proxy.id}")
    
    # 2. 软删除
    await hubstudio_proxy_controller.soft_remove(proxy.id)
    proxy = await HubStudioProxyConfig.get(id=proxy.id)
    assert proxy.is_deleted == True
    print("✓ 软删除成功")
    
    # 3. 回收站列表
    from app.controllers.hubstudio_proxy import proxy_controller
    total, objs = await proxy_controller.list_deleted(page=1, page_size=10, order=['-deleted_at'])
    assert total > 0, "回收站应该有数据"
    print(f"✓ 回收站列表: 共 {total} 条")
    
    # 4. 恢复
    await proxy_controller.restore(proxy.id)
    proxy = await HubStudioProxyConfig.get(id=proxy.id)
    assert proxy.is_deleted == False
    assert proxy.deleted_at is None
    print("✓ 恢复成功")
    
    # 5. 再次软删除
    await proxy_controller.soft_remove(proxy.id)
    
    # 6. 彻底删除
    await proxy_controller.remove(proxy.id)
    proxy = await HubStudioProxyConfig.get_or_none(id=proxy.id)
    assert proxy is None, "代理应该已被彻底删除"
    print("✓ 彻底删除成功\n")


async def test_site_delete_cascade():
    """测试站点删除时代理软删除联动"""
    print("\n=== 测试站点删除联动代理软删除 ===")
    
    # 创建测试代理
    proxy = await HubStudioProxyConfig.create(
        proxy_host="cascade-test.example.com",
        proxy_port=5555,
        description="联动删除测试"
    )
    print(f"✓ 创建测试代理: #{proxy.id}")
    
    # 查找测试站点
    site = await Site.filter(is_deleted=False).first()
    if not site:
        print("! 没有可用站点，跳过联动删除测试")
        await proxy.delete()
        return
    
    original_proxy_id = site.proxy_config_id
    site.proxy_config_id = proxy.id
    await site.save(update_fields=['proxy_config_id'])
    print(f"✓ 将站点 #{site.id} 分配给代理 #{proxy.id}")
    
    # 软删除站点（触发联动）
    result = await hubstudio_proxy_controller.soft_delete_by_site(site.id)
    print(f"✓ 软删除联动: 影响 {result} 条代理")
    
    # 验证代理被软删除
    proxy = await HubStudioProxyConfig.get(id=proxy.id)
    assert proxy.is_deleted == True, "代理应该被软删除"
    print("✓ 代理已自动软删除")
    
    # 恢复站点代理配置
    site.proxy_config_id = original_proxy_id
    await site.save(update_fields=['proxy_config_id'])
    
    # 清理
    await proxy.delete()
    print("✓ 清理测试数据完成\n")


async def main():
    """运行所有测试"""
    try:
        await init_db()
        print("=" * 60)
        print("开始测试代理批量操作、软删除和回收站功能")
        print("=" * 60)
        
        await test_batch_delete()
        await test_batch_check()
        await test_single_check()
        await test_assigned_sites()
        await test_recycle_workflow()
        await test_site_delete_cascade()
        
        print("=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await cleanup()


if __name__ == "__main__":
    asyncio.run(main())
