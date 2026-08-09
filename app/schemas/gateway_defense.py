"""
网关防御功能相关的 Schema 定义
"""
from typing import Optional, Dict
from pydantic import BaseModel, Field


class GatewayDefenseCreate(BaseModel):
    """网关防御部署请求"""
    gateway_url: str = Field(..., description='网关地址')
    gateway_site_id: Optional[str] = Field(
        None,
        description='网关侧站点标识（必须外部提供，对应 $fangyu_site_id；留空则复用站点已保存的值）',
    )
    site_key: Optional[str] = Field(None, description='站点密钥（必须外部提供；留空则复用站点已保存的密钥）')
    site_secret: Optional[str] = Field(None, description='站点签名密钥（必须外部提供；留空则复用站点已保存的密钥）')
    fail_mode: str = Field('open', description='失败模式: open / closed')
    sdk_inject: bool = Field(True, description='是否注入 SDK')


class GatewayDefenseBatchDeploy(BaseModel):
    """批量部署网关防御请求"""
    site_ids: list[int] = Field(..., description='站点ID列表')
    gateway_url: str = Field(..., description='网关地址')
    fail_mode: str = Field('open', description='失败模式')
    sdk_inject: bool = Field(True, description='是否注入 SDK')
    # 批量部署时每个站点的网关标识与密钥必须逐站提供
    credentials_map: Optional[Dict[int, Dict[str, str]]] = Field(
        None,
        description='站点ID到凭证的映射 {site_id: {gateway_site_id, site_key, site_secret}}',
    )


class GatewayDefenseUpdate(BaseModel):
    """更新网关防御配置"""
    gateway_url: Optional[str] = None
    gateway_site_id: Optional[str] = None
    site_key: Optional[str] = None
    site_secret: Optional[str] = None
    fail_mode: Optional[str] = None
    sdk_inject: Optional[bool] = None


class GatewayDefenseResponse(BaseModel):
    """网关防御响应"""
    site_id: int
    domain: str
    gateway_site_id: str
    gateway_site_key: str
    gateway_site_secret: str
    gateway_defense_status: str
    gateway_defense_type: str
    gateway_deployed_at: Optional[str] = None
    gateway_config: dict = {}
