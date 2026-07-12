from datetime import datetime

from pydantic import BaseModel, Field


class CredentialsSchema(BaseModel):
    username: str = Field(..., description="用户名称", json_schema_extra={"example": "admin"})
    password: str = Field(..., description="密码")


class JWTOut(BaseModel):
    access_token: str
    refresh_token: str
    username: str


class JWTPayload(BaseModel):
    user_id: int
    username: str
    is_superuser: bool
    exp: datetime


class RefreshTokenPayload(BaseModel):
    user_id: int
    exp: datetime
    type: str = "refresh"


class RefreshTokenIn(BaseModel):
    refresh_token: str = Field(..., description="刷新令牌")
