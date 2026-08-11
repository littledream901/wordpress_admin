# -*- coding: utf-8 -*-
"""
菜单同步修复脚本
强制将后端菜单定义同步到数据库，解决标签页404问题
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from tortoise import Tortoise
from app.settings import TORTOISE_ORM


async def fix_menu_sync():
    """强制同步菜单"""
    await Tortoise.init(config=TORTOISE_ORM)
    
    print("=" * 80)
    print("Menu Sync - Start")
    print("=" * 80)
    
    # 导入菜单初始化函数
    from app.core.init_app import init_menus, init_roles, init_apis
    
    try:
        # 执行菜单同步
        print("\n[1/3] Syncing menus...")
        await init_menus()
        print("[OK] Menus synced")
        
        # 同步 API
        print("\n[2/3] Syncing APIs...")
        await init_apis()
        print("[OK] APIs synced")
        
        # 同步角色权限
        print("\n[3/3] Syncing roles and permissions...")
        await init_roles()
        print("[OK] Roles synced")
        
        print("\n" + "=" * 80)
        print("Menu sync completed successfully!")
        print("Please restart backend service and refresh frontend page")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n[ERROR] Sync failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        await Tortoise.close_connections()
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(fix_menu_sync())
    sys.exit(exit_code)
