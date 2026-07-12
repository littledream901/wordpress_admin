"""导入任务模型"""
from tortoise import fields

from .base import BaseModel, TimestampMixin


class ImportJob(BaseModel, TimestampMixin):
    """导入任务表

    所有 CSV/Excel 导入操作统一记录到此表。
    """

    IMPORT_TYPES = [
        ("sites", "站点"),
        ("gmail", "Gmail账号"),
        ("shopify_sources", "采集源"),
        ("shopify_products", "商品"),
    ]

    STATUS_CHOICES = [
        ("pending", "等待中"),
        ("processing", "处理中"),
        ("success", "成功"),
        ("partial", "部分成功"),
        ("failed", "失败"),
    ]

    import_type = fields.CharField(max_length=32, choices=IMPORT_TYPES, description="导入类型", index=True)
    file_name = fields.CharField(max_length=255, description="文件名")
    status = fields.CharField(max_length=16, default="pending", choices=STATUS_CHOICES, description="状态")
    success_count = fields.IntField(default=0, description="成功数量")
    fail_count = fields.IntField(default=0, description="失败数量")
    error_report = fields.TextField(default="", description="错误报告(JSON)")

    class Meta:
        table = "import_job"
