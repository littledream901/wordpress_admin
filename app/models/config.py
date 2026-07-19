from tortoise import fields

from .base import BaseModel, TimestampMixin


class Config(BaseModel, TimestampMixin):
    """系统配置键值对表，按 category 分类管理 1Panel、Cloudflare、Dynadot、HubStudio 等配置"""
    CATEGORY_CHOICES = [
        ('onepanel', '1Panel'),
        ('cloudflare', 'Cloudflare'),
        ('dynadot', 'Dynadot'),
        ('hubstudio', 'HubStudio'),
        ('woo', 'WooCommerce'),
        ('shopify', 'Shopify'),
        ('pipeline', '流水线'),
        ('general', '通用'),
    ]

    name = fields.CharField(max_length=100, unique=True, description="配置键名", db_index=True)
    value = fields.TextField(default="", description="配置值")
    description = fields.CharField(max_length=255, null=True, description="配置说明")
    category = fields.CharField(max_length=50, choices=CATEGORY_CHOICES, description="配置分类", db_index=True)
    sort_order = fields.IntField(default=0, description="排序")
    is_secret = fields.BooleanField(default=False, description="是否为敏感信息（前端脱敏显示）")
    is_enabled = fields.BooleanField(default=True, description="是否启用")

    class Meta:
        table = "config"

    @classmethod
    async def get_config_map(cls, category: str) -> dict:
        """获取某个分类下所有配置的{name: value}字典"""
        rows = await cls.filter(category=category, is_enabled=True).all()
        return {row.name: row.value for row in rows}

    @classmethod
    async def get_value(cls, name: str, default: str = "") -> str:
        """获取单个配置值"""
        row = await cls.filter(name=name, is_enabled=True).first()
        return row.value if row else default
