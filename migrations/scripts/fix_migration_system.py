"""修复迁移系统 - 创建缺失的表和字段（幂等安全）"""
import asyncio
import sys
from tortoise import Tortoise
from app.settings.config import settings

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


async def table_exists(conn, table_name: str) -> bool:
    """检查表是否存在"""
    query = f"""
        SELECT COUNT(*) as cnt
        FROM information_schema.TABLES 
        WHERE TABLE_SCHEMA = '{settings.DB_NAME}' 
        AND TABLE_NAME = '{table_name}'
    """
    result = await conn.execute_query_dict(query)
    return result[0]['cnt'] > 0


async def column_exists(conn, table_name: str, column_name: str) -> bool:
    """检查列是否存在"""
    query = f"""
        SELECT COUNT(*) as cnt
        FROM information_schema.COLUMNS 
        WHERE TABLE_SCHEMA = '{settings.DB_NAME}' 
        AND TABLE_NAME = '{table_name}'
        AND COLUMN_NAME = '{column_name}'
    """
    result = await conn.execute_query_dict(query)
    return result[0]['cnt'] > 0


async def index_exists(conn, table_name: str, index_name: str) -> bool:
    """检查索引是否存在"""
    query = f"""
        SELECT COUNT(*) as cnt
        FROM information_schema.STATISTICS 
        WHERE TABLE_SCHEMA = '{settings.DB_NAME}' 
        AND TABLE_NAME = '{table_name}'
        AND INDEX_NAME = '{index_name}'
    """
    result = await conn.execute_query_dict(query)
    return result[0]['cnt'] > 0


async def fix_migration_system():
    """修复迁移系统"""
    print("=" * 80)
    print("数据库迁移系统修复脚本")
    print("=" * 80)
    print(f"\n目标数据库: {settings.DB_NAME} @ {settings.DB_HOST}:{settings.DB_PORT}")
    print("\n此脚本将:")
    print("  1. 创建 aerich 元数据表（如果不存在）")
    print("  2. 插入历史迁移记录")
    print("  3. 创建 hubstudio_proxy_config 表（如果不存在）")
    print("  4. 为 site_pipeline_site 表添加 proxy_config_id 字段（如果不存在）")
    print("  5. 插入全局默认代理配置")
    print("\n所有操作都是幂等的，可以安全重复执行。")
    
    # 等待用户确认
    print("\n" + "=" * 80)
    response = input("确认执行？(yes/no): ").strip().lower()
    if response != 'yes':
        print("操作已取消")
        return
    
    await Tortoise.init(config=settings.TORTOISE_ORM)
    conn = Tortoise.get_connection('default')
    
    print("\n" + "=" * 80)
    print("开始执行修复")
    print("=" * 80)
    
    # ========== 1. 创建 aerich 表 ==========
    print("\n[步骤1] 检查 aerich 表...")
    if await table_exists(conn, 'aerich'):
        print("  [跳过] aerich 表已存在")
    else:
        print("  [执行] 创建 aerich 表...")
        create_aerich_sql = """
            CREATE TABLE `aerich` (
                `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
                `version` VARCHAR(255) NOT NULL,
                `app` VARCHAR(100) NOT NULL,
                `content` JSON NOT NULL
            ) CHARACTER SET utf8mb4 COMMENT='Aerich 迁移历史表'
        """
        await conn.execute_script(create_aerich_sql)
        print("  [完成] aerich 表创建成功")
    
    # ========== 2. 插入历史迁移记录 ==========
    print("\n[步骤2] 插入历史迁移记录...")
    
    # 检查已有记录
    existing = await conn.execute_query_dict("SELECT version FROM aerich")
    existing_versions = {row['version'] for row in existing}
    
    # 需要插入的迁移记录（按实际迁移文件顺序）
    migrations_to_insert = [
        '1_20260713043940_None.py',
        '2_20260713143913_update.py',
        '3_20260713162304_update.py',
        '4_20260809000000_gateway_defense.py',
        '5_20260810000000_add_gateway_site_id.py',
        '6_20260810120000_add_gmail_registration.py',
        '7_20260810130000_add_outlook_to_gmail_registration.py',
        '8_20260810150000_add_outlook_account.py',
        '9_20260810160000_add_gmail_registration_two_fa_key.py',
    ]
    
    inserted_count = 0
    for version in migrations_to_insert:
        if version not in existing_versions:
            # 插入空的 content，因为这些是历史迁移
            await conn.execute_query(
                "INSERT INTO aerich (version, app, content) VALUES (%s, %s, %s)",
                [version, 'models', '{}']
            )
            print(f"  [+] {version}")
            inserted_count += 1
        else:
            print(f"  [已存在] {version}")
    
    print(f"  [完成] 插入了 {inserted_count} 条新记录")
    
    # ========== 3. 创建 hubstudio_proxy_config 表 ==========
    print("\n[步骤3] 检查 hubstudio_proxy_config 表...")
    if await table_exists(conn, 'hubstudio_proxy_config'):
        print("  [跳过] hubstudio_proxy_config 表已存在")
    else:
        print("  [执行] 创建 hubstudio_proxy_config 表...")
        create_proxy_table_sql = """
            CREATE TABLE `hubstudio_proxy_config` (
                `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
                `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
                `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
                `name` VARCHAR(128) NOT NULL COMMENT '代理配置名称',
                `code` VARCHAR(64) NOT NULL COMMENT '代理配置唯一编码',
                `description` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '代理配置描述',
                `proxy_type_name` VARCHAR(32) NOT NULL DEFAULT 'HTTP' COMMENT '代理类型',
                `proxy_host` VARCHAR(255) NOT NULL COMMENT '代理服务器地址',
                `proxy_port` INT NOT NULL COMMENT '代理端口',
                `proxy_account` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '代理账号',
                `proxy_password` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '代理密码',
                `reference_country_code` VARCHAR(8) NOT NULL DEFAULT 'US' COMMENT '参考国家代码',
                `reference_city` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '参考城市',
                `reference_region_code` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '参考区域/省份代码',
                `as_dynamic_type` INT NOT NULL DEFAULT 0 COMMENT '动态代理类型: 0=固定IP 1=动态IP',
                `ip_get_rule_type` INT NOT NULL DEFAULT 1 COMMENT 'IP获取规则类型',
                `link_code` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '代理提取链接或API代码',
                `ip_database_channel` INT NOT NULL DEFAULT 0 COMMENT 'IP数据库渠道',
                `ip_protocol_type` INT NOT NULL DEFAULT 0 COMMENT 'IP协议类型',
                `use_fixed_proxy` BOOL NOT NULL DEFAULT 1 COMMENT '是否使用固定代理配置',
                `status` VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT '状态: active/disabled/testing',
                `priority` INT NOT NULL DEFAULT 0 COMMENT '优先级，数字越大优先级越高',
                `is_default` BOOL NOT NULL DEFAULT 0 COMMENT '是否为默认代理',
                `usage_count` INT NOT NULL DEFAULT 0 COMMENT '累计使用次数',
                `success_count` INT NOT NULL DEFAULT 0 COMMENT '成功次数',
                `last_used_at` DATETIME(6) NULL COMMENT '最后使用时间',
                `last_check_at` DATETIME(6) NULL COMMENT '最后健康检查时间',
                `provider_id` INT NOT NULL DEFAULT 0 COMMENT '绑定的 ConfigProvider ID，0 表示全局可用',
                UNIQUE KEY `uid_hubstudio_p_name` (`name`),
                UNIQUE KEY `uid_hubstudio_p_code` (`code`),
                KEY `idx_hubstudio_p_created` (`created_at`),
                KEY `idx_hubstudio_p_updated` (`updated_at`),
                KEY `idx_hubstudio_p_code` (`code`),
                KEY `idx_hubstudio_p_status` (`status`),
                KEY `idx_hubstudio_p_provider` (`provider_id`),
                KEY `idx_hubstudio_p_status_default` (`status`, `is_default`),
                KEY `idx_hubstudio_p_provider_status` (`provider_id`, `status`)
            ) CHARACTER SET utf8mb4 COMMENT='HubStudio 代理配置表'
        """
        await conn.execute_script(create_proxy_table_sql)
        print("  [完成] hubstudio_proxy_config 表创建成功")
    
    # ========== 4. 为 site_pipeline_site 添加 proxy_config_id 字段 ==========
    print("\n[步骤4] 检查 site_pipeline_site.proxy_config_id 字段...")
    if await column_exists(conn, 'site_pipeline_site', 'proxy_config_id'):
        print("  [跳过] proxy_config_id 字段已存在")
    else:
        print("  [执行] 添加 proxy_config_id 字段...")
        add_column_sql = """
            ALTER TABLE `site_pipeline_site`
            ADD COLUMN `proxy_config_id` INT NOT NULL DEFAULT 0 COMMENT '绑定的代理配置ID，0表示使用Provider默认代理'
        """
        await conn.execute_script(add_column_sql)
        print("  [完成] proxy_config_id 字段添加成功")
        
        # 添加索引
        print("  [执行] 添加索引...")
        if not await index_exists(conn, 'site_pipeline_site', 'idx_site_pipeli_proxy_c'):
            add_index_sql = """
                ALTER TABLE `site_pipeline_site`
                ADD INDEX `idx_site_pipeli_proxy_c` (`proxy_config_id`)
            """
            await conn.execute_script(add_index_sql)
            print("  [完成] 索引添加成功")
        else:
            print("  [跳过] 索引已存在")
    
    # ========== 5. 插入全局默认代理配置 ==========
    print("\n[步骤5] 检查默认代理配置...")
    default_exists = await conn.execute_query_dict(
        "SELECT COUNT(*) as cnt FROM hubstudio_proxy_config WHERE code = 'global_default_hubstudio'"
    )
    
    if default_exists[0]['cnt'] > 0:
        print("  [跳过] 全局默认代理配置已存在")
    else:
        print("  [执行] 插入全局默认代理配置...")
        insert_default_sql = """
            INSERT INTO `hubstudio_proxy_config` (
                `name`, `code`, `description`,
                `proxy_type_name`, `proxy_host`, `proxy_port`,
                `proxy_account`, `proxy_password`,
                `reference_country_code`, `reference_city`, `reference_region_code`,
                `as_dynamic_type`, `ip_get_rule_type`, `link_code`,
                `ip_database_channel`, `ip_protocol_type`,
                `use_fixed_proxy`, `status`, `priority`, `is_default`, `provider_id`
            ) VALUES (
                'HubStudio 全局默认代理', 'global_default_hubstudio', '系统默认的 HubStudio 动态代理配置',
                'HTTP', 'server.iphtml.biz', 15000,
                'uid-27498-zone-hubstudio', 'h4z3tsqc',
                'US', 'New York', 'CA',
                0, 1, '',
                0, 0,
                1, 'active', 100, 1, 0
            )
        """
        await conn.execute_script(insert_default_sql)
        print("  [完成] 默认代理配置插入成功")
    
    # ========== 6. 更新 aerich 表，记录此次修复为一个迁移 ==========
    print("\n[步骤6] 记录修复操作为迁移...")
    fix_version = '10_20260810170000_add_hubstudio_proxy_config_table.py'
    
    if fix_version in existing_versions:
        print(f"  [跳过] {fix_version} 已记录")
    else:
        await conn.execute_query(
            "INSERT INTO aerich (version, app, content) VALUES (%s, %s, %s)",
            [fix_version, 'models', '{}']
        )
        print(f"  [完成] {fix_version} 已记录")
    
    await Tortoise.close_connections()
    
    print("\n" + "=" * 80)
    print("修复完成")
    print("=" * 80)
    print("\n建议后续操作:")
    print("  1. 运行 test/check_db_schema_diff.py 验证修复结果")
    print("  2. 测试 aerich 命令: .venv\\Scripts\\aerich.exe heads")
    print("  3. 测试代理配置功能")


if __name__ == '__main__':
    asyncio.run(fix_migration_system())
