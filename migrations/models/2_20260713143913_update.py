from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- 为 role 表添加 data_scope 字段
        SET @exist := (
            SELECT COUNT(*) FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE() 
            AND TABLE_NAME = 'role' 
            AND COLUMN_NAME = 'data_scope'
        );
        
        SET @sql = IF(@exist = 0, 
            'ALTER TABLE `role` ADD COLUMN `data_scope` SMALLINT NOT NULL DEFAULT 3 COMMENT \"数据权限范围\"',
            'SELECT \"data_scope already exists\" AS message'
        );
        
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        
        -- 创建 role_dept 关联表
        CREATE TABLE IF NOT EXISTS `role_dept` (
            `dept_id` BIGINT NOT NULL,
            `role_id` BIGINT NOT NULL,
            FOREIGN KEY (`dept_id`) REFERENCES `dept` (`id`) ON DELETE CASCADE,
            FOREIGN KEY (`role_id`) REFERENCES `role` (`id`) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        
        CREATE INDEX IF NOT EXISTS `idx_role_data_scope` ON `role` (`data_scope`);
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS `idx_role_data_scope` ON `role`;
        DROP TABLE IF EXISTS `role_dept`;
        ALTER TABLE `role` DROP COLUMN IF EXISTS `data_scope`;
    """
