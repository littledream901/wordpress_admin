from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `site_pipeline_gmail_registration` (
            `id`                    INT NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
            `alias`                 VARCHAR(100) NOT NULL COMMENT '邮箱别名（Gmail 前缀）',
            `domain`                VARCHAR(255) NOT NULL COMMENT '站点域名',
            `site_id`               INT          NULL COMMENT '关联站点ID',
            `full_name`             VARCHAR(200) NOT NULL DEFAULT '' COMMENT '完整姓名',
            `first_name`            VARCHAR(100) NOT NULL DEFAULT '' COMMENT '名',
            `last_name`             VARCHAR(100) NOT NULL DEFAULT '' COMMENT '姓',
            `password`              VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Gmail 密码',
            `country`               VARCHAR(100) NOT NULL DEFAULT '' COMMENT '国家',
            `province_state`        VARCHAR(100) NOT NULL DEFAULT '' COMMENT '省/州',
            `city`                  VARCHAR(100) NOT NULL DEFAULT '' COMMENT '城市',
            `zip_code`              VARCHAR(32)  NOT NULL DEFAULT '' COMMENT '邮编',
            `shipping_address_1`    VARCHAR(255) NOT NULL DEFAULT '' COMMENT '地址1',
            `shipping_address_2`    VARCHAR(255) NOT NULL DEFAULT '' COMMENT '地址2（可选）',
            `phone`                 VARCHAR(64)  NOT NULL DEFAULT '' COMMENT '电话',
            `forward_to`            VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'ImprovMX 转发目标邮箱',
            `recovery_email`        VARCHAR(255) NOT NULL DEFAULT '' COMMENT '恢复邮箱',
            `improvmx_alias_id`     VARCHAR(64)  NOT NULL DEFAULT '' COMMENT 'ImprovMX 别名 ID',
            `improvmx_status`       VARCHAR(32)  NOT NULL DEFAULT '' COMMENT '转发状态',
            `improvmx_error`        LONGTEXT     NOT NULL COMMENT 'ImprovMX 错误信息',
            `env_id`                VARCHAR(128) NOT NULL DEFAULT '' COMMENT 'HubStudio 环境 ID',
            `env_name`              VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'HubStudio 环境名称',
            `env_status`            VARCHAR(32)  NOT NULL DEFAULT '' COMMENT '环境状态',
            `env_error`             LONGTEXT     NOT NULL COMMENT '环境创建错误信息',
            `sms_request_id`        INT          NULL COMMENT 'SMSMan request_id',
            `sms_phone_number`      VARCHAR(64)  NOT NULL DEFAULT '' COMMENT 'SMS 号码',
            `sms_code`              VARCHAR(16)  NOT NULL DEFAULT '' COMMENT 'SMS 验证码',
            `sms_status`            VARCHAR(32)  NOT NULL DEFAULT '' COMMENT 'SMS 状态',
            `sms_error`             LONGTEXT     NOT NULL COMMENT 'SMS 错误信息',
            `registration_email`    VARCHAR(255) NOT NULL DEFAULT '' COMMENT '注册成功的 Gmail 地址',
            `registration_status`   VARCHAR(32)  NOT NULL DEFAULT 'pending' COMMENT '注册状态',
            `registration_error`    LONGTEXT     NOT NULL COMMENT '注册失败错误信息',
            `remark`                LONGTEXT     NOT NULL COMMENT '备注',
            `created_at`            DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
            `updated_at`            DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
            UNIQUE KEY `uid_alias_domain` (`alias`, `domain`),
            KEY `idx_alias`               (`alias`),
            KEY `idx_domain`              (`domain`),
            KEY `idx_site_id`             (`site_id`),
            KEY `idx_improvmx_status`     (`improvmx_status`),
            KEY `idx_env_id`              (`env_id`),
            KEY `idx_env_status`          (`env_status`),
            KEY `idx_sms_request_id`      (`sms_request_id`),
            KEY `idx_sms_status`          (`sms_status`),
            KEY `idx_registration_email`  (`registration_email`),
            KEY `idx_registration_status` (`registration_status`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Gmail 企业邮箱注册流程记录';
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS `site_pipeline_gmail_registration`;
    """
