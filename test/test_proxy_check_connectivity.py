"""测试代理检测连通性"""
import asyncio
import httpx
from datetime import datetime


async def test_proxy_connectivity():
    """测试 httpx AsyncHTTPTransport 代理连接"""
    
    # 测试代理（使用一个公开测试代理）
    test_proxies = [
        {
            'host': '163.123.201.136',
            'port': 5921,
            'account': 'powygrwn',
            'password': 'mbe5zxysoih3'
        }
    ]
    
    for proxy_info in test_proxies:
        proxy_url = f"http://{proxy_info['account']}:{proxy_info['password']}@{proxy_info['host']}:{proxy_info['port']}"
        print(f"\n测试代理: {proxy_info['host']}:{proxy_info['port']}")
        print(f"代理 URL: {proxy_url}")
        
        start_time = datetime.now()
        try:
            transport = httpx.AsyncHTTPTransport(proxy=proxy_url)
            async with httpx.AsyncClient(transport=transport, timeout=10.0, follow_redirects=True) as client:
                response = await client.get("http://www.google.com")
                response_time = (datetime.now() - start_time).total_seconds() * 1000
                
                print(f"✅ 连接成功")
                print(f"   状态码: {response.status_code}")
                print(f"   响应时间: {response_time:.2f} ms")
                print(f"   内容长度: {len(response.content)} bytes")
                
        except asyncio.TimeoutError:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            print(f"❌ 连接超时")
            print(f"   耗时: {response_time:.2f} ms")
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            print(f"❌ 连接失败")
            print(f"   错误: {type(e).__name__}: {str(e)}")
            print(f"   耗时: {response_time:.2f} ms")


if __name__ == '__main__':
    print("=" * 60)
    print("测试 httpx AsyncHTTPTransport 代理连通性")
    print("=" * 60)
    asyncio.run(test_proxy_connectivity())
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
