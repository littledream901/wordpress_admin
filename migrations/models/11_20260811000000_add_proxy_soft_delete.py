from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `hubstudio_proxy_config` ADD `is_deleted` BOOL NOT NULL DEFAULT 0 COMMENT '软删除标记';
        ALTER TABLE `hubstudio_proxy_config` ADD `deleted_at` DATETIME(6) COMMENT '删除时间';
        CREATE INDEX `idx_hubstudio_p_is_deleted` ON `hubstudio_proxy_config` (`is_deleted`);
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `hubstudio_proxy_config` DROP INDEX `idx_hubstudio_p_is_deleted`;
        ALTER TABLE `hubstudio_proxy_config` DROP COLUMN `is_deleted`;
        ALTER TABLE `hubstudio_proxy_config` DROP COLUMN `deleted_at`;
    """
