"""Google Feed 文件管理模型

管理上传的 Feed 文件（CSV/XML）、副本及域名替换记录。
处理后的文件默认 3 天后过期自动删除。
"""
from datetime import datetime, timedelta

from tortoise import fields

from .base import BaseModel, TimestampMixin


class FeedFile(BaseModel, TimestampMixin):
    """Feed 文件"""
    original_name = fields.CharField(max_length=500, default='', description='原始文件名')
    source_file = fields.CharField(max_length=500, default='', description='源文件路径 (文件A)')
    copy_file = fields.CharField(max_length=500, default='', description='副本文件路径 (文件B)')
    processed_file = fields.CharField(max_length=500, default='', description='替换后的文件路径')
    file_type = fields.CharField(max_length=10, default='', description='文件类型: csv / xml')
    file_size = fields.IntField(default=0, description='文件大小(字节)')
    source_domain = fields.CharField(max_length=255, default='', description='原始域名')
    target_domain = fields.CharField(max_length=255, default='', description='替换目标域名')
    replace_count = fields.IntField(default=0, description='替换次数')
    status = fields.CharField(max_length=32, default='uploaded', description='状态: uploaded/copied/replaced')
    expires_at = fields.DatetimeField(null=True, description='过期时间（处理后文件在此时间后不可下载）')

    class Meta:
        table = 'site_pipeline_feed_file'
        ordering = ['-id']

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        # 统一转 naive 比较（兼容 SQLite/Tortoise 可能返回 aware datetime）
        exp = self.expires_at.replace(tzinfo=None) if self.expires_at.tzinfo else self.expires_at
        return datetime.now() > exp

    @property
    def expires_in_minutes(self) -> int:
        """剩余有效时间（分钟），已过期返回 0"""
        if not self.expires_at:
            return 0
        exp = self.expires_at.replace(tzinfo=None) if self.expires_at.tzinfo else self.expires_at
        delta = (exp - datetime.now()).total_seconds() // 60
        return max(0, int(delta))
