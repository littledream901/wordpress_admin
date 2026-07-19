from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from fastapi import APIRouter, HTTPException

from app.controllers.user import user_controller
from app.core.ctx import CTX_USER_ID
from app.core.dependency import DependAuth
from app.log import logger
from app.models.admin import Api, Menu, Role, User
from app.schemas.base import Fail, Success
from app.schemas.login import *
from app.schemas.users import UpdatePassword
from app.settings import settings
from app.utils.jwt_utils import create_access_token, create_refresh_token, decode_refresh_token
from app.utils.password import get_password_hash, verify_password
from tortoise.exceptions import DoesNotExist, MultipleObjectsReturned

router = APIRouter()


@router.get("/health", summary="健康检查")
async def health_check():
    return {"status": "ok", "version": settings.VERSION}


@router.post("/access_token", summary="获取token")
async def login_access_token(credentials: CredentialsSchema):
    user: User = await user_controller.authenticate(credentials)
    await user_controller.update_last_login(user.id)
    access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = datetime.now(timezone.utc) + access_token_expires

    data = JWTOut(
        access_token=create_access_token(
            data=JWTPayload(
                user_id=user.id,
                username=user.username,
                is_superuser=user.is_superuser,
                exp=expire,
            )
        ),
        refresh_token=create_refresh_token(user_id=user.id),
        username=user.username,
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

    user = await user_controller.get(id=refresh_data.user_id)
    if not user:
        return Fail(code=401, msg="用户不存在")

    access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = datetime.now(timezone.utc) + access_token_expires

    data = JWTOut(
        access_token=create_access_token(
            data=JWTPayload(
                user_id=user.id,
                username=user.username,
                is_superuser=user.is_superuser,
                exp=expire,
            )
        ),
        refresh_token=create_refresh_token(user_id=user.id),
        username=user.username,
    )
    return Success(data=data.model_dump())


@router.get("/userinfo", summary="查看用户信息", dependencies=[DependAuth])
async def get_userinfo():
    user_id = CTX_USER_ID.get()
    try:
        user_obj = await user_controller.get(id=user_id)
    except DoesNotExist:
        logger.warning(f"[userinfo] 用户不存在 user_id={user_id}")
        raise HTTPException(status_code=401, detail="用户不存在或已失效，请重新登录")
    except MultipleObjectsReturned:
        logger.error(f"[userinfo] 用户数据异常(重复记录) user_id={user_id}")
        raise HTTPException(status_code=500, detail="用户数据异常，请联系管理员")
    except Exception as e:
        logger.error(f"[userinfo] 获取用户信息异常 user_id={user_id}: {e}")
        raise HTTPException(status_code=500, detail="服务异常，请稍后重试")

    if not user_obj:
        raise HTTPException(status_code=401, detail="用户不存在或已失效，请重新登录")
    data = await user_obj.to_dict(exclude_fields=["password"])
    if not data.get("avatar"):
        data["avatar"] = "/static/default_avatar.svg"
    return Success(data=data)


@router.get("/usermenu", summary="查看用户菜单", dependencies=[DependAuth])
async def get_user_menu():
    user_id = CTX_USER_ID.get()
    user_obj = await User.filter(id=user_id).first()
    if not user_obj:
        raise HTTPException(status_code=401, detail="用户不存在或已失效，请重新登录")
    menus: list[Menu] = []
    if user_obj.is_superuser:
        menus = await Menu.all()
    else:
        role_objs: list[Role] = await user_obj.roles
        for role_obj in role_objs:
            menu = await role_obj.menus
            menus.extend(menu)
        menus = list(set(menus))
    parent_menus: list[Menu] = []
    for menu in menus:
        if menu.parent_id == 0:
            parent_menus.append(menu)
    res = []
    for parent_menu in parent_menus:
        parent_menu_dict = await parent_menu.to_dict()
        parent_menu_dict["children"] = []
        for menu in menus:
            if menu.parent_id == parent_menu.id:
                parent_menu_dict["children"].append(await menu.to_dict())
        res.append(parent_menu_dict)
    return Success(data=res)


@router.get("/userapi", summary="查看用户API", dependencies=[DependAuth])
async def get_user_api():
    user_id = CTX_USER_ID.get()
    user_obj = await User.filter(id=user_id).first()
    if user_obj.is_superuser:
        api_objs: list[Api] = await Api.all()
        apis = [api.method.lower() + api.path for api in api_objs]
        return Success(data=apis)
    role_objs: list[Role] = await user_obj.roles
    apis = []
    for role_obj in role_objs:
        api_objs: list[Api] = await role_obj.apis
        apis.extend([api.method.lower() + api.path for api in api_objs])
    apis = list(set(apis))
    return Success(data=apis)


@router.post("/update_password", summary="修改密码", dependencies=[DependAuth])
async def update_user_password(req_in: UpdatePassword):
    user_id = CTX_USER_ID.get()
    user = await user_controller.get(user_id)
    verified = verify_password(req_in.old_password, user.password)
    if not verified:
        return Fail(msg="旧密码验证错误！")
    user.password = get_password_hash(req_in.new_password)
    await user.save()
    return Success(msg="修改成功")
