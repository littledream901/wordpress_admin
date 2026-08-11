"""
菜单路由诊断脚本
检查数据库菜单的 component 字段与前端 views 组件的匹配情况
"""
import asyncio
import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from tortoise import Tortoise
from app.models.admin import Menu
from app.settings import TORTOISE_ORM


async def diagnose_menu_routes():
    """诊断菜单路由配置"""
    await Tortoise.init(config=TORTOISE_ORM)
    
    print("=" * 80)
    print("菜单路由诊断报告")
    print("=" * 80)
    
    # 获取所有菜单
    menus = await Menu.all()
    
    # 前端 views 目录
    views_dir = Path(__file__).parent.parent / "web" / "src" / "views"
    
    issues = []
    valid_menus = []
    
    for menu in menus:
        if menu.is_hidden:
            continue
            
        component = menu.component
        if not component or component == "Layout":
            # 父级菜单，跳过
            continue
        
        # 前端拼接路径：/src/views + component + /index.vue
        expected_path = views_dir / component.lstrip("/") / "index.vue"
        
        if expected_path.exists():
            valid_menus.append({
                "id": menu.id,
                "name": menu.name,
                "path": menu.path,
                "component": menu.component,
                "status": "✓ OK"
            })
        else:
            issues.append({
                "id": menu.id,
                "name": menu.name,
                "path": menu.path,
                "component": menu.component,
                "parent_id": menu.parent_id,
                "expected_file": str(expected_path),
                "status": "✗ 组件文件不存在"
            })
    
    # 输出有问题的菜单
    if issues:
        print("\n【发现问题的菜单】")
        print("-" * 80)
        for issue in issues:
            print(f"ID: {issue['id']}")
            print(f"  名称: {issue['name']}")
            print(f"  路径: {issue['path']}")
            print(f"  父ID: {issue['parent_id']}")
            print(f"  Component: {issue['component']}")
            print(f"  期望文件: {issue['expected_file']}")
            print(f"  状态: {issue['status']}")
            print()
    else:
        print("\n【所有菜单组件路径正确】")
    
    # 输出正常的菜单
    print(f"\n【正常菜单数量】: {len(valid_menus)}")
    
    # 检查前端存在但后端没定义的组件
    print("\n【检查前端孤立组件】")
    print("-" * 80)
    
    defined_components = {menu.component.lstrip("/") for menu in menus if menu.component and menu.component != "Layout"}
    
    orphan_views = []
    for view_file in views_dir.rglob("*/index.vue"):
        # 排除特殊目录
        relative = view_file.relative_to(views_dir)
        parent_dir = str(relative.parent)
        
        if parent_dir in ["login", "error-page", "profile", "workbench"]:
            continue
        
        if parent_dir not in defined_components:
            orphan_views.append(parent_dir)
    
    if orphan_views:
        print("发现前端存在但后端菜单未定义的组件：")
        for orphan in sorted(orphan_views):
            print(f"  - {orphan}")
    else:
        print("没有孤立组件")
    
    print("\n" + "=" * 80)
    print(f"诊断完成 - 问题菜单: {len(issues)} 个")
    print("=" * 80)
    
    await Tortoise.close_connections()
    
    return len(issues)


if __name__ == "__main__":
    exit_code = asyncio.run(diagnose_menu_routes())
    sys.exit(exit_code)
