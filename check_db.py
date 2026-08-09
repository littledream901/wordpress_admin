"""检查数据库表字段"""
import asyncio
from tortoise import Tortoise
from app.settings.config import settings

async def check_columns():
    db_url = f"mysql://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
    await Tortoise.init(
        db_url=db_url,
        modules={"models": ["app.models"]},
    )
    conn = Tortoise.get_connection("default")
    
    # 检查 site_pipeline_site 表的 browser 相关字段
    result = await conn.execute_query(
        "SHOW COLUMNS FROM site_pipeline_site WHERE Field LIKE 'browser%'"
    )
    
    print("=== site_pipeline_site 表中的 browser 字段 ===")
    for row in result[1]:
        print(f"  {row['Field']}: {row['Type']} | Null={row['Null']} | Default={row['Default']}")
    
    await Tortoise.close_connections()

if __name__ == "__main__":
    asyncio.run(check_columns())
