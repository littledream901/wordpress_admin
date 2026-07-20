import asyncio
import logging
import time
import traceback

from fastapi import APIRouter, Body, File, Query, UploadFile
from fastapi.exceptions import HTTPException
from tortoise.expressions import Q

from app.controllers.dept import dept_controller
from app.controllers.user import user_controller
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.users import UserCreate, UserUpdate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["User"])


@router.get("/list", summary="查看用户列表")
async def list_user(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    username: str = Query("", description="用户名称，用于搜索"),
    email: str = Query("", description="邮箱地址"),
    dept_id: int = Query(None, description="部门ID"),
):
    t0 = time.perf_counter()
    q = Q()
    if username:
        q &= Q(username__contains=username)
    if email:
        q &= Q(email__contains=email)
    if dept_id is not None:
        q &= Q(dept_id=dept_id)
    # 使用 prefetch_related 预加载角色，避免 to_dict(m2m=True) 的 N+1 查询
    total, user_objs = await user_controller.list(
        page=page, page_size=page_size, search=q, prefetch_related=['roles'],
    )
    t1 = time.perf_counter()
    data = await asyncio.gather(*[obj.to_dict(m2m=True, exclude_fields=["password"]) for obj in user_objs])
    data = list(data)

    # 批量查询部门（避免 N+1）
    dept_ids = {item["dept_id"] for item in data if item.get("dept_id")}
    dept_map = {}
    if dept_ids:
        depts = await dept_controller.model.filter(id__in=list(dept_ids)).all()
        dept_dicts = await asyncio.gather(*[d.to_dict() for d in depts])
        dept_map = {d.id: dd for d, dd in zip(depts, dept_dicts)}

    for item in data:
        dept_id = item.pop("dept_id", None)
        item["dept"] = dept_map.get(dept_id) or {}

    t2 = time.perf_counter()
    total_ms = int((t2 - t0) * 1000)
    logger.info(
        "[user/list] 耗时: %dms | DB查询: %dms | 序列化+部门: %dms | total=%d page_size=%d",
        total_ms, int((t1 - t0) * 1000), int((t2 - t1) * 1000), total, page_size,
    )
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/get", summary="查看用户")
async def get_user(
    user_id: int = Query(..., description="用户ID"),
):
    user_obj = await user_controller.get(id=user_id)
    user_dict = await user_obj.to_dict(exclude_fields=["password"])
    return Success(data=user_dict)


@router.post("/create", summary="创建用户")
async def create_user(
    user_in: UserCreate,
):
    user = await user_controller.get_by_email(user_in.email)
    if user:
        return Fail(code=400, msg="The user with this email already exists in the system.")
    new_user = await user_controller.create_user(obj_in=user_in)
    await user_controller.update_roles(new_user, user_in.role_ids)
    return Success(msg="Created Successfully")


@router.post("/update", summary="更新用户")
async def update_user(
    user_in: UserUpdate,
):
    user = await user_controller.update(id=user_in.id, obj_in=user_in)
    await user_controller.update_roles(user, user_in.role_ids)
    return Success(msg="Updated Successfully")


@router.delete("/delete", summary="删除用户")
async def delete_user(
    user_id: int = Query(..., description="用户ID"),
):
    await user_controller.remove(id=user_id)
    return Success(msg="Deleted Successfully")


@router.post("/reset_password", summary="重置密码")
async def reset_password(user_id: int = Body(..., description="用户ID", embed=True)):
    await user_controller.reset_password(user_id)
    return Success(msg="密码已重置")


@router.post("/avatar/upload", summary="上传头像文件")
async def upload_avatar(
    file: UploadFile = File(...),
):
    try:
        result = await user_controller.upload_avatar(file)
        return Success(data=result, msg="头像上传成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Avatar upload error: {traceback.format_exc()}")
        return Fail(code=500, msg=f"上传失败: {e}")


@router.post("/avatar/url", summary="设置头像 URL")
async def set_avatar_url(
    url: str = Body(..., embed=True),
):
    try:
        result = await user_controller.set_avatar_url(url)
        return Success(data=result, msg="头像设置成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Avatar url error: {traceback.format_exc()}")
        return Fail(code=500, msg=f"设置失败: {e}")
