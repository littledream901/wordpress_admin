"""
手动执行网关防御迁移脚本
绕过 Aerich 旧格式检查问题
"""
import asyncio
import aiomysql
from dotenv import load_dotenv
import os

# 加载环境变量
load_dotenv()

DB_HOST = os.getenv('DB_HOST', '192.168.0.110')
DB_PORT = int(os.getenv('DB_PORT', 3306))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_NAME = os.getenv('DB_NAME', 'vue_fastapi_admin')

# 迁移 SQL
MIGRATION_SQL = """
ALTER TABLE `site_pipeline_site` 
ADD COLUMN `gateway_defense_status` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '网关防御状态' AFTER `shopify_token`,
ADD COLUMN `gateway_defense_type` VARCHAR(32) NOT NULL DEFAULT '' COMMENT '网关防御类型: worker / nginx_lua' AFTER `gateway_defense_status`,
ADD COLUMN `gateway_site_key` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '网关站点密钥 (site_xxxxxxxx)' AFTER `gateway_defense_type`,
ADD COLUMN `gateway_site_secret` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '网关签名密钥' AFTER `gateway_site_key`,
ADD COLUMN `gateway_deployed_at` DATETIME(6) NULL COMMENT '网关部署时间' AFTER `gateway_site_secret`,
ADD COLUMN `gateway_config_json` TEXT COMMENT '网关配置(JSON)' AFTER `gateway_deployed_at`,
ADD COLUMN `gateway_last_error` TEXT COMMENT '最后错误信息' AFTER `gateway_config_json`,
ADD INDEX `idx_gateway_defense_status` (`gateway_defense_status`);
"""

async def main():
    print(f"连接数据库: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    
    conn = await aiomysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        db=DB_NAME,
        charset='utf8mb4'
    )
    
    try:
        async with conn.cursor() as cursor:
            # 检查字段是否已存在
            await cursor.execute("""
                SELECT COUNT(*) 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = %s 
                AND TABLE_NAME = 'site_pipeline_site' 
                AND COLUMN_NAME = 'gateway_defense_status'
            """, (DB_NAME,))
            
            result = await cursor.fetchone()
            
            if result[0] > 0:
                print("✓ 迁移已执行过，字段已存在")
                return
            
            print("开始执行迁移...")
            await cursor.execute(MIGRATION_SQL)
            await conn.commit()
            print("✓ 迁移执行成功")
            
            # 验证字段是否创建成功
            await cursor.execute("""
                SELECT COLUMN_NAME 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = %s 
                AND TABLE_NAME = 'site_pipeline_site' 
                AND COLUMN_NAME LIKE 'gateway_%%'
            """, (DB_NAME,))
            
            columns = await cursor.fetchall()
            print(f"\n已创建的字段 ({len(columns)} 个):")
            for col in columns:
                print(f"  - {col[0]}")
                
    except Exception as e:
        print(f"✗ 迁移失败: {e}")
        await conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    asyncio.run(main())
