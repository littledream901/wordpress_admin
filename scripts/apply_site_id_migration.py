"""Apply site_id column migration to gmail_registration table"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from tortoise import Tortoise
from app.settings.config import settings


async def apply_migration():
    """Add site_id column to site_pipeline_gmail_registration table"""
    print("Connecting to database...")
    await Tortoise.init(config=settings.TORTOISE_ORM)
    conn = Tortoise.get_connection('default')
    
    try:
        # Check if column already exists
        check_sql = """
        SELECT COUNT(*) as count 
        FROM information_schema.COLUMNS 
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'site_pipeline_gmail_registration' 
        AND COLUMN_NAME = 'site_id'
        """
        print("Checking if site_id column exists...")
        result = await conn.execute_query_dict(check_sql)
        
        if result[0]['count'] > 0:
            print("✓ Column 'site_id' already exists, skipping migration")
        else:
            # Add the column and index
            print("Adding site_id column and index...")
            alter_sql = """
            ALTER TABLE `site_pipeline_gmail_registration` 
            ADD COLUMN `site_id` INT NULL COMMENT '关联站点ID' AFTER `domain`,
            ADD INDEX `idx_site_id` (`site_id`)
            """
            await conn.execute_script(alter_sql)
            print("✓ Migration applied successfully: Added site_id column and index")
    
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        await Tortoise.close_connections()
        print("Database connection closed")


if __name__ == "__main__":
    asyncio.run(apply_migration())
