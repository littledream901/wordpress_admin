"""HubStudio 代理配置模型

用于管理 HubStudio 浏览器环境的代理配置。
"""
from tortoise import fields
from app.models.base import BaseModel, TimestampMixin


class HubStudioProxyConfig(BaseModel, TimestampMixin):
    """HubStudio 代理配置表
    
    存储 HubStudio 浏览器环境使用的代理配置。
    每个站点可以绑定一个代理，或使用 HubStudio 默认代理。
    """
    
    # ── 基础信息 ──
    description = fields.CharField(
        max_length=255, 
        default='', 
        description='代理配置描述'
    )
    
    # ── 核心代理参数（对应 HubStudio API）──
    proxy_type_name = fields.CharField(
        max_length=32, 
        default='HTTP', 
        description='代理类型: HTTP/HTTPS/SOCKS5/不使用代理'
    )
    proxy_host = fields.CharField(
        max_length=255, 
        description='代理服务器地址',
        db_index=True
    )
    proxy_port = fields.IntField(
        description='代理端口'
    )
    proxy_account = fields.CharField(
        max_length=255, 
        default='', 
        description='代理账号/用户名'
    )
    proxy_password = fields.CharField(
        max_length=255, 
        default='', 
        description='代理密码'
    )
    
    # ── 地理位置参数 ──
    reference_country_code = fields.CharField(
        max_length=8, 
        default='US', 
        description='参考国家代码，如 US/UK/CA'
    )
    reference_city = fields.CharField(
        max_length=128, 
        default='', 
        description='参考城市，如 New York'
    )
    reference_region_code = fields.CharField(
        max_length=128, 
        default='', 
        description='参考区域/省份代码，如 CA（加州）'
    )
    
    # ── 动态代理配置 ──
    as_dynamic_type = fields.IntField(
        default=0, 
        description='IP变更提醒: 0=关闭提醒(默认) 1=开启提醒'
    )
    ip_get_rule_type = fields.IntField(
        default=1, 
        description='IP提取方式: 1=IP失效时提取新IP 2=每次打开环境时提取新IP（API提取代理时必填）'
    )
    link_code = fields.CharField(
        max_length=255, 
        default='', 
        description='API提取链接（API提取代理时必填）'
    )
    ip_database_channel = fields.IntField(
        default=1, 
        description='代理查询渠道: 1=IP2Location 2=DB-IP 3=MaxMind（0表示不指定）'
    )
    ip_protocol_type = fields.IntField(
        default=1, 
        description='IP协议选项: 1=速度优先 2=IPv4 3=IPv6（0表示不指定）'
    )
    
    # ── 开关控制 ──
    use_fixed_proxy = fields.BooleanField(
        default=True, 
        description='是否使用固定代理配置'
    )
    
    # ── 管理字段 ──
    status = fields.CharField(
        max_length=32, 
        default='active', 
        description='状态: active=启用 disabled=禁用 testing=测试中', 
        db_index=True
    )
    
    # ── 统计监控字段 ──
    usage_count = fields.IntField(
        default=0, 
        description='累计使用次数'
    )
    success_count = fields.IntField(
        default=0, 
        description='成功次数'
    )
    last_used_at = fields.DatetimeField(
        null=True, 
        description='最后使用时间'
    )
    is_deleted = fields.BooleanField(
        default=False, 
        description='软删除标记', 
        db_index=True
    )
    deleted_at = fields.DatetimeField(
        null=True, 
        description='删除时间'
    )
    
    class Meta:
        table = 'hubstudio_proxy_config'
        ordering = ['-id']
        indexes = [
            ('proxy_host', 'proxy_port'),
        ]
    
    def to_api_params(self) -> dict:
        """转换为 HubStudio API 所需的代理参数格式
        
        注意：
        - containerCode 由调用方单独传递，不包含在此方法返回值中
        - ipDatabaseChannel 和 ipProtocolType 为 0 时表示不指定，不传递给 API
        - linkCode 和 ipGetRuleType 仅在 API 提取代理类型时需要
        """
        params = {
            "proxyTypeName": self.proxy_type_name,
            "asDynamicType": self.as_dynamic_type,
            "proxyHost": self.proxy_host,
            "proxyPort": self.proxy_port,
            "proxyAccount": self.proxy_account or "",
            "proxyPassword": self.proxy_password or "",
            "referenceCountryCode": self.reference_country_code,
            "referenceCity": self.reference_city or "",
            "referenceRegionCode": self.reference_region_code or "",
        }
        
        # 可选字段：仅在有值时传递
        if self.ip_get_rule_type and self.ip_get_rule_type > 0:
            params["ipGetRuleType"] = self.ip_get_rule_type
        
        if self.link_code:
            params["linkCode"] = self.link_code
        
        if self.ip_database_channel and self.ip_database_channel > 0:
            params["ipDatabaseChannel"] = self.ip_database_channel
        
        if self.ip_protocol_type and self.ip_protocol_type > 0:
            params["ipProtocolType"] = self.ip_protocol_type
        
        return params

