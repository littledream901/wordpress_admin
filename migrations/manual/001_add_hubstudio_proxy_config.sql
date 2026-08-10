-- 手动迁移脚本：添加 HubStudio 代理配置表
-- 执行方式：在 MySQL 客户端中运行此脚本
-- 或使用：mysql -u用户名 -p数据库名 < 001_add_hubstudio_proxy_config.sql

-- 1. 创建代理配置表
CREATE TABLE IF NOT EXISTS `hubstudio_proxy_config` (
  `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
  `name` VARCHAR(128) NOT NULL UNIQUE COMMENT '代理配置名称',
  `code` VARCHAR(64) NOT NULL UNIQUE COMMENT '代理配置编码',
  `description` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '描述',
  
  -- HubStudio API 核心字段（13个）
  `proxy_type_name` VARCHAR(32) NOT NULL DEFAULT 'HTTP' COMMENT '代理类型: HTTP/HTTPS/SOCKS5',
  `proxy_host` VARCHAR(255) NOT NULL COMMENT '代理服务器地址',
  `proxy_port` INT NOT NULL COMMENT '代理端口',
  `proxy_account` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '代理账号',
  `proxy_password` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '代理密码',
  `reference_country_code` VARCHAR(8) NOT NULL DEFAULT 'US' COMMENT '国家代码',
  `reference_city` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '城市',
  `reference_region_code` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '省份/州代码',
  `as_dynamic_type` INT NOT NULL DEFAULT 0 COMMENT '动态代理类型: 0=固定 1=动态',
  `ip_get_rule_type` INT NOT NULL DEFAULT 1 COMMENT 'IP获取规则类型',
  `link_code` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '链接代码',
  `ip_database_channel` INT NOT NULL DEFAULT 0 COMMENT 'IP数据库渠道',
  `ip_protocol_type` INT NOT NULL DEFAULT 0 COMMENT 'IP协议类型',
  `use_fixed_proxy` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否使用固定代理',
  
  -- 管理字段
  `status` VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT '状态: active/disabled/testing',
  `priority` INT NOT NULL DEFAULT 0 COMMENT '优先级，数字越大优先级越高',
  `is_default` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否默认代理',
  
  -- 统计字段
  `usage_count` INT NOT NULL DEFAULT 0 COMMENT '使用次数',
  `success_count` INT NOT NULL DEFAULT 0 COMMENT '成功次数',
  `last_used_at` DATETIME NULL COMMENT '最后使用时间',
  `last_check_at` DATETIME NULL COMMENT '最后检测时间',
  
  -- 关联字段
  `provider_id` INT NOT NULL DEFAULT 0 COMMENT '绑定的 Provider ID（0表示全局可用）',
  
  -- 时间戳
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  
  -- 索引
  KEY `idx_status_is_default` (`status`, `is_default`),
  KEY `idx_provider_status` (`provider_id`, `status`),
  KEY `idx_code` (`code`),
  KEY `idx_provider_id` (`provider_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='HubStudio 代理配置表';

-- 2. 为 Site 表新增字段
ALTER TABLE `site_pipeline_site` 
  ADD COLUMN IF NOT EXISTS `proxy_config_id` INT NOT NULL DEFAULT 0 COMMENT '绑定的代理配置ID（0表示使用Provider默认）',
  ADD INDEX IF NOT EXISTS `idx_proxy_config_id` (`proxy_config_id`);

-- 3. 插入默认全局代理配置
INSERT INTO `hubstudio_proxy_config` (
  `name`, `code`, `description`,
  `proxy_type_name`, `proxy_host`, `proxy_port`,
  `proxy_account`, `proxy_password`,
  `reference_country_code`, `reference_city`, `reference_region_code`,
  `as_dynamic_type`, `ip_get_rule_type`,
  `status`, `is_default`, `provider_id`
) VALUES (
  '全局默认代理', 
  'global_default', 
  '全局默认 HubStudio 代理配置（从环境变量迁移）',
  'HTTP', 
  'server.iphtml.biz', 
  15000,
  'uid-27498-zone-hubstudio', 
  'h4z3tsqc',
  'US', 
  'New York', 
  'CA',
  0, 
  1,
  'active', 
  1, 
  0
) ON DUPLICATE KEY UPDATE 
  `proxy_host` = VALUES(`proxy_host`),
  `proxy_port` = VALUES(`proxy_port`),
  `proxy_account` = VALUES(`proxy_account`);

-- 执行完成后验证
SELECT '✓ 迁移完成，当前代理配置：' AS status;
SELECT * FROM `hubstudio_proxy_config`;
