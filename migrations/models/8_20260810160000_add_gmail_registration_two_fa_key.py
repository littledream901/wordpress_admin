from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `site_pipeline_gmail_registration`
        ADD COLUMN `two_fa_key` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '2FA Key' AFTER `recovery_email`;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `site_pipeline_gmail_registration`
        DROP COLUMN `two_fa_key`;
    """
