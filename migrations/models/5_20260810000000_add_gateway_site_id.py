from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `site_pipeline_site` 
        ADD COLUMN `gateway_site_id` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '网关侧站点标识（必须外部提供）' AFTER `gateway_defense_type`;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `site_pipeline_site` 
        DROP COLUMN `gateway_site_id`;
    """
