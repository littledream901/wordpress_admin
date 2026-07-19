import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import UploadFile
from fastapi.exceptions import HTTPException

from app.core.crud import CRUDBase
from app.core.ctx import CTX_USER_ID
from app.models.admin import User
from app.settings.config import settings
from app.schemas.login import CredentialsSchema
from app.schemas.users import UserCreate, UserUpdate
from app.utils.password import get_password_hash, verify_password

from .role import role_controller

_log = logging.getLogger(__name__)

AVATAR_DIR = Path("static/avatars")
AVATAR_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


class UserController(CRUDBase[User, UserCreate, UserUpdate]):
    def __init__(self):
        super().__init__(model=User)

    async def get_by_email(self, email: str) -> Optional[User]:
        return await self.model.filter(email=email).first()

    async def get_by_username(self, username: str) -> Optional[User]:
        return await self.model.filter(username=username).first()

    async def create_user(self, obj_in: UserCreate) -> User:
        obj_in.password = get_password_hash(password=obj_in.password)
        obj = await self.create(obj_in)
        return obj

    async def update_last_login(self, id: int) -> None:
        user = await self.get(id=id)
        user.last_login = datetime.now()
        await user.save()

    async def authenticate(self, credentials: CredentialsSchema) -> Optional["User"]:
        user = await self.model.filter(username=credentials.username).first()
        if not user:
            raise HTTPException(status_code=400, detail="无效的用户名")
        verified = verify_password(credentials.password, user.password)
        if not verified:
            raise HTTPException(status_code=400, detail="密码错误!")
        if not user.is_active:
            raise HTTPException(status_code=400, detail="用户已被禁用")
        return user

    async def update_roles(self, user: User, role_ids: List[int]) -> None:
        await user.roles.clear()
        for role_id in role_ids:
            role_obj = await role_controller.get(id=role_id)
            await user.roles.add(role_obj)

    async def reset_password(self, user_id: int):
        user_obj = await self.get(id=user_id)
        if user_obj.is_superuser:
            raise HTTPException(status_code=403, detail="不允许重置超级管理员密码")
        user_obj.password = get_password_hash(password=settings.DEFAULT_PASSWORD)
        await user_obj.save()

    async def upload_avatar(self, file: UploadFile) -> dict:
        """处理头像文件上传，保存到磁盘并更新用户记录。返回 {"avatar": url}"""
        user_id = CTX_USER_ID.get()
        if not user_id:
            raise HTTPException(status_code=401, detail="请先登录")
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")
        filename = f"{uuid.uuid4().hex}{ext}"
        filepath = AVATAR_DIR / filename
        content = await file.read()
        filepath.write_bytes(content)
        avatar_url = f"/static/avatars/{filename}"

        user_obj = await self.get(id=user_id)
        user_obj.avatar = avatar_url
        await user_obj.save()
        return {"avatar": avatar_url}

    async def set_avatar_url(self, url: str) -> dict:
        """设置用户头像 URL。返回 {"avatar": url}"""
        user_id = CTX_USER_ID.get()
        if not user_id:
            raise HTTPException(status_code=401, detail="请先登录")
        avatar_url = url.strip()
        if not avatar_url:
            raise HTTPException(status_code=400, detail="URL 不能为空")

        user_obj = await self.get(id=user_id)
        user_obj.avatar = avatar_url
        await user_obj.save()
        return {"avatar": avatar_url}


user_controller = UserController()
