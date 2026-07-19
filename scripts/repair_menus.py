"""
菜单去重修复脚本

清理 (path, parent_id) 重复的菜单记录，保留最早创建的。
处理子菜单重定向和角色关联。

用法:
    python scripts/repair_menus.py          # 检测模式（dry-run）
    python scripts/repair_menus.py --fix    # 修复模式
"""

import asyncio
import argparse
from collections import defaultdict
from tortoise import Tortoise
from app.settings import TORTOISE_ORM
from app.models.admin import Menu, Role


async def check_duplicates():
    """检测重复菜单"""
    all_menus = await Menu.all().order_by("id")
    groups = defaultdict(list)
    for m in all_menus:
        groups[(m.path, m.parent_id)].append(m)

    duplicates = {k: v for k, v in groups.items() if len(v) > 1}
    return duplicates


async def repair_duplicates(duplicates: dict, dry_run: bool = True):
    """修复重复菜单"""
    for (path, parent_id), dup_list in duplicates.items():
        keeper = dup_list[0]
        removed_ids = [m.id for m in dup_list[1:]]
        print(f"\n  重复菜单: path={path} parent_id={parent_id}")
        print(f"    保留: id={keeper.id} name={keeper.name}")
        print(f"    删除: {[(m.id, m.name) for m in dup_list[1:]]}")

        if dry_run:
            continue

        # 子菜单重定向
        await Menu.filter(parent_id__in=removed_ids).update(parent_id=keeper.id)
        # 清理角色关联
        roles = await Role.filter(menus__id__in=removed_ids).all()
        for role in roles:
            await role.menus.remove(*removed_ids)
        # 删除重复
        await Menu.filter(id__in=removed_ids).delete()
        print(f"    [FIXED] 已删除 {len(removed_ids)} 条重复菜单")


async def main():
    parser = argparse.ArgumentParser(description="菜单去重修复工具")
    parser.add_argument("--fix", action="store_true", help="执行修复（默认仅检测）")
    args = parser.parse_args()

    await Tortoise.init(config=TORTOISE_ORM)

    duplicates = await check_duplicates()
    if not duplicates:
        print("菜单无重复，无需修复")
        return

    print(f"发现 {len(duplicates)} 组重复菜单")
    await repair_duplicates(duplicates, dry_run=not args.fix)

    if not args.fix:
        print("\n使用 --fix 参数执行修复: python scripts/repair_menus.py --fix")


if __name__ == "__main__":
    asyncio.run(main())
