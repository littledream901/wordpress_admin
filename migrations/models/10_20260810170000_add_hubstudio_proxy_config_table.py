from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `hubstudio_proxy_config` (
            `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
            `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
            `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
            `description` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '代理配置描述',
            `proxy_type_name` VARCHAR(32) NOT NULL DEFAULT 'HTTP' COMMENT '代理类型',
            `proxy_host` VARCHAR(255) NOT NULL COMMENT '代理服务器地址',
            `proxy_port` INT NOT NULL COMMENT '代理端口',
            `proxy_account` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '代理账号',
            `proxy_password` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '代理密码',
            `reference_country_code` VARCHAR(8) NOT NULL DEFAULT 'US' COMMENT '参考国家代码',
            `reference_city` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '参考城市',
            `reference_region_code` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '参考区域/省份代码',
            `as_dynamic_type` INT NOT NULL DEFAULT 0 COMMENT 'IP变更提醒: 0=关闭 1=开启',
            `ip_get_rule_type` INT NOT NULL DEFAULT 1 COMMENT 'IP提取方式: 1=IP失效时提取 2=每次打开环境时提取',
            `link_code` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'API提取链接',
            `ip_database_channel` INT NOT NULL DEFAULT 1 COMMENT '代理查询渠道: 1=IP2Location 2=DB-IP 3=MaxMind',
            `ip_protocol_type` INT NOT NULL DEFAULT 1 COMMENT 'IP协议选项: 1=速度优先 2=IPv4 3=IPv6',
            `use_fixed_proxy` BOOL NOT NULL DEFAULT 1 COMMENT '是否使用固定代理配置',
            `status` VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT '状态: active/disabled/testing',
            `usage_count` INT NOT NULL DEFAULT 0 COMMENT '累计使用次数',
            `success_count` INT NOT NULL DEFAULT 0 COMMENT '成功次数',
            `last_used_at` DATETIME(6) NULL COMMENT '最后使用时间',
            KEY `idx_hubstudio_p_created` (`created_at`),
            KEY `idx_hubstudio_p_updated` (`updated_at`),
            KEY `idx_hubstudio_p_host` (`proxy_host`),
            KEY `idx_hubstudio_p_status` (`status`),
            KEY `idx_hubstudio_p_host_port` (`proxy_host`, `proxy_port`)
        ) CHARACTER SET utf8mb4 COMMENT='HubStudio 代理配置表';
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS `hubstudio_proxy_config`;
    """
