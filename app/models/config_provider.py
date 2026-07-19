"""配置提供者模型 — 管理多账号、多环境、多节点的配置实例"""
from tortoise import fields

from .base import BaseModel, SoftDeleteMixin, TimestampMixin


class ConfigProvider(BaseModel, SoftDeleteMixin, TimestampMixin):
    """配置提供者（一个实例 = 一个账号/节点/环境）

    例如：
    - "Cloudflare 主账号"
    - "Dynadot 账号1"
    - "1Panel 华东节点"
    """

    PROVIDER_TYPES = [
        ("cloudflare", "Cloudflare"),
        ("dynadot", "Dynadot"),
        ("onepanel", "1Panel"),
        ("hubstudio", "HubStudio"),
        ("shopify", "Shopify"),
        ("woo", "WooCommerce"),
        ("pipeline", "流水线"),
    ]

    STATUS_CHOICES = [
        ("active", "启用"),
        ("disabled", "禁用"),
        ("expired", "已过期"),
        ("error", "异常"),
    ]

    provider_type = fields.CharField(max_length=64, choices=PROVIDER_TYPES, description="提供者类型", db_index=True)
    provider_name = fields.CharField(max_length=128, description="名称")
    description = fields.CharField(max_length=500, default="", description="描述")
    remark = fields.CharField(max_length=500, default="", description="备注")
    status = fields.CharField(max_length=32, default="active", choices=STATUS_CHOICES, description="状态")
    is_default = fields.BooleanField(default=False, description="是否默认")
    priority = fields.IntField(default=0, description="优先级（越大越高）")
    tags = fields.CharField(max_length=500, default="", description="标签(逗号分隔)")

    class Meta:
        table = "config_provider"
        ordering = ["-priority", "id"]
        unique_together = [("provider_type", "provider_name")]

    @classmethod
    async def get_default(cls, provider_type: str) -> "ConfigProvider":
        """获取默认 provider"""
        p = await cls.filter(provider_type=provider_type, is_default=True, status="active").first()
        if not p:
            p = await cls.filter(provider_type=provider_type, status="active").order_by("-priority", "id").first()
        return p

    @classmethod
    async def get_for_resource(cls, resource_type: str, resource_id: int, provider_type: str) -> "ConfigProvider":
        """按资源绑定获取 provider，无绑定时返回默认"""
        binding = await ResourceProviderBinding.filter(
            resource_type=resource_type, resource_id=resource_id,
            provider_type=provider_type, bind_type="preferred"
        ).first()
        if binding:
            p = await cls.filter(id=binding.provider_id, status="active").first()
            if p:
                return p
        return await cls.get_default(provider_type)


class ProviderConfigItem(BaseModel, TimestampMixin):
    """配置提供者的键值对项"""

    CONFIG_TYPES = [
        ("string", "字符串"),
        ("int", "整数"),
        ("float", "浮点数"),
        ("bool", "布尔"),
        ("json", "JSON"),
        ("path", "路径"),
        ("url", "URL"),
        ("password", "密码"),
        ("token", "令牌"),
    ]

    provider = fields.ForeignKeyField("models.ConfigProvider", related_name="items", description="所属提供者")
    config_key = fields.CharField(max_length=128, description="配置键名", db_index=True)
    config_value = fields.TextField(default="", description="配置值")
    config_type = fields.CharField(max_length=32, default="string", choices=CONFIG_TYPES, description="值类型")
    is_secret = fields.BooleanField(default=False, description="是否敏感")
    is_required = fields.BooleanField(default=False, description="是否必填")
    description = fields.CharField(max_length=500, default="", description="描述")
    remark = fields.CharField(max_length=500, default="", description="备注")
    sort = fields.IntField(default=0, description="排序")

    class Meta:
        table = "provider_config_item"
        unique_together = [("provider_id", "config_key")]

    @classmethod
    async def get_map(cls, provider_id: int) -> dict:
        """获取某 provider 的所有配置项 → {config_key: config_value}"""
        items = await cls.filter(provider_id=provider_id).all()
        return {item.config_key: item.config_value for item in items}


class ResourceProviderBinding(BaseModel, TimestampMixin):
    """资源 → 提供者绑定关系"""

    BIND_TYPES = [
        ("preferred", "首选"),
        ("fallback", "备选"),
        ("exclusive", "独占"),
    ]

    resource_type = fields.CharField(max_length=64, description="资源类型 (site/operation_job/gmail_account)", db_index=True)
    resource_id = fields.IntField(description="资源ID", db_index=True)
    provider_type = fields.CharField(max_length=64, description="提供者类型", db_index=True)
    provider = fields.ForeignKeyField("models.ConfigProvider", related_name="bindings", description="提供者")
    bind_type = fields.CharField(max_length=32, default="preferred", choices=BIND_TYPES, description="绑定类型")
    remark = fields.CharField(max_length=500, default="", description="备注")

    class Meta:
        table = "resource_provider_binding"
        unique_together = [("resource_type", "resource_id", "provider_type")]
