"""
用户数据修复脚本

检查并修复用户名/邮箱重复、is_superuser 缺失等问题。

用法:
    python scripts/repair_users.py          # 检测模式（dry-run）
    python scripts/repair_users.py --fix    # 修复模式
"""

import asyncio
import argparse
from collections import defaultdict
from tortoise import Tortoise
from app.settings import TORTOISE_ORM
from app.models.admin import User


async def check_issues():
    """检测用户数据问题"""
    issues = {}

    # 检查重复用户名
    all_users = await User.all().order_by("id")
    username_groups = defaultdict(list)
    for u in all_users:
        username_groups[u.username].append(u)
    dup_usernames = {k: v for k, v in username_groups.items() if len(v) > 1}
    if dup_usernames:
        issues["dup_username"] = dup_usernames

    # 检查缺少 is_superuser 的 admin
    admin = await User.filter(username="admin").first()
    if admin and not admin.is_superuser:
        issues["admin_not_superuser"] = admin

    return issues


async def repair_issues(issues: dict, dry_run: bool = True):
    """修复用户数据问题"""
    if "dup_username" in issues:
        for username, users in issues["dup_username"].items():
            print(f"\n  重复用户名: {username} ({len(users)} 条)")
            keeper = users[0]
            print(f"    保留: id={keeper.id}")
            print(f"    待处理: {[u.id for u in users[1:]]}")
            if not dry_run:
                # 保守策略：仅标记，不自动删除
                print(f"    [SKIP] 自动删除用户风险过高，请手动处理")

    if "admin_not_superuser" in issues:
        admin = issues["admin_not_superuser"]
        print(f"\n  admin 用户缺少 is_superuser 权限: id={admin.id}")
        if not dry_run:
            admin.is_superuser = True
            await admin.save(update_fields=["is_superuser"])
            print(f"    [FIXED] admin is_superuser=True")


async def main():
    parser = argparse.ArgumentParser(description="用户数据修复工具")
    parser.add_argument("--fix", action="store_true", help="执行修复（默认仅检测）")
    args = parser.parse_args()

    await Tortoise.init(config=TORTOISE_ORM)

    issues = await check_issues()
    if not issues:
        print("用户数据正常，无需修复")
        return

    print(f"发现 {len(issues)} 类用户数据问题")
    await repair_issues(issues, dry_run=not args.fix)

    if not args.fix:
        print("\n使用 --fix 参数执行修复: python scripts/repair_users.py --fix")


if __name__ == "__main__":
    asyncio.run(main())
