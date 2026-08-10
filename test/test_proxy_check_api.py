"""测试代理检测 API"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tortoise import Tortoise
from app.settings import TORTOISE_ORM
from app.controllers.hubstudio_proxy import hubstudio_proxy_controller
from app.models.hubstudio_proxy import HubStudioProxyConfig


async def test_check_api():
    """测试检测 API"""
    await Tortoise.init(config=TORTOISE_ORM)
    
    try:
        # 查找第一个代理
        proxy = await HubStudioProxyConfig.filter(is_deleted=False).first()
        
        if not proxy:
            print("❌ 没有找到可测试的代理")
            return
        
        print(f"\n测试代理 #{proxy.id}")
        print(f"地址: {proxy.proxy_host}:{proxy.proxy_port}")
        print(f"账号: {proxy.proxy_account}")
        print(f"当前状态: {proxy.status}")
        
        # 调用检测方法
        print("\n开始检测...")
        result = await hubstudio_proxy_controller.check_single_proxy(proxy.id)
        
        print("\n检测结果:")
        print(f"  代理 ID: {result.proxy_id}")
        print(f"  状态: {result.status}")
        print(f"  响应时间: {result.response_time} ms")
        print(f"  错误信息: {result.error_message}")
        
        # 检查数据库状态是否更新
        await proxy.refresh_from_db()
        print(f"\n数据库状态已更新为: {proxy.status}")
        
        if result.status == 'success':
            print("✅ 代理连接成功")
        else:
            print(f"❌ 代理连接失败: {result.error_message}")
        
    finally:
        await Tortoise.close_connections()


if __name__ == '__main__':
    print("=" * 60)
    print("测试代理检测 API")
    print("=" * 60)
    asyncio.run(test_check_api())
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
