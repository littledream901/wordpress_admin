"""ADS 环境管理 - Pydantic 校验"""

from typing import Optional, List
from pydantic import BaseModel, Field


class AdsEnvCreate(BaseModel):
    ads_env_id: str = Field(..., description='ADS环境ID')
    site_ids: Optional[List[int]] = Field(default=None, description='关联站点ID列表')
    domain: str = Field(default='', description='域名')
    status: str = Field(default='正常', description='状态')
    remark: str = Field(default='', description='备注')


class AdsEnvUpdate(BaseModel):
    id: int
    ads_env_id: Optional[str] = None
    site_ids: Optional[List[int]] = None
    domain: Optional[str] = None
    status: Optional[str] = None
    remark: Optional[str] = None
