from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `site_pipeline_outlook_account` 
        ADD COLUMN `api_url` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '接码地址' AFTER `recovery_email`;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `site_pipeline_outlook_account` 
        DROP COLUMN `api_url`;
    """
