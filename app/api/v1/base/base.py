from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import jwt as pyjwt
from fastapi import APIRouter, HTTPException

from app.controllers.user import user_controller
from app.core.ctx import CTX_USER_ID
from app.core.dependency import DependAuth
from app.log import logger
from app.models.admin import Api, Menu, Role, User
from app.schemas.base import Fail, Success
from app.schemas.login import CredentialsSchema, JWTOut, JWTPayload, RefreshTokenIn
from app.schemas.users import UpdatePassword
from app.settings import settings
from app.utils.jwt_utils import create_access_token, create_refresh_token, decode_refresh_token
from app.utils.password import get_password_hash, verify_password

router = APIRouter()


def _build_userinfo_dict(user: User) -> Dict[str, Any]:
    """稳定构造用户信息，避免依赖 ORM to_dict 在脏对象场景下抛异常。"""
    last_login = getattr(user, "last_login", None)
    return {
        "id": getattr(user, "id", None),
        "username": getattr(user, "username", "") or "",
        "alias": getattr(user, "alias", "") or "",
        "email": getattr(user, "email", "") or "",
        "phone": getattr(user, "phone", "") or "",
        "avatar": getattr(user, "avatar", "") or "/static/default_avatar.svg",
        "is_active": bool(getattr(user, "is_active", True)),
        "is_superuser": bool(getattr(user, "is_superuser", False)),
        "last_login": last_login.isoformat() if last_login else None,
        "dept_id": getattr(user, "dept_id", None),
    }


def _safe_menu_attr(menu: Any, attr: str, default: Any = None, *, user_id: int | None = None) -> Any:
    """安全读取菜单字段。"""
    value = getattr(menu, attr, default)
    if value is None and attr in ("id", "parent_id", "path", "name"):
        logger.warning(
            "[usermenu] Menu 对象字段缺失 attr=%s menu_id=%s menu_type=%s user_id=%s",
            attr,
            getattr(menu, "id", "?"),
            type(menu).__name__,
            user_id,
        )
    return value


def _menu_to_dict(menu: Any, *, user_id: int | None = None) -> Dict[str, Any] | None:
    """将菜单对象安全转为字典；关键字段缺失时返回 None。"""
    menu_id = _safe_menu_attr(menu, "id", None, user_id=user_id)
    path = _safe_menu_attr(menu, "path", None, user_id=user_id)
    name = _safe_menu_attr(menu, "name", "", user_id=user_id)

    if menu_id is None or path is None:
        logger.warning(
            "[usermenu] 跳过异常菜单对象 menu_id=%s path=%s menu_type=%s user_id=%s",
            menu_id,
            path,
            type(menu).__name__,
            user_id,
        )
        return None

    return {
        "id": menu_id,
        "name": name or "",
        "path": path or "",
        "parent_id": _safe_menu_attr(menu, "parent_id", 0, user_id=user_id) or 0,
        "icon": _safe_menu_attr(menu, "icon", None, user_id=user_id),
        "menu_type": _safe_menu_attr(menu, "menu_type", None, user_id=user_id),
        "order": _safe_menu_attr(menu, "order", 0, user_id=user_id) or 0,
        "is_hidden": bool(_safe_menu_attr(menu, "is_hidden", False, user_id=user_id)),
        "component": _safe_menu_attr(menu, "component", "", user_id=user_id) or "",
        "keepalive": bool(_safe_menu_attr(menu, "keepalive", True, user_id=user_id)),
        "redirect": _safe_menu_attr(menu, "redirect", None, user_id=user_id),
        "remark": _safe_menu_attr(menu, "remark", None, user_id=user_id),
        "children": [],
    }


def _build_menu_tree(menu_rows: List[Dict[str, Any]], *, user_id: int | None = None) -> List[Dict[str, Any]]:
    """将扁平菜单构造成树；父节点缺失时降级为根菜单。"""
    by_id: Dict[int, Dict[str, Any]] = {}
    roots: List[Dict[str, Any]] = []

    for row in menu_rows:
        by_id[row["id"]] = row

    for row in menu_rows:
        parent_id = row.get("parent_id", 0) or 0
        if parent_id == 0:
            roots.append(row)
            continue

        parent = by_id.get(parent_id)
        if not parent:
            logger.warning(
                "[usermenu] 菜单父节点不存在，降级为根节点 menu_id=%s parent_id=%s path=%s user_id=%s",
                row.get("id"),
                parent_id,
                row.get("path"),
                user_id,
            )
            roots.append(row)
            continue

        parent.setdefault("children", []).append(row)

    def _sort_tree(nodes: List[Dict[str, Any]]) -> None:
        nodes.sort(key=lambda x: (x.get("order", 0), x.get("id", 0)))
        for node in nodes:
            children = node.get("children") or []
            if children:
                _sort_tree(children)

    _sort_tree(roots)
    return roots


@router.get("/health", summary="健康检查")
async def health_check():
    return {"status": "ok", "version": settings.VERSION}


@router.post("/access_token", summary="获取token")
async def login_access_token(credentials: CredentialsSchema):
    user: User = await user_controller.authenticate(credentials)
    await user_controller.update_last_login(user.id)

    user_id = getattr(user, "id", None)
    username = getattr(user, "username", "") or ""
    if not user_id:
        logger.warning("[access_token] 用户对象异常，缺少 id user_type=%s", type(user).__name__)
        return Fail(code=401, msg="用户不存在")

    access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = datetime.now(timezone.utc) + access_token_expires

    data = JWTOut(
        access_token=create_access_token(
            data=JWTPayload(
                user_id=user_id,
                username=username,
                is_superuser=bool(getattr(user, "is_superuser", False)),
                exp=expire,
            )
        ),
        refresh_token=create_refresh_token(user_id=user_id),
        username=username,
    )
    return Success(data=data.model_dump())


@router.post("/refresh_token", summary="刷新token（无需认证）")
async def refresh_access_token(payload: RefreshTokenIn):
    try:
        refresh_data = decode_refresh_token(payload.refresh_token)
    except pyjwt.ExpiredSignatureError:
        return Fail(code=401, msg="刷新令牌已过期，请重新登录")
    except (pyjwt.DecodeError, pyjwt.InvalidTokenError):
        return Fail(code=401, msg="无效的刷新令牌")

    user = await User.filter(id=refresh_data.user_id).first()
    if not user:
        logger.warning("[refresh_token] 用户不存在 user_id=%s", refresh_data.user_id)
        return Fail(code=401, msg="用户不存在")
    if not getattr(user, "is_active", True):
        logger.warning("[refresh_token] 用户已禁用 user_id=%s", refresh_data.user_id)
        return Fail(code=401, msg="用户已禁用")

    user_id = getattr(user, "id", None)
    username = getattr(user, "username", "") or ""
    if not user_id:
        logger.warning("[refresh_token] 用户对象异常，缺少 id user_type=%s", type(user).__name__)
        return Fail(code=401, msg="用户不存在")

    access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = datetime.now(timezone.utc) + access_token_expires

    data = JWTOut(
        access_token=create_access_token(
            data=JWTPayload(
                user_id=user_id,
                username=username,
                is_superuser=bool(getattr(user, "is_superuser", False)),
                exp=expire,
            )
        ),
        refresh_token=create_refresh_token(user_id=user_id),
        username=username,
    )
    return Success(data=data.model_dump())


@router.get("/userinfo", summary="查看用户信息", dependencies=[DependAuth])
async def get_userinfo(current_user: User = DependAuth):
    """返回当前登录用户信息。认证状态已由 DependAuth 保障。"""
    data = _build_userinfo_dict(current_user)
    if not data.get("id"):
        logger.warning("[userinfo] 用户对象异常，缺少 id")
        raise HTTPException(status_code=401, detail="登录已失效")
    return Success(data=data)


@router.get("/usermenu", summary="查看用户菜单", dependencies=[DependAuth])
async def get_user_menu(current_user: User = DependAuth):
    """返回当前用户可见菜单树。单条脏菜单跳过，不阻断整体返回。"""
    user_id = getattr(current_user, "id", None)

    if getattr(current_user, "is_superuser", False):
        try:
            menus = await Menu.all()
        except Exception:
            logger.exception("[usermenu] 超级管理员读取菜单失败 user_id=%s", user_id)
            raise HTTPException(status_code=500, detail="读取菜单失败")
    else:
        try:
            roles: List[Role] = await current_user.roles
        except Exception:
            logger.exception("[usermenu] 获取用户角色失败 user_id=%s", user_id)
            roles = []

        if not roles:
            raise HTTPException(status_code=403, detail="当前用户未绑定角色")

        all_menu_lists: List[List[Menu]] = []
        for role in roles:
            try:
                role_menus = await role.menus
                all_menu_lists.append(role_menus)
            except Exception:
                logger.warning(
                    "[usermenu] 获取角色菜单失败 role_id=%s user_id=%s",
                    getattr(role, "id", None),
                    user_id,
                )
                continue

        menus = list({getattr(m, "id", id(m)): m for m in sum(all_menu_lists, [])}.values())

    safe_rows: List[Dict[str, Any]] = []
    for menu in menus:
        row = _menu_to_dict(menu, user_id=user_id)
        if row:
            safe_rows.append(row)

    return Success(data=_build_menu_tree(safe_rows, user_id=user_id))


@router.get("/userapi", summary="查看用户API", dependencies=[DependAuth])
async def get_user_api(current_user: User = DependAuth):
    """返回当前用户拥有的接口权限点。单条脏 API 跳过，不阻断整体返回。"""
    user_id = getattr(current_user, "id", None)

    if getattr(current_user, "is_superuser", False):
        api_objs = await Api.all()
        return Success(
            data=[
                {
                    "id": getattr(api, "id", None),
                    "path": getattr(api, "path", ""),
                    "method": getattr(api, "method", ""),
                    "summary": getattr(api, "summary", "") or "",
                    "tags": getattr(api, "tags", "") or "",
                    "is_button": bool(getattr(api, "is_button", False)),
                }
                for api in api_objs
                if getattr(api, "path", None) and getattr(api, "method", None)
            ]
        )

    try:
        roles: List[Role] = await current_user.roles
    except Exception:
        logger.exception("[userapi] 获取用户角色失败 user_id=%s", user_id)
        roles = []

    if not roles:
        raise HTTPException(status_code=403, detail="当前用户未绑定角色")

    api_seen: set[tuple] = set()
    result: List[Dict[str, Any]] = []

    for role in roles:
        try:
            role_apis = await role.apis
        except Exception:
            logger.warning(
                "[userapi] 获取角色 API 失败 role_id=%s user_id=%s",
                getattr(role, "id", None),
                user_id,
            )
            continue

        for api in role_apis:
            path = getattr(api, "path", None)
            method = getattr(api, "method", None)
            if not path or not method:
                logger.warning(
                    "[userapi] Api 对象字段缺失 path=%s method=%s api_id=%s role_id=%s user_id=%s",
                    path,
                    method,
                    getattr(api, "id", None),
                    getattr(role, "id", None),
                    user_id,
                )
                continue

            key = (method, path)
            if key in api_seen:
                continue

            api_seen.add(key)
            result.append(
                {
                    "id": getattr(api, "id", None),
                    "path": path,
                    "method": method,
                    "summary": getattr(api, "summary", "") or "",
                    "tags": getattr(api, "tags", "") or "",
                    "is_button": bool(getattr(api, "is_button", False)),
                }
            )

    return Success(data=result)


@router.post("/update_password", summary="修改密码", dependencies=[DependAuth])
async def update_user_password(req_in: UpdatePassword):
    user_id = CTX_USER_ID.get()
    user = await User.filter(id=user_id).first()
    if not user:
        return Fail(code=401, msg="用户不存在或登录已失效")

    verified = verify_password(req_in.old_password, getattr(user, "password", ""))
    if not verified:
        return Fail(msg="旧密码验证错误！")

    user.password = get_password_hash(req_in.new_password)
    await user.save()
    return Success(msg="修改成功")
