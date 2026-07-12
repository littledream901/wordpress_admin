from datetime import datetime, timedelta, timezone

import jwt

from app.schemas.login import JWTPayload, RefreshTokenPayload
from app.settings.config import settings


def create_access_token(*, data: JWTPayload):
    """创建访问令牌"""
    payload = data.model_dump().copy()
    encoded_jwt = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(*, user_id: int) -> str:
    """创建刷新令牌（有效期更长，仅包含 user_id）"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_REFRESH_TOKEN_EXPIRE_MINUTES)
    payload = RefreshTokenPayload(user_id=user_id, exp=expire, type="refresh")
    encoded_jwt = jwt.encode(payload.model_dump(), settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def decode_refresh_token(token: str) -> RefreshTokenPayload:
    """解码刷新令牌"""
    data = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    if data.get("type") != "refresh":
        raise jwt.InvalidTokenError("Not a refresh token")
    return RefreshTokenPayload(**data)
