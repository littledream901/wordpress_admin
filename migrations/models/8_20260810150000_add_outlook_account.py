from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `site_pipeline_outlook_account` (
            `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
            `last_name` VARCHAR(100) NOT NULL DEFAULT '' COMMENT 'last name',
            `first_name` VARCHAR(100) NOT NULL DEFAULT '' COMMENT 'first name',
            `full_name` VARCHAR(200) NOT NULL DEFAULT '' COMMENT 'full name',
            `zip_code` VARCHAR(32) NOT NULL DEFAULT '' COMMENT 'zip code',
            `shipping_address_1` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Shipping address 1',
            `shipping_address_2` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Shipping address 2',
            `country` VARCHAR(100) NOT NULL DEFAULT '' COMMENT 'Country',
            `province_state` VARCHAR(100) NOT NULL DEFAULT '' COMMENT 'Province/State',
            `city` VARCHAR(100) NOT NULL DEFAULT '' COMMENT 'City',
            `phone` VARCHAR(64) NOT NULL DEFAULT '' COMMENT 'phone',
            `username` VARCHAR(255) NOT NULL COMMENT 'Username',
            `password` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Password',
            `two_fa_key` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '2FA Key',
            `two_fa_code` VARCHAR(16) NOT NULL DEFAULT '' COMMENT '2FA 验证码',
            `link_to_generate_login_code` VARCHAR(500) NOT NULL DEFAULT '' COMMENT 'Link To Generate Login Code from 2FA Key',
            `recovery_email` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Recovery Email',
            `status` VARCHAR(64) NOT NULL DEFAULT '正常' COMMENT '健康状态',
            `assigned_site_id` INT NULL COMMENT '分配站点ID',
            `assigned_site_domain` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '分配站点域名',
            `is_deleted` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '软删除标记',
            `deleted_at` DATETIME NULL COMMENT '删除时间',
            `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
            UNIQUE KEY `uid_site_pipel_usernam_8a9f0b` (`username`),
            KEY `idx_site_pipel_id_c14b90` (`id`),
            KEY `idx_site_pipel_usernam_a55c3d` (`username`),
            KEY `idx_site_pipel_status_7c0a8b` (`status`),
            KEY `idx_site_pipel_assigne_f30b4a` (`assigned_site_id`),
            KEY `idx_site_pipel_is_dele_a51b3f` (`is_deleted`),
            KEY `idx_site_pipel_created_89c73d` (`created_at`),
            KEY `idx_site_pipel_updated_6cd6c2` (`updated_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Outlook 账号库';
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS `site_pipeline_outlook_account`;
    """
