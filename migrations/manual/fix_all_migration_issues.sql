-- ============================================================
-- 数据库迁移修复脚本
-- 用途: 创建 aerich 表 + hubstudio_proxy_config 表
-- ============================================================

-- 1. 创建 aerich 迁移追踪表
CREATE TABLE IF NOT EXISTS `aerich` (
  `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
  `version` VARCHAR(255) NOT NULL,
  `app` VARCHAR(100) NOT NULL,
  `content` JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Aerich 迁移历史表';

-- 2. 插入已应用的迁移记录（根据 migrations/models 目录中的文件）
INSERT INTO `aerich` (`version`, `app`, `content`) VALUES
  ('1_20260713043940_None.py', 'models', '{}'),
  ('2_20260713143913_update.py', 'models', '{}'),
  ('3_20260713162304_update.py', 'models', '{}'),
  ('4_20260809000000_gateway_defense.py', 'models', '{}'),
  ('5_20260810000000_add_gateway_site_id.py', 'models', '{}'),
  ('6_20260810120000_add_gmail_registration.py', 'models', '{}'),
  ('7_20260810130000_add_outlook_to_gmail_registration.py', 'models', '{}'),
  ('8_20260810150000_add_outlook_account.py', 'models', '{}'),
  ('9_20260810160000_add_gmail_registration_two_fa_key.py', 'models', '{}')
ON DUPLICATE KEY UPDATE version=version;

-- 3. 创建 HubStudio 代理配置表
CREATE TABLE IF NOT EXISTS `hubstudio_proxy_config` (
  `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
  `name` VARCHAR(128) NOT NULL UNIQUE COMMENT '代理配置名称',
  `code` VARCHAR(64) NOT NULL UNIQUE COMMENT '代理配置编码',
  `description` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '描述',
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
  `status` VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT '状态: active/disabled/testing',
  `priority` INT NOT NULL DEFAULT 0 COMMENT '优先级，数字越大优先级越高',
  `is_default` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否默认代理',
  `usage_count` INT NOT NULL DEFAULT 0 COMMENT '使用次数',
  `success_count` INT NOT NULL DEFAULT 0 COMMENT '成功次数',
  `last_used_at` DATETIME NULL COMMENT '最后使用时间',
  `last_check_at` DATETIME NULL COMMENT '最后检测时间',
  `provider_id` INT NOT NULL DEFAULT 0 COMMENT '绑定的 Provider ID（0表示全局可用）',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  KEY `idx_status_is_default` (`status`, `is_default`),
  KEY `idx_provider_status` (`provider_id`, `status`),
  KEY `idx_code` (`code`),
  KEY `idx_provider_id` (`provider_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='HubStudio 代理配置表';

-- 4. 为 Site 表新增代理配置字段
ALTER TABLE `site_pipeline_site` 
  ADD COLUMN IF NOT EXISTS `proxy_config_id` INT NOT NULL DEFAULT 0 COMMENT '绑定的代理配置ID',
  ADD INDEX IF NOT EXISTS `idx_proxy_config_id` (`proxy_config_id`);

-- 5. 插入全局默认代理配置
INSERT INTO `hubstudio_proxy_config` (
  `name`, `code`, `description`,
  `proxy_type_name`, `proxy_host`, `proxy_port`,
  `proxy_account`, `proxy_password`,
  `reference_country_code`, `reference_city`, `reference_region_code`,
  `as_dynamic_type`, `ip_get_rule_type`,
  `link_code`, `ip_database_channel`, `ip_protocol_type`,
  `use_fixed_proxy`, `status`, `is_default`, `provider_id`
) VALUES (
  '全局默认代理', 'global_default', '全局默认 HubStudio 代理配置',
  'HTTP', 'server.iphtml.biz', 15000,
  'uid-27498-zone-hubstudio', 'h4z3tsqc',
  'US', 'New York', 'CA',
  0, 1,
  '', 0, 0,
  1, 'active', 1, 0
) ON DUPLICATE KEY UPDATE code=code;

-- 6. 记录此次迁移到 aerich
INSERT INTO `aerich` (`version`, `app`, `content`) VALUES
  ('10_20260810170000_add_hubstudio_proxy_config_table.py', 'models', '{}')
ON DUPLICATE KEY UPDATE version=version;

-- ============================================================
-- 修复完成提示
-- ============================================================
SELECT 
  '修复完成！' as status,
  (SELECT COUNT(*) FROM aerich) as aerich_records,
  (SELECT COUNT(*) FROM hubstudio_proxy_config) as proxy_configs,
  (SELECT COUNT(*) FROM information_schema.columns WHERE table_name='site_pipeline_site' AND column_name='proxy_config_id') as site_field_exists;
