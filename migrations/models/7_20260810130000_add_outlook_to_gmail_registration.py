from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `site_pipeline_gmail_registration`
        ADD COLUMN `outlook_account_id` INT NULL COMMENT '分配的 Outlook 账号 ID' AFTER `sms_error`,
        ADD COLUMN `outlook_account_username` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Outlook 账号用户名（冗余，便于展示）' AFTER `outlook_account_id`,
        ADD COLUMN `is_deleted` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '软删除标记' AFTER `outlook_account_username`,
        ADD COLUMN `deleted_at` DATETIME NULL COMMENT '删除时间' AFTER `is_deleted`,
        ADD KEY `idx_outlook_account_id` (`outlook_account_id`),
        ADD KEY `idx_is_deleted` (`is_deleted`);
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `site_pipeline_gmail_registration`
        DROP INDEX `idx_is_deleted`,
        DROP INDEX `idx_outlook_account_id`,
        DROP COLUMN `deleted_at`,
        DROP COLUMN `is_deleted`,
        DROP COLUMN `outlook_account_username`,
        DROP COLUMN `outlook_account_id`;
    """
