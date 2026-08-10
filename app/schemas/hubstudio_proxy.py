"""HubStudio 代理配置 Schema"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class HubStudioProxyConfigBase(BaseModel):
    """代理配置基础字段"""
    description: str = Field('', max_length=255, description='描述')
    
    # 核心代理参数
    proxy_type_name: str = Field('HTTP', description='代理类型: HTTP/HTTPS/SOCKS5/不使用代理')
    proxy_host: str = Field(..., description='代理服务器地址')
    proxy_port: int = Field(..., ge=1, le=65535, description='代理端口')
    proxy_account: str = Field('', description='代理账号')
    proxy_password: str = Field('', description='代理密码')
    
    # 地理位置
    reference_country_code: str = Field('US', max_length=8, description='国家代码')
    reference_city: str = Field('', description='城市')
    reference_region_code: str = Field('', description='区域/省份代码')
    
    # 动态代理配置（字段含义对齐 HubStudio /api/v1/env/proxy/update）
    as_dynamic_type: int = Field(0, ge=0, le=1, description='IP变更提醒: 0=关闭 1=开启')
    ip_get_rule_type: int = Field(1, ge=1, le=2, description='IP提取方式: 1=IP失效时提取 2=每次打开环境时提取')
    link_code: str = Field('', description='API提取链接，API提取代理时必填')
    ip_database_channel: int = Field(1, ge=0, le=3, description='代理查询渠道: 0=不指定 1=IP2Location 2=DB-IP 3=MaxMind')
    ip_protocol_type: int = Field(1, ge=0, le=3, description='IP协议选项: 0=不指定 1=速度优先 2=IPv4 3=IPv6')
    
    # 管理字段
    use_fixed_proxy: bool = Field(True, description='是否使用固定代理')
    status: str = Field('active', description='状态: active/disabled/testing')


class HubStudioProxyConfigCreate(HubStudioProxyConfigBase):
    """创建代理配置"""
    pass


class HubStudioProxyConfigUpdate(BaseModel):
    """更新代理配置（部分字段可选）"""
    proxy_id: int
    description: Optional[str] = None
    proxy_type_name: Optional[str] = None
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = Field(None, ge=1, le=65535)
    proxy_account: Optional[str] = None
    proxy_password: Optional[str] = None
    reference_country_code: Optional[str] = None
    reference_city: Optional[str] = None
    reference_region_code: Optional[str] = None
    as_dynamic_type: Optional[int] = Field(None, ge=0, le=1)
    ip_get_rule_type: Optional[int] = Field(None, ge=1, le=2)
    link_code: Optional[str] = None
    ip_database_channel: Optional[int] = None
    ip_protocol_type: Optional[int] = None
    use_fixed_proxy: Optional[bool] = None
    status: Optional[str] = None


class HubStudioProxyConfigResponse(HubStudioProxyConfigBase):
    """代理配置响应"""
    id: int
    usage_count: int
    success_count: int
    last_used_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class HubStudioProxyBatchImport(BaseModel):
    """批量导入代理配置

    解析格式：host:port:account:password（每行一条）
    示例：163.123.201.136:5921:powygrwn:mbe5zxysoih3
    """
    raw_text: str = Field(..., description='批量粘贴文本，每行一条 host:port:account:password')
    proxy_type_name: str = Field('HTTP', description='统一代理类型')
    reference_country_code: str = Field('US', max_length=8, description='统一国家代码')
    reference_city: str = Field('', description='统一城市')
    reference_region_code: str = Field('', description='统一区域/省份代码')
    as_dynamic_type: int = Field(0, ge=0, le=1, description='IP变更提醒: 0=关闭 1=开启')
    ip_get_rule_type: int = Field(1, ge=1, le=2, description='IP提取方式: 1=IP失效时提取 2=每次打开环境时提取')


class SiteBatchAssignProxy(BaseModel):
    """站点批量分配代理
    
    - use_default=True: 使用 HubStudio 默认代理
    - use_default=False: 从可用代理池中为每个站点分配一个未使用的代理
    """
    site_ids: list[int] = Field(..., min_length=1, description='站点ID列表')
    use_default: bool = Field(True, description='True=使用HubStudio默认代理，False=从代理管理中分配')


class ProxyBatchDelete(BaseModel):
    """批量删除代理（软删除）"""
    proxy_ids: list[int] = Field(..., min_length=1, description='代理ID列表')


class ProxyBatchCheck(BaseModel):
    """批量检测代理"""
    proxy_ids: list[int] = Field(..., min_length=1, description='代理ID列表')


class ProxyCheckResult(BaseModel):
    """代理检测结果"""
    proxy_id: int
    proxy_host: str
    proxy_port: int
    status: str = Field(..., description='检测状态: success/failed/timeout')
    response_time: Optional[float] = Field(None, description='响应时间(毫秒)')
    error_message: Optional[str] = Field(None, description='错误信息')
    # 地理位置信息（检测成功时返回）
    detected_ip: Optional[str] = Field(None, description='检测到的IP地址')
    detected_country: Optional[str] = Field(None, description='国家/地区')
    detected_region: Optional[str] = Field(None, description='州/省')
    detected_city: Optional[str] = Field(None, description='城市')
    detected_timezone: Optional[str] = Field(None, description='时区')




