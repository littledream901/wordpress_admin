"""全面检测模型定义与数据库实际结构的差异"""
import asyncio
import sys
from typing import Dict, Set
from tortoise import Tortoise
from app.settings.config import settings

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


async def get_db_tables_and_columns(conn) -> Dict[str, Set[str]]:
    """获取数据库中所有表及其列"""
    result = {}
    
    # 获取所有表
    tables_query = f"""
        SELECT TABLE_NAME 
        FROM information_schema.TABLES 
        WHERE TABLE_SCHEMA = '{settings.DB_NAME}'
    """
    tables = await conn.execute_query_dict(tables_query)
    
    for table_row in tables:
        table_name = table_row['TABLE_NAME']
        
        # 获取该表的所有列
        columns_query = f"""
            SELECT COLUMN_NAME 
            FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = '{settings.DB_NAME}' 
            AND TABLE_NAME = '{table_name}'
        """
        columns = await conn.execute_query_dict(columns_query)
        result[table_name] = {col['COLUMN_NAME'] for col in columns}
    
    return result


async def get_model_tables_and_fields() -> Dict[str, Set[str]]:
    """从 Tortoise 模型中提取表名和字段"""
    result = {}
    
    for app_name, models_dict in Tortoise.apps.items():
        for model_name, model_class in models_dict.items():
            # 跳过 Aerich 模型
            if model_name == 'Aerich':
                continue
                
            table_name = model_class._meta.db_table or model_name.lower()
            fields = set(model_class._meta.fields_map.keys())
            
            # 移除关系字段（ForeignKey, ManyToMany 等的反向字段）
            fields = {f for f in fields if not f.endswith('_relation')}
            
            result[table_name] = fields
    
    return result


async def check_schema_diff():
    """检测模型与数据库的差异"""
    print("=" * 80)
    print("数据库结构差异检测")
    print("=" * 80)
    
    await Tortoise.init(config=settings.TORTOISE_ORM)
    conn = Tortoise.get_connection('default')
    
    print(f"\n[连接] 数据库: {settings.DB_NAME} @ {settings.DB_HOST}:{settings.DB_PORT}")
    
    # 获取数据库实际结构
    print("\n[步骤1] 读取数据库实际结构...")
    db_schema = await get_db_tables_and_columns(conn)
    print(f"  数据库中的表数量: {len(db_schema)}")
    
    # 获取模型定义
    print("\n[步骤2] 读取 Tortoise 模型定义...")
    model_schema = await get_model_tables_and_fields()
    print(f"  模型定义的表数量: {len(model_schema)}")
    
    # 检查 aerich 表
    print("\n" + "=" * 80)
    print("关键检查: aerich 迁移表")
    print("=" * 80)
    if 'aerich' in db_schema:
        print("  [OK] aerich 表存在")
        migrations = await conn.execute_query_dict(
            'SELECT id, version, app FROM aerich ORDER BY id'
        )
        print(f"  已记录的迁移数: {len(migrations)}")
        for m in migrations:
            print(f"    #{m['id']}: {m['version']}")
    else:
        print("  [ERROR] aerich 表不存在")
        print("  -> 这会导致 aerich migrate/upgrade 无法工作")
    
    # 对比差异
    print("\n" + "=" * 80)
    print("结构差异分析")
    print("=" * 80)
    
    model_tables = set(model_schema.keys())
    db_tables = set(db_schema.keys())
    
    # 1. 模型中定义但数据库中缺失的表
    missing_tables = model_tables - db_tables
    if missing_tables:
        print(f"\n[缺失表] 模型中有定义，但数据库中不存在 ({len(missing_tables)} 个):")
        for table in sorted(missing_tables):
            fields = model_schema[table]
            print(f"  - {table} (字段数: {len(fields)})")
            print(f"    字段: {', '.join(sorted(fields)[:10])}" + 
                  ("..." if len(fields) > 10 else ""))
    else:
        print("\n[缺失表] 无")
    
    # 2. 数据库中存在但模型中未定义的表
    extra_tables = db_tables - model_tables
    if extra_tables:
        print(f"\n[多余表] 数据库中存在，但模型中未定义 ({len(extra_tables)} 个):")
        for table in sorted(extra_tables):
            print(f"  - {table}")
    else:
        print("\n[多余表] 无")
    
    # 3. 字段差异（只检查共同存在的表）
    common_tables = model_tables & db_tables
    print(f"\n[字段差异] 检查共同存在的表 ({len(common_tables)} 个)...")
    
    has_field_diff = False
    for table in sorted(common_tables):
        model_fields = model_schema[table]
        db_fields = db_schema[table]
        
        missing_fields = model_fields - db_fields
        extra_fields = db_fields - model_fields
        
        if missing_fields or extra_fields:
            has_field_diff = True
            print(f"\n  表: {table}")
            
            if missing_fields:
                print(f"    [缺失字段] 模型中有，数据库中无:")
                for field in sorted(missing_fields):
                    print(f"      - {field}")
            
            if extra_fields:
                print(f"    [多余字段] 数据库中有，模型中无:")
                for field in sorted(extra_fields):
                    print(f"      - {field}")
    
    if not has_field_diff:
        print("  [OK] 所有共同表的字段都一致")
    
    # 检查关键表
    print("\n" + "=" * 80)
    print("关键表检查")
    print("=" * 80)
    
    # HubStudio 代理配置表
    print("\n[hubstudio_proxy_config]")
    if 'hubstudio_proxy_config' in db_schema:
        print("  [OK] 表存在")
        count = await conn.execute_query_dict(
            'SELECT COUNT(*) as cnt FROM hubstudio_proxy_config'
        )
        print(f"  记录数: {count[0]['cnt']}")
    else:
        print("  [ERROR] 表不存在")
        if 'hubstudio_proxy_config' in model_schema:
            print(f"  模型定义的字段 ({len(model_schema['hubstudio_proxy_config'])} 个):")
            for field in sorted(model_schema['hubstudio_proxy_config'])[:15]:
                print(f"    - {field}")
    
    # Site 表的 proxy_config_id 字段
    print("\n[site_pipeline_site.proxy_config_id]")
    if 'site_pipeline_site' in db_schema:
        if 'proxy_config_id' in db_schema['site_pipeline_site']:
            print("  [OK] 字段存在")
        else:
            print("  [ERROR] 字段不存在")
            if 'site_pipeline_site' in model_schema:
                if 'proxy_config_id' in model_schema['site_pipeline_site']:
                    print("  -> 模型中已定义此字段，需要执行迁移")
    
    # 总结
    print("\n" + "=" * 80)
    print("总结")
    print("=" * 80)
    
    issues = []
    if 'aerich' not in db_schema:
        issues.append("aerich 表缺失 - 迁移系统无法工作")
    if missing_tables:
        issues.append(f"{len(missing_tables)} 个表需要创建")
    if has_field_diff:
        issues.append("部分表的字段不一致")
    
    if issues:
        print("\n发现的问题:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    else:
        print("\n[OK] 数据库结构与模型定义完全一致")
    
    await Tortoise.close_connections()
    
    print("\n" + "=" * 80)
    print("检测完成")
    print("=" * 80)


if __name__ == '__main__':
    asyncio.run(check_schema_diff())
