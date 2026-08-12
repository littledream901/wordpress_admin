-- 添加 site_id 字段到 Gmail 注册表
-- 使用方法: mysql -u用户名 -p数据库名 < 此文件路径

-- 检查并添加 site_id 列
SET @dbname = DATABASE();
SET @tablename = 'site_pipeline_gmail_registration';
SET @columnname = 'site_id';
SET @preparedStatement = (SELECT IF(
  (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE 
      TABLE_SCHEMA = @dbname
      AND TABLE_NAME = @tablename
      AND COLUMN_NAME = @columnname
  ) > 0,
  'SELECT ''Column site_id already exists'' AS message;',
  'ALTER TABLE `site_pipeline_gmail_registration` 
   ADD COLUMN `site_id` INT NULL COMMENT ''关联站点ID'' AFTER `domain`,
   ADD INDEX `idx_site_id` (`site_id`);'
));

PREPARE alterIfNotExists FROM @preparedStatement;
EXECUTE alterIfNotExists;
DEALLOCATE PREPARE alterIfNotExists;

-- 验证结果
SELECT 
    COLUMN_NAME, 
    DATA_TYPE, 
    IS_NULLABLE, 
    COLUMN_COMMENT 
FROM INFORMATION_SCHEMA.COLUMNS 
WHERE TABLE_SCHEMA = DATABASE() 
  AND TABLE_NAME = 'site_pipeline_gmail_registration' 
  AND COLUMN_NAME = 'site_id';
