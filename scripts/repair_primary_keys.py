"""
主键修复脚本

检查并修复缺失 PRIMARY KEY 的业务表 id 列。
由人工确认后执行，不在应用启动时自动运行。

用法:
    python scripts/repair_primary_keys.py          # 检测模式（dry-run）
    python scripts/repair_primary_keys.py --fix    # 修复模式
"""

import asyncio
import argparse
from tortoise import Tortoise, connections
from app.settings import TORTOISE_ORM


async def check_pk(conn) -> list[str]:
    """返回当前库中所有无主键的表名"""
    result = await conn.execute_query(
        """SELECT t.TABLE_NAME FROM information_schema.TABLES t
           WHERE t.TABLE_SCHEMA = DATABASE()
             AND NOT EXISTS (
               SELECT 1 FROM information_schema.TABLE_CONSTRAINTS c
               WHERE c.TABLE_SCHEMA = t.TABLE_SCHEMA
                 AND c.TABLE_NAME = t.TABLE_NAME
                 AND c.CONSTRAINT_TYPE = 'PRIMARY KEY'
             )"""
    )
    return [row[0] for row in result[1]] if result[1] else []


async def repair_pk(conn, tables: list[str], dry_run: bool = True):
    for table in tables:
        sql = f"ALTER TABLE `{table}` MODIFY COLUMN `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY"
        if dry_run:
            print(f"  [DRY-RUN] {sql}")
        else:
            try:
                await conn.execute_query(sql)
                print(f"  [FIXED] {table}")
            except Exception as e:
                print(f"  [ERROR] {table}: {e}")


async def main():
    parser = argparse.ArgumentParser(description="主键修复工具")
    parser.add_argument("--fix", action="store_true", help="执行修复（默认仅检测）")
    args = parser.parse_args()

    await Tortoise.init(config=TORTOISE_ORM)
    conn = connections.get("default")

    tables = await check_pk(conn)
    if not tables:
        print("所有业务表主键正常，无需修复")
        return

    print(f"发现 {len(tables)} 个表缺少主键: {tables}")
    await repair_pk(conn, tables, dry_run=not args.fix)

    if not args.fix:
        print("\n使用 --fix 参数执行修复: python scripts/repair_primary_keys.py --fix")


if __name__ == "__main__":
    asyncio.run(main())
