"""诊断 Cloudflare 403 权限错误

使用方法：
    python test/diagnose_cloudflare_403.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from tortoise import Tortoise

from app.settings import TORTOISE_ORM
from app.models.config_provider import ConfigProvider, ProviderConfigItem


async def diagnose():
    """诊断 Cloudflare 配置和权限"""
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas()

    print("=" * 80)
    print("Cloudflare 403 权限诊断")
    print("=" * 80)
    print()

    # 1. 查找 Cloudflare Provider
    providers = await ConfigProvider.filter(
        provider_type='cloudflare',
        is_deleted=False
    ).order_by('-is_default', '-priority')

    if not providers:
        print("❌ 未找到任何 Cloudflare Provider 配置")
        print("   请在管理后台【配置中心】→【Provider 管理】中添加 Cloudflare 配置")
        await Tortoise.close_connections()
        return

    print(f"✓ 找到 {len(providers)} 个 Cloudflare Provider:\n")
    
    for provider in providers:
        print(f"  Provider ID: {provider.id}")
        print(f"  名称: {provider.provider_name}")
        print(f"  状态: {provider.status}")
        print(f"  是否默认: {'是' if provider.is_default else '否'}")
        print(f"  优先级: {provider.priority}")
        print()

    # 2. 检查默认 Provider 的配置
    default_provider = await ConfigProvider.get_default('cloudflare')
    if not default_provider:
        print("❌ 未找到默认 Cloudflare Provider")
        await Tortoise.close_connections()
        return

    print(f"当前使用的 Provider: #{default_provider.id} {default_provider.provider_name}")
    print("-" * 80)

    # 3. 读取配置项
    config_map = await ProviderConfigItem.get_map(default_provider.id)
    
    api_token = config_map.get('api_token', '')
    account_id = config_map.get('account_id', '')
    
    print("\n配置项检查:")
    print(f"  api_token: {'✓ 已配置' if api_token else '❌ 未配置'} ({len(api_token) if api_token else 0} 字符)")
    if api_token:
        print(f"             {api_token[:10]}...{api_token[-6:]}" if len(api_token) > 16 else f"             {api_token}")
    
    print(f"  account_id: {'✓ 已配置' if account_id else '❌ 未配置'} ({len(account_id) if account_id else 0} 字符)")
    if account_id:
        print(f"              {account_id}")
    print()

    if not api_token or not account_id:
        print("❌ 配置不完整，请补全 api_token 和 account_id")
        await Tortoise.close_connections()
        return

    # 4. 测试 API Token 权限
    print("-" * 80)
    print("开始测试 Cloudflare API 权限...\n")
    
    client = httpx.Client(http2=True, timeout=30.0)
    client.headers.update({
        'Authorization': f'Bearer {api_token}',
        'Content-Type': 'application/json',
    })

    base_url = 'https://api.cloudflare.com/client/v4'

    # 测试 1: 验证 Token
    print("1. 验证 Token 有效性...")
    try:
        resp = client.get(f'{base_url}/user/tokens/verify')
        data = resp.json()
        if data.get('success'):
            print("   ✓ Token 有效")
            result = data.get('result', {})
            print(f"   Token ID: {result.get('id', 'N/A')}")
            print(f"   状态: {result.get('status', 'N/A')}")
        else:
            errors = data.get('errors', [])
            print(f"   ❌ Token 验证失败")
            for err in errors:
                print(f"      - {err.get('message', err)}")
            await Tortoise.close_connections()
            return
    except Exception as e:
        print(f"   ❌ 请求失败: {e}")
        await Tortoise.close_connections()
        return

    # 测试 2: 查询账号信息
    print("\n2. 查询账号信息...")
    try:
        resp = client.get(f'{base_url}/accounts')
        data = resp.json()
        if data.get('success'):
            accounts = data.get('result', [])
            print(f"   ✓ 找到 {len(accounts)} 个账号")
            for acc in accounts:
                print(f"      - {acc['name']} (ID: {acc['id']})")
                if acc['id'] == account_id:
                    print(f"        ✓ 与配置的 account_id 匹配")
            
            # 检查 account_id 是否在列表中
            account_ids = [a['id'] for a in accounts]
            if account_id not in account_ids:
                print(f"\n   ❌ 配置的 account_id 不在您的账号列表中")
                print(f"      当前配置: {account_id}")
                print(f"      可用账号: {', '.join(account_ids)}")
                print("\n   建议：请检查 account_id 是否正确")
        else:
            errors = data.get('errors', [])
            print(f"   ❌ 查询失败")
            for err in errors:
                print(f"      - {err.get('message', err)}")
    except Exception as e:
        print(f"   ❌ 请求失败: {e}")

    # 测试 3: 尝试创建 Zone（使用测试域名）
    print("\n3. 测试 Zone 创建权限（模拟请求）...")
    print(f"   Account ID: {account_id}")
    
    test_domain = "test-permission-check-12345.com"
    payload = {
        'account': {'id': account_id},
        'name': test_domain,
        'jump_start': False
    }
    
    try:
        resp = client.post(f'{base_url}/zones', json=payload)
        print(f"   HTTP 状态码: {resp.status_code}")
        data = resp.json()
        
        if resp.status_code == 403:
            print(f"   ❌ 403 Forbidden - Token 权限不足")
            errors = data.get('errors', [])
            for err in errors:
                print(f"      错误码: {err.get('code', 'N/A')}")
                print(f"      消息: {err.get('message', err)}")
            
            print("\n   ✅ 解决方案:")
            print("      1. 前往 Cloudflare Dashboard")
            print("      2. My Profile → API Tokens → 找到当前 Token")
            print("      3. 确保 Token 拥有以下权限:")
            print("         - Zone:Edit (必须)")
            print("         - DNS:Edit (可选，建议添加)")
            print("      4. 确保 Token 的 Account Resources 包含目标账号")
            
        elif resp.status_code == 400:
            # 预期行为：测试域名不存在，但说明有创建权限
            errors = data.get('errors', [])
            err_codes = [e.get('code') for e in errors]
            if 1061 in err_codes or 'already exists' in str(errors).lower():
                print(f"   ✓ Token 拥有 Zone 创建权限（测试域名已存在，这是预期的）")
            else:
                print(f"   ✓ Token 拥有 API 调用权限（返回 400 但非权限问题）")
                for err in errors:
                    print(f"      - {err.get('message', err)}")
        
        elif data.get('success'):
            # 意外创建成功，需要删除
            zone_id = data['result']['id']
            print(f"   ✓ Token 拥有 Zone 创建权限")
            print(f"   正在删除测试 Zone...")
            client.delete(f'{base_url}/zones/{zone_id}')
            print(f"   ✓ 测试 Zone 已删除")
        
        else:
            print(f"   ⚠️ 未预期的响应:")
            errors = data.get('errors', [])
            for err in errors:
                print(f"      - {err.get('message', err)}")
    
    except Exception as e:
        print(f"   ❌ 请求失败: {e}")

    print("\n" + "=" * 80)
    print("诊断完成")
    print("=" * 80)
    
    await Tortoise.close_connections()
    client.close()


if __name__ == '__main__':
    asyncio.run(diagnose())
