"""Check the actual schema of gmail_registration table"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from tortoise import Tortoise
from app.settings.config import settings


async def check_schema():
    """Check gmail_registration table schema"""
    print("Connecting to database...")
    await Tortoise.init(config=settings.TORTOISE_ORM)
    conn = Tortoise.get_connection('default')
    
    try:
        # Get all columns
        check_sql = """
        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_COMMENT
        FROM information_schema.COLUMNS 
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'site_pipeline_gmail_registration'
        ORDER BY ORDINAL_POSITION
        """
        print("\nQuerying table schema...")
        result = await conn.execute_query_dict(check_sql)
        
        print(f"\n{'Column Name':<30} {'Type':<15} {'Nullable':<10} {'Comment':<30}")
        print("-" * 90)
        for row in result:
            col_name = row['COLUMN_NAME']
            col_type = row['DATA_TYPE']
            nullable = row['IS_NULLABLE']
            comment = row['COLUMN_COMMENT'] or ''
            print(f"{col_name:<30} {col_type:<15} {nullable:<10} {comment:<30}")
        
        print(f"\nTotal columns: {len(result)}")
        
        # Check specifically for site_id
        has_site_id = any(row['COLUMN_NAME'] == 'site_id' for row in result)
        print(f"\n✓ site_id column exists: {has_site_id}")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await Tortoise.close_connections()
        print("\nDatabase connection closed")


if __name__ == "__main__":
    asyncio.run(check_schema())
