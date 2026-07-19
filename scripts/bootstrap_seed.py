"""
种子数据初始化入口

统一调用所有幂等 seed 函数，可作为独立脚本或 entrypoint 调用。

用法:
    python scripts/bootstrap_seed.py          # 完整种子初始化
    python scripts/bootstrap_seed.py --check  # 仅检查（dry-run）
    python scripts/bootstrap_seed.py --skip-menus  # 跳过菜单
"""

import asyncio
import argparse
from tortoise import Tortoise
from app.settings import TORTOISE_ORM
from app.core.init_app import (
    init_superuser,
    init_menus,
    init_roles,
    init_providers,
    init_configs,
    init_apis,
)
from app.utils.provider_resolver import _load_configs_to_cache


async def main():
    parser = argparse.ArgumentParser(description="种子数据初始化")
    parser.add_argument("--check", action="store_true", help="仅检查，不写入")
    parser.add_argument("--skip-menus", action="store_true", help="跳过菜单初始化")
    parser.add_argument("--skip-roles", action="store_true", help="跳过角色初始化")
    parser.add_argument("--skip-providers", action="store_true", help="跳过 Provider 初始化")
    args = parser.parse_args()

    await Tortoise.init(config=TORTOISE_ORM)

    if args.check:
        print("[CHECK] 种子数据检查模式 — 不执行写入")
        return

    print("[SEED] 开始种子数据初始化...")

    await init_superuser()
    print("  [OK] 超级用户")

    if not args.skip_menus:
        await init_menus()
        print("  [OK] 菜单")

    if not args.skip_roles:
        await init_roles()
        print("  [OK] 角色")

    if not args.skip_providers:
        await init_providers()
        await _load_configs_to_cache()
        print("  [OK] Provider + 缓存")

    await init_configs()
    print("  [OK] 全局配置")

    await init_apis()
    print("  [OK] API 同步")

    print("[SEED] 种子数据初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
