from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- 为 site_pipeline_site 表添加 dept_id 和 create_by 字段
        SET @exist_dept_id := (
            SELECT COUNT(*) FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE() 
            AND TABLE_NAME = 'site_pipeline_site' 
            AND COLUMN_NAME = 'dept_id'
        );
        
        SET @exist_create_by := (
            SELECT COUNT(*) FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE() 
            AND TABLE_NAME = 'site_pipeline_site' 
            AND COLUMN_NAME = 'create_by'
        );
        
        SET @sql_dept_id = IF(@exist_dept_id = 0, 
            'ALTER TABLE `site_pipeline_site` ADD COLUMN `dept_id` INT NULL COMMENT \"创建者部门ID\"',
            'SELECT \"dept_id already exists\" AS message'
        );
        
        SET @sql_create_by = IF(@exist_create_by = 0,
            'ALTER TABLE `site_pipeline_site` ADD COLUMN `create_by` INT NULL COMMENT \"创建者用户ID\"',
            'SELECT \"create_by already exists\" AS message'
        );
        
        PREPARE stmt_dept FROM @sql_dept_id;
        EXECUTE stmt_dept;
        DEALLOCATE PREPARE stmt_dept;
        
        PREPARE stmt_create FROM @sql_create_by;
        EXECUTE stmt_create;
        DEALLOCATE PREPARE stmt_create;
        
        -- 添加索引
        CREATE INDEX IF NOT EXISTS `idx_site_pipeli_dept_id` ON `site_pipeline_site` (`dept_id`);
        CREATE INDEX IF NOT EXISTS `idx_site_pipeli_create_by` ON `site_pipeline_site` (`create_by`);
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS `idx_site_pipeli_create_by` ON `site_pipeline_site`;
        DROP INDEX IF EXISTS `idx_site_pipeli_dept_id` ON `site_pipeline_site`;
        ALTER TABLE `site_pipeline_site` DROP COLUMN IF EXISTS `create_by`;
        ALTER TABLE `site_pipeline_site` DROP COLUMN IF EXISTS `dept_id`;
    """
