"""1Panel API 认证诊断测试

用于排查 401 API 接口密钥错误
"""

import hashlib
import time
import sys
import io
from pathlib import Path

# 修复 Windows 控制台编码问题
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_api_key_format():
    """测试 API Key 格式和签名生成"""
    from app.services.onepanel.client import OnePanelAPI

    api = OnePanelAPI()

    print("=" * 60)
    print("[1] 1Panel API 配置诊断")
    print("=" * 60)

    # 检查基础配置
    print(f"\n[OK] 配置状态: {'已配置' if api._configured else '未配置'}")
    print(f"[OK] 基础 URL: {api.base}")
    print(f"[OK] API Key 长度: {len(api.api_key)} 字符")
    if api.api_key:
        print(f"[OK] API Key 前缀: {api.api_key[:8]}...")
    else:
        print(f"[FAIL] API Key 为空")
    print(f"[OK] 最大重试: {api.max_retries}")
    print(f"[OK] 重试间隔: {api.retry_interval}s")
    print(f"[OK] 超时设置: {api.timeout}s")
    print(f"[OK] SSL 验证: {api.verify_ssl}")

    # 检查签名生成
    if api.api_key:
        ts = str(int(time.time()))
        expected_token = hashlib.md5(f'1panel{api.api_key}{ts}'.encode('utf-8')).hexdigest()
        headers = api.headers()

        print(f"\n签名测试:")
        print(f"  时间戳: {ts}")
        print(f"  签名原文: 1panel{api.api_key[:4]}...{api.api_key[-4:]}{ts}")
        print(f"  生成 Token: {expected_token}")
        print(f"  Headers Token: {headers.get('1Panel-Token')}")
        match = '[OK]' if headers.get('1Panel-Token') == expected_token else '[FAIL]'
        print(f"  Token 匹配: {match}")

        # 检查 API Key 是否包含空白字符
        if api.api_key != api.api_key.strip():
            print(f"\n[WARN] API Key 包含首尾空白字符，请清理！")
        if '\n' in api.api_key or '\r' in api.api_key:
            print(f"\n[WARN] API Key 包含换行符，请清理！")

    return api


def test_provider_config():
    """测试 Provider 配置加载"""
    from app.utils.provider_resolver import ProviderResolver

    print(f"\n{'=' * 60}")
    print("[2] Provider 配置检查")
    print("=" * 60)

    # 同步读取配置
    cfgs = ProviderResolver.sync_get_config_map('onepanel')

    print(f"\n配置项数量: {len(cfgs)}")

    # 检查关键配置项
    key_configs = ['url', 'api_key', 'OP_URL', 'OP_API_KEY']
    for key in key_configs:
        value = cfgs.get(key, '')
        if value:
            if 'key' in key.lower() or 'api' in key.lower():
                print(f"  {key}: {value[:8]}...{value[-4:]} (长度: {len(value)})")
            else:
                print(f"  {key}: {value}")
        else:
            print(f"  {key}: <未配置>")

    # 显示所有配置项键
    print(f"\n所有配置键: {list(cfgs.keys())}")

    return cfgs


def test_api_connection():
    """测试 API 连接"""
    from app.services.onepanel.client import OnePanelAPI

    print(f"\n{'=' * 60}")
    print("[3] API 连接测试")
    print("=" * 60)

    api = OnePanelAPI()

    if not api._configured:
        print("\n[FAIL] 1Panel 未配置，跳过连接测试")
        return

    # 测试简单的 GET 请求
    print(f"\n正在测试 GET /apps/wordpress...")
    ok, result = api.get('/apps/wordpress')

    if ok:
        print(f"[OK] 连接成功")
        if isinstance(result, dict):
            print(f"  App ID: {result.get('id')}")
            print(f"  App Key: {result.get('key')}")
            print(f"  App 名称: {result.get('name')}")
            print(f"  可用版本: {result.get('versions')}")
    else:
        print(f"[FAIL] 连接失败: {result}")

        # 401 错误特殊处理
        if '401' in str(result):
            print(f"\n>> 401 错误排查建议:")
            print(f"   1. 检查 API Key 是否正确（1Panel 面板 → 设置 → 安全 → API 接口）")
            print(f"   2. 确认 API Key 没有多余空格或换行符")
            print(f"   3. 检查 1Panel 版本（建议 v1.8.0+）")
            print(f"   4. 尝试重新生成 API Key")
            print(f"   5. 参考 docs/troubleshooting/onepanel_401_fix.md")


if __name__ == '__main__':
    print("\n开始 1Panel API 认证诊断...\n")

    try:
        # 需要初始化数据库连接才能读取 Provider 配置
        import asyncio
        from tortoise import Tortoise
        from app.settings.config import settings

        async def init_and_test():
            await Tortoise.init(config=settings.TORTOISE_ORM)

            # 预加载配置到缓存
            from app.utils.provider_resolver import _load_configs_to_cache
            await _load_configs_to_cache()

            # 执行诊断（同步方法）
            test_api_key_format()
            test_provider_config()
            test_api_connection()

            await Tortoise.close_connections()

        asyncio.run(init_and_test())

        print(f"\n{'=' * 60}")
        print("诊断完成")
        print("=" * 60)

    except Exception as e:
        print(f"\n[FAIL] 诊断过程出错: {e}")
        import traceback
        traceback.print_exc()
