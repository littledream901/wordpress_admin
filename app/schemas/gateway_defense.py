"""
网关防御功能相关的 Schema 定义
"""
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


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


class BatchBindGatewayRulesRequest(BaseModel):
    """批量部署网关防御请求"""
    site_ids: List[int] = Field(..., description='站点ID列表')
    rule_ids: List[int] = Field(default_factory=list, description='要绑定的规则ID；留空表示使用环境变量默认规则 RULE_IDS')


class GatewayRuleItem(BaseModel):
    """网关防御规则条目（来自网关 admin-api GET /v2/rules）。

    admin-api 返回字段可能随版本扩展，故放开 extra，仅约束前端实际使用的最小字段。
    """
    model_config = ConfigDict(extra='allow')

    id: int = Field(..., description='规则ID')
    name: str = Field('', description='规则名称')
    kind: Optional[str] = Field(None, description='规则类型：scoring(打分) / decision(决策)')


class GatewayRuleListResponse(BaseModel):
    """网关防御规则列表响应"""
    items: List[GatewayRuleItem] = Field(default_factory=list, description='规则列表')
    total: int = Field(0, description='规则总数')
