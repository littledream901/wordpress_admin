"""数据库迁移问题诊断脚本"""
import asyncio
import sys
from tortoise import Tortoise
from app.settings.config import settings

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


async def diagnose():
    """诊断数据库迁移状态"""
    print("=" * 60)
    print("数据库迁移诊断")
    print("=" * 60)
    
    await Tortoise.init(config=settings.TORTOISE_ORM)
    conn = Tortoise.get_connection('default')
    
    # 1. 检查数据库连接
    print("\n[OK] 数据库连接成功")
    print(f"  数据库: {settings.DB_NAME}")
    print(f"  主机: {settings.DB_HOST}:{settings.DB_PORT}")
    
    # 2. 列出所有表
    print("\n=== 现有数据库表 ===")
    tables = await conn.execute_query_dict('SHOW TABLES')
    table_names = [list(t.values())[0] for t in tables]
    
    for table in sorted(table_names):
        print(f"  [+] {table}")
    
    # 3. 检查 aerich 表
    print("\n=== aerich 迁移表检查 ===")
    if 'aerich' in table_names:
        print("  [OK] aerich 表存在")
        
        # 查看迁移历史
        migrations = await conn.execute_query_dict(
            'SELECT version, app FROM aerich ORDER BY id'
        )
        print(f"  已应用迁移数: {len(migrations)}")
        for m in migrations:
            print(f"    - {m['version']} (app: {m['app']})")
    else:
        print("  [ERROR] aerich 表不存在 - 这是问题根源！")
        print("  原因: aerich 需要此表来追踪迁移历史")
    
    # 4. 检查新表
    print("\n=== HubStudio 代理配置表检查 ===")
    if 'hubstudio_proxy_config' in table_names:
        print("  [OK] hubstudio_proxy_config 表已存在")
        count = await conn.execute_query_dict(
            'SELECT COUNT(*) as cnt FROM hubstudio_proxy_config'
        )
        print(f"  代理配置数量: {count[0]['cnt']}")
    else:
        print("  [ERROR] hubstudio_proxy_config 表不存在")
        print("  需要执行: migrations/manual/001_add_hubstudio_proxy_config.sql")
    
    # 5. 检查 Site 表字段
    print("\n=== Site 表字段检查 ===")
    if 'site_pipeline_site' in table_names:
        columns = await conn.execute_query_dict(
            "SHOW COLUMNS FROM site_pipeline_site LIKE 'proxy_config_id'"
        )
        if columns:
            print("  [OK] proxy_config_id 字段已存在")
        else:
            print("  [ERROR] proxy_config_id 字段不存在")
            print("  需要执行: ALTER TABLE site_pipeline_site ADD COLUMN proxy_config_id")
    
    # 6. 检查迁移文件
    print("\n=== 迁移文件检查 ===")
    import os
    migration_dir = 'migrations/models'
    if os.path.exists(migration_dir):
        files = sorted([f for f in os.listdir(migration_dir) if f.endswith('.py')])
        print(f"  迁移文件数量: {len(files)}")
        for f in files:
            print(f"    - {f}")
    
    # 7. 生成修复建议
    print("\n" + "=" * 60)
    print("修复建议")
    print("=" * 60)
    
    if 'aerich' not in table_names:
        print("\n[FIX] 问题1: aerich 表缺失")
        print("解决方案:")
        print("  1. 需要初始化 aerich 数据库")
        print("  2. 由于已有迁移文件，需要手动创建 aerich 表并插入历史记录")
        print("\n执行以下 SQL:")
        print("""
  CREATE TABLE `aerich` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `version` VARCHAR(255) NOT NULL,
    `app` VARCHAR(100) NOT NULL,
    `content` JSON NOT NULL
  );
  
  -- 插入已应用的迁移记录（根据实际情况调整）
  INSERT INTO `aerich` (`version`, `app`, `content`) VALUES
    ('1_20260713043940_None.py', 'models', '{}'),
    ('2_20260713143913_update.py', 'models', '{}'),
    ('3_20260713162304_update.py', 'models', '{}'),
    ('4_20260809000000_gateway_defense.py', 'models', '{}'),
    ('5_20260810000000_add_gateway_site_id.py', 'models', '{}'),
    ('6_20260810120000_add_gmail_registration.py', 'models', '{}'),
    ('7_20260810130000_add_outlook_to_gmail_registration.py', 'models', '{}'),
    ('8_20260810150000_add_outlook_account.py', 'models', '{}'),
    ('9_20260810160000_add_gmail_registration_two_fa_key.py', 'models', '{}');
        """)
    
    if 'hubstudio_proxy_config' not in table_names:
        print("\n[FIX] 问题2: hubstudio_proxy_config 表缺失")
        print("解决方案:")
        print("  执行: migrations/manual/001_add_hubstudio_proxy_config.sql")
    
    await Tortoise.close_connections()
    
    print("\n" + "=" * 60)
    print("诊断完成")
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(diagnose())
