"""Gmail 企业邮箱注册 Schemas"""
from typing import Optional
from pydantic import BaseModel, Field


class GmailRegistrationCreate(BaseModel):
    """创建 Gmail 注册记录"""
    alias: str = Field(..., description='邮箱别名')
    domain: str = Field(..., description='站点域名')
    full_name: str = ''
    first_name: str = ''
    last_name: str = ''
    password: str = ''
    country: str = ''
    province_state: str = ''
    city: str = ''
    zip_code: str = ''
    shipping_address_1: str = ''
    shipping_address_2: str = ''
    phone: str = ''
    forward_to: str = ''
    recovery_email: str = ''
    two_fa_key: str = ''
    registration_email: str = ''
    registration_status: str = 'pending'
    env_id: str = ''
    outlook_account_id: Optional[int] = None
    remark: str = ''


class GmailRegistrationStatusUpdate(BaseModel):
    """批量更新注册状态"""
    ids: list[int]
    registration_status: str = Field(..., description='目标状态')


class GmailRegistrationActionSingle(BaseModel):
    """单条记录操作（创建转发/环境/获取号码等）"""
    registration_id: int


class GmailRegistrationGetPhone(BaseModel):
    """获取 SMS 号码"""
    registration_id: int
    country_id: Optional[int] = None
    application_id: Optional[int] = None
    max_price: Optional[int] = None


class GmailRegistrationWaitSms(BaseModel):
    """等待 SMS 验证码"""
    registration_id: int
    timeout: int = 300
    interval: int = 10


class GmailRegistrationConfirmSms(BaseModel):
    """确认 SMS 使用完成"""
    registration_id: int
    status: str = 'used'


class GmailRegistrationBatchAssignEnv(BaseModel):
    """批量分配环境到站点"""
    ids: list[int]


class GmailRegistrationBatchFetch(BaseModel):
    """批量获取待注册站点（同步未分配 Gmail 的站点）"""
    alias: str = ''


class GmailRegistrationAssignOutlook(BaseModel):
    """单条分配 Outlook 邮箱"""
    registration_id: int
    outlook_account_id: Optional[int] = Field(None, description='Outlook 账号 ID，传 null 表示解绑')


class GmailRegistrationBatchAssignOutlook(BaseModel):
    """批量自动分配 Outlook 邮箱（取未被占用的可用账号）"""
    ids: list[int]


class GmailRegistrationUpdateTwoFaKey(BaseModel):
    """回填 2FA Key"""
    registration_id: int
    two_fa_key: str = Field('', description='2FA Key，传空表示清除')
