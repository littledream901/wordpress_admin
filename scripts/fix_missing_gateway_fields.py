"""
快速修复脚本：添加缺失的 gateway 相关字段
使用方式: python scripts/fix_missing_gateway_fields.py
"""
import asyncio
import os
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tortoise import Tortoise
from app.settings.config import settings


async def check_and_add_fields():
    """检查并添加缺失的 gateway 字段"""
    print("🔍 连接数据库...")
    
    await Tortoise.init(config=settings.TORTOISE_ORM)
    conn = Tortoise.get_connection("default")
    
    try:
        # 检查字段是否存在
        print("🔍 检查 gateway_defense_status 字段是否存在...")
        result = await conn.execute_query_dict("DESCRIBE site_pipeline_site")
        existing_fields = {row['Field'] for row in result}
        
        if 'gateway_defense_status' in existing_fields:
            print("✅ gateway 字段已存在，无需添加")
            return
        
        print("⚠️  gateway 字段不存在，开始添加...")
        
        # 执行 ALTER TABLE 添加字段（来自迁移文件 4）
        sql = """
        ALTER TABLE `site_pipeline_site` 
          ADD COLUMN `gateway_defense_status` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '网关防御状态' AFTER `shopify_token`,
          ADD COLUMN `gateway_defense_type` VARCHAR(32) NOT NULL DEFAULT '' COMMENT '网关防御类型: worker / nginx_lua' AFTER `gateway_defense_status`,
          ADD COLUMN `gateway_site_key` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '网关站点密钥' AFTER `gateway_defense_type`,
          ADD COLUMN `gateway_site_secret` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '网关签名密钥' AFTER `gateway_site_key`,
          ADD COLUMN `gateway_deployed_at` DATETIME(6) NULL COMMENT '网关部署时间' AFTER `gateway_site_secret`,
          ADD COLUMN `gateway_config_json` TEXT COMMENT '网关配置(JSON)' AFTER `gateway_deployed_at`,
          ADD COLUMN `gateway_last_error` TEXT COMMENT '最后错误信息' AFTER `gateway_config_json`,
          ADD INDEX `idx_gateway_defense_status` (`gateway_defense_status`);
        """
        
        await conn.execute_script(sql)
        print("✅ gateway 字段添加成功")
        
        # 检查 gateway_site_id 字段（来自迁移文件 5）
        result = await conn.execute_query_dict("DESCRIBE site_pipeline_site")
        existing_fields = {row['Field'] for row in result}
        
        if 'gateway_site_id' not in existing_fields:
            print("⚠️  gateway_site_id 字段不存在，开始添加...")
            sql_site_id = """
            ALTER TABLE `site_pipeline_site` 
              ADD COLUMN `gateway_site_id` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '网关侧站点标识（必须外部提供）' AFTER `gateway_defense_type`;
            """
            await conn.execute_script(sql_site_id)
            print("✅ gateway_site_id 字段添加成功")
        
        # 验证所有 gateway 字段
        result = await conn.execute_query_dict("DESCRIBE site_pipeline_site")
        gateway_fields = [row['Field'] for row in result if 'gateway' in row['Field']]
        print(f"\n✅ 当前所有 gateway 字段:")
        for field in gateway_fields:
            print(f"   - {field}")
        
    except Exception as e:
        print(f"❌ 操作失败: {e}")
        raise
    finally:
        await Tortoise.close_connections()
        print("\n🔌 数据库连接已关闭")


if __name__ == "__main__":
    print("=" * 60)
    print("Gateway 字段修复脚本")
    print("=" * 60)
    asyncio.run(check_and_add_fields())
    print("\n✅ 修复完成！现在可以重启应用了。")
