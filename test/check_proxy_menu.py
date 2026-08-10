"""检查并强制同步「代理管理」菜单 + API 权限"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    from tortoise import Tortoise
    from app.settings.config import settings

    await Tortoise.init(config=settings.TORTOISE_ORM)

    from app.models.admin import Menu, Api, Role

    print("=== 1. 当前 site-pipeline 下的菜单 ===")
    parent = await Menu.get_or_none(path="/site-pipeline", parent_id=0)
    if not parent:
        print("!! 未找到父菜单 /site-pipeline")
        await Tortoise.close_connections()
        return
    children = await Menu.filter(parent_id=parent.id).order_by("order")
    for m in children:
        print(f"  id={m.id:<4} order={m.order:<3} path={m.path:<16} hidden={m.is_hidden} name={m.name}")

    proxy_menu = await Menu.get_or_none(path="proxy-config", parent_id=parent.id)
    print(f"\n=== 2. 代理管理菜单是否存在: {bool(proxy_menu)} ===")

    if not proxy_menu:
        print(">> 强制执行 init_menus() 同步菜单")
        from app.core.init_app import init_menus
        await init_menus()
        proxy_menu = await Menu.get_or_none(path="proxy-config", parent_id=parent.id)
        print(f">> 同步后是否存在: {bool(proxy_menu)}")

    if proxy_menu and proxy_menu.is_hidden:
        proxy_menu.is_hidden = False
        await proxy_menu.save(update_fields=["is_hidden"])
        print(">> 菜单原为隐藏，已改为显示")

    print("\n=== 3. hubstudio-proxy 相关 API 记录 ===")
    apis = await Api.filter(path__contains="hubstudio-proxy")
    if not apis:
        print("!! 无记录，强制执行 init_apis()")
        from app.core.init_app import init_apis
        await init_apis()
        apis = await Api.filter(path__contains="hubstudio-proxy")
    for a in apis:
        print(f"  {a.method:<7} {a.path}")

    print("\n=== 4. 角色授权情况 ===")
    roles = await Role.all()
    for role in roles:
        menu_ids = await role.menus.all().values_list("id", flat=True)
        has_menu = proxy_menu and proxy_menu.id in menu_ids
        api_paths = await role.apis.all().values_list("path", flat=True)
        api_cnt = len([p for p in api_paths if "hubstudio-proxy" in p])
        print(f"  role={role.name:<12} code={role.code}  含代理菜单={has_menu}  代理API数={api_cnt}")

        # 给 admin 角色补齐授权
        if role.code == "admin":
            if proxy_menu and not has_menu:
                await role.menus.add(proxy_menu)
                print(f"    >> 已为 {role.name} 添加代理管理菜单")
            missing = [a for a in apis if a.path not in api_paths]
            if missing:
                await role.apis.add(*missing)
                print(f"    >> 已为 {role.name} 添加 {len(missing)} 个代理 API 权限")

    await Tortoise.close_connections()
    print("\n完成。请刷新浏览器（Ctrl+F5）。")


if __name__ == "__main__":
    asyncio.run(main())
