import logging
import re
from typing import Optional

from fastapi import APIRouter, Query

from app.controllers.menu import menu_controller
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.menus import MenuCreate, MenuUpdate
from app.utils.db_utils import safe_count

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Menu"])

# ── 路径校验正则 ──
_PATH_RE = re.compile(r'^[a-zA-Z0-9_\-/.]+$')  # 只允许字母/数字/下划线/连字符/点/斜杠


async def _validate_menu_path(parent_id: Optional[int], path: Optional[str]) -> str | None:
    """校验菜单路径，返回错误信息或 None"""
    if not path:
        return "路径不能为空"
    if not _PATH_RE.match(path):
        return f"路径包含非法字符: {path}，只允许字母/数字/下划线/连字符/斜杠"
    if parent_id and parent_id > 0:
        if path.startswith("/"):
            return f"子菜单路径不能以 / 开头: {path}（请用相对路径，如 monitor）"
    else:
        if not path.startswith("/"):
            return f"根菜单路径必须以 / 开头: {path}（如 /system、/onepanel-monitor）"
    return None


async def _validate_parent_exists(parent_id: Optional[int]) -> str | None:
    """校验 parent_id 是否存在"""
    if not parent_id or parent_id <= 0:
        return None
    if not await menu_controller.model.filter(id=parent_id).exists():
        return f"上级菜单不存在: id={parent_id}"
    return None


async def _validate_no_circular_ref(menu_id: Optional[int], parent_id: Optional[int]) -> str | None:
    """校验不会形成循环引用（不能将菜单设为自身或其子孙的父级）"""
    if not menu_id or not parent_id or parent_id <= 0:
        return None
    if menu_id == parent_id:
        return "不能将菜单的上级设为自己"
    # 检查 parent_id 是否是 menu_id 的子孙
    current = parent_id
    visited = set()
    while current and current > 0:
        if current == menu_id:
            return "不能将菜单的上级设为其子孙菜单（会形成循环引用）"
        if current in visited:
            break
        visited.add(current)
        parent_menu = await menu_controller.model.filter(id=current).first()
        if not parent_menu:
            break
        current = parent_menu.parent_id
    return None


async def _validate_menu_config(menu_type: Optional[str], component: Optional[str], redirect: Optional[str], parent_id: Optional[int]) -> str | None:
    """校验菜单配置完整性"""
    is_root = not parent_id or parent_id <= 0
    if menu_type == "catalog":
        if is_root and not redirect:
            return "根目录菜单必须设置跳转路径（redirect），否则点击无响应"
        # 目录菜单的 component 由前端路由统一使用 Layout，不强制校验
    elif menu_type == "menu":
        if not component:
            return "菜单必须设置组件路径（component），否则页面无法加载"
        if not component.startswith("/"):
            return f"菜单组件路径必须以 / 开头: {component}"
    return None


@router.get("/list", summary="查看菜单列表")
async def list_menu(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
):
    """一次性加载全部菜单，在内存中构建树（避免递归查询 N+1）"""
    all_menus = await menu_controller.model.all().order_by("order")
    menu_dicts = [await m.to_dict() for m in all_menus]
    by_id = {m["id"]: m for m in menu_dicts}
    for m in menu_dicts:
        m["children"] = []
    roots = []
    for m in menu_dicts:
        parent_id = m.get("parent_id", 0) or 0
        if parent_id == 0:
            roots.append(m)
        else:
            parent = by_id.get(parent_id)
            if parent:
                parent["children"].append(m)
            else:
                roots.append(m)
    return SuccessExtra(data=roots, total=len(roots), page=page, page_size=page_size)


@router.get("/get", summary="查看菜单")
async def get_menu(
    menu_id: int = Query(..., description="菜单id"),
):
    result = await menu_controller.get(id=menu_id)
    return Success(data=await result.to_dict())


@router.post("/create", summary="创建菜单")
async def create_menu(
    menu_in: MenuCreate,
):
    # 校验路径格式
    for err_func in [_validate_menu_path, _validate_parent_exists, _validate_no_circular_ref]:
        err = await err_func(menu_in.parent_id, menu_in.path) if err_func is _validate_menu_path else (
            await err_func(menu_in.parent_id) if err_func is _validate_parent_exists else
            await err_func(None, menu_in.parent_id)
        )
        if err:
            return Fail(msg=err)
    # 校验配置完整性
    err = await _validate_menu_config(menu_in.menu_type, menu_in.component, menu_in.redirect, menu_in.parent_id)
    if err:
        return Fail(msg=err)

    await menu_controller.create(obj_in=menu_in)
    return Success(msg="Created Success")


@router.post("/update", summary="更新菜单")
async def update_menu(
    menu_in: MenuUpdate,
):
    # 只对实际更新的字段做校验
    if menu_in.path is not None:
        # 获取当前 parent_id（如果请求没传则从数据库取）
        parent_id = menu_in.parent_id
        if parent_id is None:
            existing = await menu_controller.model.filter(id=menu_in.id).first()
            if existing:
                parent_id = existing.parent_id
        err = await _validate_menu_path(parent_id, menu_in.path)
        if err:
            return Fail(msg=err)

    if menu_in.parent_id is not None:
        err = await _validate_parent_exists(menu_in.parent_id)
        if err:
            return Fail(msg=err)
        err = await _validate_no_circular_ref(menu_in.id, menu_in.parent_id)
        if err:
            return Fail(msg=err)

    # 校验配置完整性（需结合数据库中的现有值）
    if menu_in.menu_type is not None or menu_in.component is not None or menu_in.redirect is not None or menu_in.parent_id is not None:
        existing = await menu_controller.model.filter(id=menu_in.id).first()
        if not existing:
            return Fail(msg="菜单不存在")
        menu_type = menu_in.menu_type or existing.menu_type
        component = menu_in.component if menu_in.component is not None else existing.component
        redirect = menu_in.redirect if menu_in.redirect is not None else existing.redirect
        parent_id = menu_in.parent_id if menu_in.parent_id is not None else existing.parent_id
        err = await _validate_menu_config(menu_type, component, redirect, parent_id)
        if err:
            return Fail(msg=err)

    await menu_controller.update(id=menu_in.id, obj_in=menu_in)
    return Success(msg="Updated Success")


async def _collect_child_ids(parent_id: int) -> list[int]:
    """递归收集所有子孙菜单 ID"""
    ids = []
    children = await menu_controller.model.filter(parent_id=parent_id).all()
    for child in children:
        ids.append(child.id)
        ids.extend(await _collect_child_ids(child.id))
    return ids


async def _delete_menu_cascade(menu_id: int) -> int:
    """级联删除菜单及其所有子孙菜单，返回删除总数（含自身）"""
    # 1. 收集所有子孙 ID
    child_ids = await _collect_child_ids(menu_id)
    all_ids = [menu_id] + child_ids
    all_id_set = set(all_ids)

    # 2. 清理角色-菜单关联（ManyToMany）
    #    Tortoise 的 remove() 需要传模型实例，不能直接传 ID
    from app.models.admin import Role
    roles = await Role.all()
    for role in roles:
        role_menus = await role.menus.all()
        menus_to_remove = [m for m in role_menus if m.id in all_id_set]
        if menus_to_remove:
            await role.menus.remove(*menus_to_remove)

    # 3. 从叶子节点开始删除（避免外键约束问题）
    for mid in reversed(all_ids):
        await menu_controller.model.filter(id=mid).delete()

    return len(all_ids)


@router.delete("/delete", summary="删除菜单")
async def delete_menu(
    id: int = Query(..., description="菜单id"),
    cascade: bool = Query(False, description="是否级联删除所有子菜单"),
):
    child_menu_count = await safe_count(menu_controller.model.filter(parent_id=id))
    if child_menu_count > 0 and not cascade:
        return Fail(
            msg=f"该菜单下有 {child_menu_count} 个子菜单，请先删除子菜单或使用级联删除",
            code=400,
        )
    deleted_count = await _delete_menu_cascade(id)
    return Success(msg=f"已删除 {deleted_count} 个菜单")
