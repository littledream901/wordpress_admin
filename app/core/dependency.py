from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, Request

from app.core.ctx import CTX_USER_ID
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
    @classmethod
    async def has_permission(cls, request: Request, current_user: User = Depends(AuthControl.is_authed)) -> None:
        if getattr(current_user, "is_superuser", False):
            return
        method = request.method
        # 使用路由模式路径（如 /api/v1/user/{id}），拼接 root_path 补偿 Mount 前缀
        route = request.scope.get("route")
        root_path = request.scope.get("root_path", "")
        path = (root_path + route.path) if route else request.url.path
        roles: list[Role] = await current_user.roles
        if not roles:
            raise HTTPException(status_code=403, detail="The user is not bound to a role")
        apis = [await role.apis for role in roles]
        permission_apis = list(set((api.method, api.path) for api in sum(apis, [])))
        if (method, path) not in permission_apis:
            raise HTTPException(status_code=403, detail=f"Permission denied method:{method} path:{path}")


def decode_token_lightweight(token: str) -> dict | None:
    """轻量级 JWT 解码（不查数据库），供中间件使用。返回 payload 或 None"""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except Exception:
        return None


DependAuth = Depends(AuthControl.is_authed)
DependPermission = Depends(PermissionControl.has_permission)
