from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- 本迁移文件用于替代已删除的 SQLite 迁移文件 1 和 3
        -- 如果表已存在则跳过，确保幂等性
        
        CREATE TABLE IF NOT EXISTS `api` (
            `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
            `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
            `path` VARCHAR(100) NOT NULL COMMENT 'API路径',
            `method` VARCHAR(6) NOT NULL COMMENT '请求方法',
            `summary` VARCHAR(500) NOT NULL COMMENT '请求简介',
            `tags` VARCHAR(100) NOT NULL COMMENT 'API标签',
            `is_button` INT NOT NULL DEFAULT 0 COMMENT '是否为按钮权限',
            KEY `idx_api_created` (`created_at`),
            KEY `idx_api_updated` (`updated_at`),
            KEY `idx_api_path` (`path`),
            KEY `idx_api_method` (`method`),
            KEY `idx_api_summary` (`summary`),
            KEY `idx_api_tags` (`tags`),
            KEY `idx_api_is_button` (`is_button`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS `role_data_scope` (
            `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
            `resource` VARCHAR(64) NOT NULL COMMENT '业务模块标识',
            `data_scope` SMALLINT NOT NULL DEFAULT 3 COMMENT '数据权限范围',
            `role_id` BIGINT NOT NULL COMMENT '角色',
            CONSTRAINT `uid_role_data_s_role_id_3092d4` UNIQUE (`role_id`, `resource`),
            KEY `idx_role_data_s_resource` (`resource`),
            KEY `idx_role_data_s_data_scope` (`data_scope`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='角色按业务模块的数据权限配置';

        CREATE TABLE IF NOT EXISTS `role_data_scope_dept` (
            `dept_id` BIGINT NOT NULL,
            `role_data_scope_id` BIGINT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS `role_data_scope_dept`;
        DROP TABLE IF EXISTS `role_data_scope`;
        DROP TABLE IF EXISTS `api`;
    """
