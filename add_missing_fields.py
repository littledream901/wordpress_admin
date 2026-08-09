"""手动添加缺失的 browser 字段"""
import asyncio
from tortoise import Tortoise
from app.settings.config import settings

async def add_fields():
    db_url = f"mysql://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
    await Tortoise.init(
        db_url=db_url,
        modules={"models": ["app.models"]},
    )
    conn = Tortoise.get_connection("default")
    
    # 添加 browser_last_error 和 browser_meta_json
    fields = [
        ("browser_last_error", "ALTER TABLE `site_pipeline_site` ADD COLUMN `browser_last_error` TEXT NULL COMMENT '浏览器错误信息'"),
        ("browser_meta_json", "ALTER TABLE `site_pipeline_site` ADD COLUMN `browser_meta_json` TEXT NULL COMMENT '浏览器扩展信息'"),
    ]
    
    for field_name, sql in fields:
        try:
            await conn.execute_query(sql)
            print(f"[OK] 成功添加字段: {field_name}")
        except Exception as e:
            if "Duplicate column" in str(e):
                print(f"[SKIP] 字段已存在: {field_name}")
            else:
                print(f"[ERROR] 添加字段失败: {field_name} - {e}")
    
    await Tortoise.close_connections()

if __name__ == "__main__":
    asyncio.run(add_fields())
