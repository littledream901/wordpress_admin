-- 添加 site_id 列（如果不存在）
ALTER TABLE `site_pipeline_gmail_registration` ADD COLUMN IF NOT EXISTS `site_id` INT NULL COMMENT '关联站点ID' AFTER `domain`;

-- 添加索引（如果不存在）
ALTER TABLE `site_pipeline_gmail_registration` ADD INDEX IF NOT EXISTS `idx_site_id` (`site_id`);
