from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, Request

from app.core.ctx import CTX_USER_ID
from app.log import logger
from app.models.admin import Role, User
from app.settings import settings


def _parse_bearer_token(authorization: str) -> str:
    """从 Authorization: Bearer <token> 中提取 token"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证信息")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="认证格式错误，应为 Bearer <token>")
    return token


class AuthControl:
    @classmethod
    async def is_authed(
        cls,
        authorization: str = Header(
            None,
            alias="Authorization",
            description="Bearer Token 认证（格式：Bearer <token>）",
        ),
    ) -> Optional["User"]:
        if not authorization:
            raise HTTPException(status_code=401, detail="未提供认证信息")
        try:
            token = _parse_bearer_token(authorization)
            decode_data = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            user_id = decode_data.get("user_id")
            user = await User.filter(id=user_id).first()
            if not user:
                raise HTTPException(status_code=401, detail="用户不存在或已被删除")
            if not getattr(user, "is_active", True):
                raise HTTPException(status_code=401, detail="用户已被禁用")
            CTX_USER_ID.set(int(user_id))
            return user
        except jwt.DecodeError:
            raise HTTPException(status_code=401, detail="无效的Token")
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="登录已过期")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"{repr(e)}")


class PermissionControl:
    # 公共只读 API：跨模块通用，所有已认证用户可访问，不参与权限校验
    PUBLIC_API: set[tuple[str, str]] = {
        ("GET", "/api/v1/dept/list"),
        ("GET", "/api/v1/dept/get"),
        ("GET", "/api/v1/user/list"),
        ("GET", "/api/v1/user/get"),
        ("GET", "/api/v1/menu/list"),
        ("GET", "/api/v1/menu/get"),
        ("GET", "/api/v1/role/list"),
        ("GET", "/api/v1/role/get"),
        ("GET", "/api/v1/role/authorized"),
        # ── 个人设置（所有用户可管理自己的信息）──
        ("POST", "/api/v1/user/update"),
        ("POST", "/api/v1/user/avatar/upload"),
        ("POST", "/api/v1/user/avatar/url"),
    }

    @classmethod
    async def has_permission(cls, request: Request, current_user: User = Depends(AuthControl.is_authed)) -> None:
        if getattr(current_user, "is_superuser", False):
            return
        method = request.method
        # 使用路由模式路径（如 /api/v1/user/{id}），拼接 root_path 补偿 Mount 前缀
        route = request.scope.get("route")
        root_path = request.scope.get("root_path", "")
        path = (root_path + route.path) if route else request.url.path

        # 公共只读 API 直接放行
        if (method, path) in cls.PUBLIC_API:
            return
        roles: list[Role] = await current_user.roles
        if not roles:
            logger.warning(
                "[Perm] 拒绝: user={}(id={}) 无角色绑定 | method={} path={}",
                current_user.username, current_user.id, method, path,
            )
            raise HTTPException(status_code=403, detail="The user is not bound to a role")
        apis = [await role.apis for role in roles]
        permission_apis = list(set(
            (getattr(api, "method", ""), getattr(api, "path", ""))
            for api in sum(apis, [])
            if getattr(api, "method", None) and getattr(api, "path", None)
        ))
        if (method, path) not in permission_apis:
            role_codes = [getattr(r, 'code', '?') for r in roles]
            logger.warning(
                "[Perm] 拒绝: user={}(id={}) roles={} | 请求 {} {} | 拥有 {} 条权限",
                current_user.username, current_user.id, role_codes, method, path, len(permission_apis),
            )
            raise HTTPException(status_code=403, detail=f"Permission denied method:{method} path:{path}")


def decode_token_lightweight(token: str) -> dict | None:
    """轻量级 JWT 解码（不查数据库），供中间件使用。返回 payload 或 None"""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except Exception:
        return None


DependAuth = Depends(AuthControl.is_authed)
DependPermission = Depends(PermissionControl.has_permission)
