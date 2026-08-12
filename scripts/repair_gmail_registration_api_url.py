"""
修复脚本：同步 GmailRegistration 缺失的 api_url 字段

背景：
- _OUTLOOK_IDENTITY_FIELDS 之前未包含 api_url，导致分配 Outlook 账号时
  接码地址未同步到 GmailRegistration.api_url
- 本脚本将已分配 Outlook 的注册记录，同步 api_url 字段

使用方式: python scripts/repair_gmail_registration_api_url.py
"""
import asyncio
import os
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tortoise import Tortoise
from app.settings.config import settings
from app.log import logger


async def repair():
    """同步缺失的 api_url 字段"""
    await Tortoise.init(config=settings.TORTOISE_ORM)

    from app.models.gmail_registration import GmailRegistration
    from app.models.outlook_account import OutlookAccount

    # 查询所有已分配 Outlook 且 api_url 为空的注册记录
    registrations = await GmailRegistration.filter(
        is_deleted=False,
        outlook_account_id__isnull=False,
        api_url='',
    ).all()

    print(f"找到 {len(registrations)} 条已分配 Outlook 但 api_url 为空的注册记录")

    updated = 0
    skipped = 0
    for reg in registrations:
        outlook = await OutlookAccount.filter(
            id=reg.outlook_account_id,
            is_deleted=False,
        ).first()
        if not outlook:
            print(f"  [跳过] reg#{reg.id}: Outlook 账号 #{reg.outlook_account_id} 不存在")
            skipped += 1
            continue

        if not outlook.api_url:
            print(f"  [跳过] reg#{reg.id}: Outlook 账号 #{reg.outlook_account_id} 的 api_url 为空")
            skipped += 1
            continue

        reg.api_url = outlook.api_url
        await reg.save(update_fields=['api_url'])
        updated += 1
        print(f"  [同步] reg#{reg.id}: api_url = {outlook.api_url}")

    print(f"\n完成：更新 {updated} 条，跳过 {skipped} 条")

    await Tortoise.close_connections()


if __name__ == "__main__":
    print("=" * 60)
    print("GmailRegistration api_url 字段修复脚本")
    print("=" * 60)
    asyncio.run(repair())
    print("\n修复完成！")
