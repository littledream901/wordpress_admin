"""简化 hubstudio_proxy_config 表结构

删除与代理管理页面无关的字段：name / code / priority / is_default / provider_id / last_check_at
"""
import asyncio
import os
from pathlib import Path
from tortoise import Tortoise
from dotenv import load_dotenv

DROP_COLUMNS = [
    "name",
    "code",
    "priority",
    "is_default",
    "provider_id",
    "last_check_at",
]

DROP_INDEXES = [
    "uid_hubstudio_p_name",
    "uid_hubstudio_p_code",
    "idx_hubstudio_p_code",
    "idx_hubstudio_p_provider",
    "idx_hubstudio_p_status_default",
    "idx_hubstudio_p_provider_status",
]


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

    # 当前索引
    _, idx_rows = await conn.execute_query(
        "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME='hubstudio_proxy_config'",
        [db_name],
    )
    existing_indexes = {r["INDEX_NAME"] for r in idx_rows}

    for idx in DROP_INDEXES:
        if idx in existing_indexes:
            await conn.execute_query(f"ALTER TABLE `hubstudio_proxy_config` DROP INDEX `{idx}`")
            print(f"dropped index {idx}")

    # 当前列
    _, col_rows = await conn.execute_query(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME='hubstudio_proxy_config'",
        [db_name],
    )
    existing_columns = {r["COLUMN_NAME"] for r in col_rows}

    for col in DROP_COLUMNS:
        if col in existing_columns:
            await conn.execute_query(f"ALTER TABLE `hubstudio_proxy_config` DROP COLUMN `{col}`")
            print(f"dropped column {col}")

    # 补 host+port 复合索引
    if "idx_hubstudio_p_host_port" not in existing_indexes:
        await conn.execute_query(
            "ALTER TABLE `hubstudio_proxy_config` "
            "ADD INDEX `idx_hubstudio_p_host_port` (`proxy_host`, `proxy_port`)"
        )
        print("added index idx_hubstudio_p_host_port")

    _, final_cols = await conn.execute_query(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME='hubstudio_proxy_config' ORDER BY ORDINAL_POSITION",
        [db_name],
    )
    print("\ncurrent columns:")
    print(", ".join(r["COLUMN_NAME"] for r in final_cols))

    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
