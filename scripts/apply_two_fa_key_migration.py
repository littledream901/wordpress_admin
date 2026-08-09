"""执行 8_20260810160000_add_gmail_registration_two_fa_key 迁移"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tortoise import Tortoise, connections
from app.settings.config import settings

TABLE = 'site_pipeline_gmail_registration'


async def main():
    await Tortoise.init(config=settings.TORTOISE_ORM)
    conn = connections.get('default')

    existing = await conn.execute_query(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", [TABLE]
    )
    cols = {r['COLUMN_NAME'] for r in existing[1]}

    if 'two_fa_key' in cols:
        print("跳过列 two_fa_key（已存在）")
    else:
        sql = f"ALTER TABLE `{TABLE}` ADD COLUMN `two_fa_key` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '2FA Key' AFTER `recovery_email`"
        await conn.execute_script(sql)
        print("已添加列 two_fa_key")

    final = await conn.execute_query(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s "
        "AND COLUMN_NAME='two_fa_key'",
        [TABLE]
    )
    print("验证新增列:", sorted(r['COLUMN_NAME'] for r in final[1]))

    await Tortoise.close_connections()


if __name__ == '__main__':
    asyncio.run(main())
