"""为 hubstudio_proxy_config 表添加软删除字段

新增字段：is_deleted（软删除标记）/ deleted_at（删除时间）
执行方式：python test/add_proxy_soft_delete.py
"""
import asyncio
import os
from pathlib import Path
from tortoise import Tortoise
from dotenv import load_dotenv

TABLE = "hubstudio_proxy_config"

ADD_COLUMNS = {
    "is_deleted": "BOOL NOT NULL DEFAULT 0 COMMENT '软删除标记'",
    "deleted_at": "DATETIME(6) NULL COMMENT '删除时间'",
}

ADD_INDEXES = {
    "idx_hubstudio_p_is_deleted": "(`is_deleted`)",
}


async def main():
    load_dotenv(Path(__file__).parent.parent / ".env")
    db_name = os.getenv("DB_NAME")
    db_url = (
        f"mysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{db_name}"
    )

    await Tortoise.init(
        config={
            "connections": {"default": db_url},
            "apps": {"models": {"models": [], "default_connection": "default"}},
        }
    )
    conn = Tortoise.get_connection("default")

    # 现有列
    _, col_rows = await conn.execute_query(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
        [db_name, TABLE],
    )
    existing_columns = {r["COLUMN_NAME"] for r in col_rows}

    for col, ddl in ADD_COLUMNS.items():
        if col in existing_columns:
            print(f"column {col} already exists, skip")
            continue
        await conn.execute_query(f"ALTER TABLE `{TABLE}` ADD COLUMN `{col}` {ddl}")
        print(f"added column {col}")

    # 现有索引
    _, idx_rows = await conn.execute_query(
        "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
        [db_name, TABLE],
    )
    existing_indexes = {r["INDEX_NAME"] for r in idx_rows}

    for idx, cols in ADD_INDEXES.items():
        if idx in existing_indexes:
            print(f"index {idx} already exists, skip")
            continue
        await conn.execute_query(f"ALTER TABLE `{TABLE}` ADD INDEX `{idx}` {cols}")
        print(f"added index {idx}")

    await Tortoise.close_connections()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
