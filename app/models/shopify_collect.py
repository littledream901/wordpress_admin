from tortoise import fields

from .base import BaseModel, TimestampMixin


class ShopifySource(BaseModel, TimestampMixin):
    source_url = fields.CharField(max_length=500, unique=True, description='待采集URL', db_index=True)
    source_type = fields.CharField(max_length=32, default='collection', description='source类型：collection/product')
    status = fields.CharField(max_length=64, default='pending', description='采集状态', db_index=True)
    max_products = fields.IntField(default=0, description='最大采集数量，0=不限')
    last_collect_count = fields.IntField(default=0, description='最近一次采集数量')
    last_collect_at = fields.DatetimeField(null=True, description='最近一次采集时间')
    remark = fields.CharField(max_length=500, default='', description='备注')

    class Meta:
        table = 'site_pipeline_shopify_source'


class ShopifyProduct(BaseModel, TimestampMixin):
    source_id = fields.IntField(description='来源ID', db_index=True)
    source_url = fields.CharField(max_length=500, default='', description='来源URL')
    product_url = fields.CharField(max_length=500, unique=True, description='产品URL', db_index=True)
    handle = fields.CharField(max_length=255, default='', description='handle', db_index=True)
    title = fields.CharField(max_length=500, default='', description='标题')
    vendor = fields.CharField(max_length=255, default='', description='vendor')
    product_type = fields.CharField(max_length=255, default='', description='product_type')
    tags = fields.TextField(default='', description='tags')
    status = fields.CharField(max_length=64, default='ready', description='状态', db_index=True)
    prod_info_json = fields.TextField(default='{}', description='完整产品JSON')
    assigned_site_id = fields.IntField(null=True, description='分配目标站点ID', db_index=True)
    assigned_status = fields.CharField(max_length=64, default='', description='分配状态', db_index=True)
    imported_site_id = fields.IntField(null=True, description='最近导入站点ID', db_index=True)
    imported_status = fields.CharField(max_length=64, default='', description='导入状态', db_index=True)
    imported_result = fields.TextField(default='', description='导入结果')

    class Meta:
        table = 'site_pipeline_shopify_product'
