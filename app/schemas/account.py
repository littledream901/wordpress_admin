from typing import Optional

from pydantic import BaseModel, Field


class AccountCreate(BaseModel):
    account_type: str = Field(description="账号类型")
    username: str = Field(description="账号")
    password: str = Field(description="密码")
    env_id: int = Field(default=0, description="环境ID")
    two_fa: Optional[str] = Field(default=None, description="2FA")
    remark: Optional[str] = Field(default=None, description="备注")
    provider_id: Optional[int] = Field(default=None, description="关联Provider ID")


class AccountUpdate(BaseModel):
    id: int
    account_type: Optional[str] = Field(default=None, description="账号类型")
    username: Optional[str] = Field(default=None, description="账号")
    password: Optional[str] = Field(default=None, description="密码")
    env_id: Optional[int] = Field(default=None, description="环境ID")
    two_fa: Optional[str] = Field(default=None, description="2FA")
    remark: Optional[str] = Field(default=None, description="备注")
    provider_id: Optional[int] = Field(default=None, description="关联Provider ID")
