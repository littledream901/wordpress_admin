from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "api" ADD "is_button" INT NOT NULL  DEFAULT 0 /* 是否为按钮权限 */;
        CREATE TABLE IF NOT EXISTS "role_data_scope" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "resource" VARCHAR(64) NOT NULL  /* 业务模块标识（如 site\/account\/gmail） */,
    "data_scope" SMALLINT NOT NULL  DEFAULT 3 /* 数据权限范围 */,
    "role_id" BIGINT NOT NULL REFERENCES "role" ("id") ON DELETE CASCADE /* 角色 */,
    CONSTRAINT "uid_role_data_s_role_id_3092d4" UNIQUE ("role_id", "resource")
) /* 角色按业务模块的数据权限配置 */;
CREATE INDEX IF NOT EXISTS "idx_role_data_s_resourc_611237" ON "role_data_scope" ("resource");
CREATE INDEX IF NOT EXISTS "idx_role_data_s_data_sc_16f0f1" ON "role_data_scope" ("data_scope");
        ALTER TABLE "site_pipeline_site" ADD "dept_id" INT   /* 创建者部门ID */;
        ALTER TABLE "site_pipeline_site" ADD "create_by" INT   /* 创建者用户ID */;
        CREATE INDEX "idx_api_is_butt_8d8d88" ON "api" ("is_button");
        CREATE TABLE "role_data_scope_dept" (
    "dept_id" BIGINT NOT NULL REFERENCES "dept" ("id") ON DELETE CASCADE,
    "role_data_scope_id" BIGINT NOT NULL REFERENCES "role_data_scope" ("id") ON DELETE CASCADE
);
        CREATE INDEX "idx_site_pipeli_dept_id_5a2ce0" ON "site_pipeline_site" ("dept_id");
        CREATE INDEX "idx_site_pipeli_create__cec76b" ON "site_pipeline_site" ("create_by");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_site_pipeli_create__cec76b";
        DROP INDEX IF EXISTS "idx_site_pipeli_dept_id_5a2ce0";
        DROP TABLE IF EXISTS "role_data_scope_dept";
        DROP INDEX IF EXISTS "idx_api_is_butt_8d8d88";
        ALTER TABLE "api" DROP COLUMN "is_button";
        ALTER TABLE "site_pipeline_site" DROP COLUMN "dept_id";
        ALTER TABLE "site_pipeline_site" DROP COLUMN "create_by";
        DROP TABLE IF EXISTS "role_data_scope";"""
