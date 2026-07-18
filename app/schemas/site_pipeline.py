from typing import List, Optional
from pydantic import BaseModel, Field


class SiteBase(BaseModel):
    domain: str = Field(description='域名')
    server_ip: str = Field(default='', description='服务器IP')


class SiteCreate(SiteBase):
    platform: str = 'wordpress'  # wordpress / shopify
    dept_id: Optional[int] = None
    assign_to: Optional[int] = None  # 分配给指定用户（覆盖 create_by）
    # Shopify 专属
    shopify_key: Optional[str] = ''
    shopify_store_url: Optional[str] = ''
    shopify_token: Optional[str] = ''


class SiteBatchCreate(BaseModel):
    items: List[SiteCreate]


class SiteUpdate(BaseModel):
    id: int
    platform: Optional[str] = None
    server_ip: Optional[str] = ''
    status: Optional[str] = ''
    login_url: Optional[str] = ''
    woo_ck: Optional[str] = ''
    woo_cs: Optional[str] = ''
    ctx_refresh_url: Optional[str] = ''
    feed_link: Optional[str] = ''
    cloudflare_status: Optional[str] = ''
    hub_env_id: Optional[str] = ''
    hub_env_name: Optional[str] = ''
    hub_status: Optional[str] = ''
    hub_account_id: Optional[str] = ''
    hub_last_action: Optional[str] = ''
    pipeline_status: Optional[str] = ''
    pipeline_log: Optional[str] = ''
    # Shopify 专属
    shopify_key: Optional[str] = ''
    shopify_store_url: Optional[str] = ''
    shopify_token: Optional[str] = ''


class HubStudioJobCreate(BaseModel):
    site_id: int
    domain: str
    job_type: str = 'create_env'
    payload_json: str = '{}'
    provider_id: int = 0


class HubStudioJobReport(BaseModel):
    status: str
    result_json: str = '{}'
    error_message: str = ''
    worker_name: str = ''
