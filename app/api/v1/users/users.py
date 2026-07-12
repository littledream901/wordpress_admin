import logging
import traceback
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, File, Query, UploadFile
from tortoise.expressions import Q

from app.controllers.dept import dept_controller
from app.controllers.user import user_controller
from app.core.ctx import CTX_USER_ID
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.users import *

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/list", summary="查看用户列表")
async def list_user(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    username: str = Query("", description="用户名称，用于搜索"),
    email: str = Query("", description="邮箱地址"),
    dept_id: int = Query(None, description="部门ID"),
):
    q = Q()
    if username:
        q &= Q(username__contains=username)
    if email:
        q &= Q(email__contains=email)
    if dept_id is not None:
        q &= Q(dept_id=dept_id)
    total, user_objs = await user_controller.list(page=page, page_size=page_size, search=q)
    data = [await obj.to_dict(m2m=True, exclude_fields=["password"]) for obj in user_objs]
    for item in data:
        dept_id = item.pop("dept_id", None)
        item["dept"] = await (await dept_controller.get(id=dept_id)).to_dict() if dept_id else {}

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


AVATAR_DIR = Path("static/avatars")
AVATAR_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


@router.post("/avatar/upload", summary="上传头像文件")
async def upload_avatar(
    file: UploadFile = File(...),
):
    try:
        user_id = CTX_USER_ID.get()
        if not user_id:
            return Fail(code=401, msg="请先登录")
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return Fail(code=400, msg=f"不支持的文件类型: {ext}")
        filename = f"{uuid.uuid4().hex}{ext}"
        filepath = AVATAR_DIR / filename
        content = await file.read()
        filepath.write_bytes(content)
        avatar_url = f"/static/avatars/{filename}"

        user_obj = await user_controller.get(id=user_id)
        user_obj.avatar = avatar_url
        await user_obj.save()
        return Success(data={"avatar": avatar_url}, msg="头像上传成功")
    except Exception as e:
        logging.error(f"Avatar upload error: {traceback.format_exc()}")
        return Fail(code=500, msg=f"上传失败: {e}")


@router.post("/avatar/url", summary="设置头像 URL")
async def set_avatar_url(
    url: str = Body(..., embed=True),
):
    try:
        user_id = CTX_USER_ID.get()
        if not user_id:
            return Fail(code=401, msg="请先登录")
        avatar_url = url.strip()
        if not avatar_url:
            return Fail(code=400, msg="URL 不能为空")

        user_obj = await user_controller.get(id=user_id)
        user_obj.avatar = avatar_url
        await user_obj.save()
        return Success(data={"avatar": avatar_url}, msg="头像设置成功")
    except Exception as e:
        logging.error(f"Avatar url error: {traceback.format_exc()}")
        return Fail(code=500, msg=f"设置失败: {e}")
