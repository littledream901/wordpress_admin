from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "role" ADD "data_scope" SMALLINT NOT NULL  DEFAULT 3 /* 数据权限范围 */;
        CREATE TABLE "role_dept" (
    "dept_id" BIGINT NOT NULL REFERENCES "dept" ("id") ON DELETE CASCADE,
    "role_id" BIGINT NOT NULL REFERENCES "role" ("id") ON DELETE CASCADE
);
        CREATE INDEX "idx_role_data_sc_94b654" ON "role" ("data_scope");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_role_data_sc_94b654";
        DROP TABLE IF EXISTS "role_dept";
        ALTER TABLE "role" DROP COLUMN "data_scope";"""
