from typing import Optional
from pydantic import BaseModel, Field


class GmailAccountCreate(BaseModel):
    last_name: str = ''
    first_name: str = ''
    full_name: str = ''
    zip_code: str = ''
    shipping_address_1: str = ''
    shipping_address_2: str = ''
    country: str = ''
    province_state: str = ''
    city: str = ''
    phone: str = ''
    username: str = Field(...)
    password: str = ''
    two_fa_key: str = ''
    two_fa_code: str = ''
    link_to_generate_login_code: str = ''
    recovery_email: str = ''


class GmailAccountUpdate(BaseModel):
    id: int
    last_name: Optional[str] = ''
    first_name: Optional[str] = ''
    full_name: Optional[str] = ''
    zip_code: Optional[str] = ''
    shipping_address_1: Optional[str] = ''
    shipping_address_2: Optional[str] = ''
    country: Optional[str] = ''
    province_state: Optional[str] = ''
    city: Optional[str] = ''
    phone: Optional[str] = ''
    username: Optional[str] = ''
    password: Optional[str] = ''
    two_fa_key: Optional[str] = ''
    two_fa_code: Optional[str] = ''
    link_to_generate_login_code: Optional[str] = ''
    recovery_email: Optional[str] = ''
    status: Optional[str] = ''
    assigned_site_id: Optional[int] = None
    assigned_site_domain: Optional[str] = ''


class GmailAssign(BaseModel):
    gmail_id: int
    site_id: int


class GmailHealthStatus(BaseModel):
    id: int
    status: str = Field(..., description="健康状态：正常 或 不正常")
