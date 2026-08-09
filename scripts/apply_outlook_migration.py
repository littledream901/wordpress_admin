"""执行 7_20260810130000_add_outlook_to_gmail_registration 迁移"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tortoise import Tortoise, connections
from app.settings.config import settings

TABLE = 'site_pipeline_gmail_registration'

COLUMNS = [
    ("outlook_account_id", "INT NULL COMMENT '分配的 Outlook 账号 ID'", "sms_error"),
    ("outlook_account_username", "VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Outlook 账号用户名（冗余，便于展示）'", "outlook_account_id"),
    ("is_deleted", "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '软删除标记'", "outlook_account_username"),
    ("deleted_at", "DATETIME NULL COMMENT '删除时间'", "is_deleted"),
]

INDEXES = [
    ("idx_outlook_account_id", "outlook_account_id"),
    ("idx_is_deleted", "is_deleted"),
]


async def main():
    await Tortoise.init(config=settings.TORTOISE_ORM)
    conn = connections.get('default')

    existing = await conn.execute_query(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", [TABLE]
    )
    cols = {r['COLUMN_NAME'] for r in existing[1]}

    for name, definition, after in COLUMNS:
        if name in cols:
            print(f"跳过列 {name}（已存在）")
            continue
        sql = f"ALTER TABLE `{TABLE}` ADD COLUMN `{name}` {definition} AFTER `{after}`"
        await conn.execute_script(sql)
        print(f"已添加列 {name}")

    idx_rows = await conn.execute_query(
        "SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", [TABLE]
    )
    idxs = {r['INDEX_NAME'] for r in idx_rows[1]}

    for idx_name, col in INDEXES:
        if idx_name in idxs:
            print(f"跳过索引 {idx_name}（已存在）")
            continue
        await conn.execute_script(f"ALTER TABLE `{TABLE}` ADD KEY `{idx_name}` (`{col}`)")
        print(f"已添加索引 {idx_name}")

    final = await conn.execute_query(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s "
        "AND COLUMN_NAME IN ('outlook_account_id','outlook_account_username','is_deleted','deleted_at')",
        [TABLE]
    )
    print("验证新增列:", sorted(r['COLUMN_NAME'] for r in final[1]))

    await Tortoise.close_connections()


if __name__ == '__main__':
    asyncio.run(main())
