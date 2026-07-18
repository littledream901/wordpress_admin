"""ADS 浏览器环境管理"""

from tortoise import fields
from app.models.base import BaseModel, SoftDeleteMixin, TimestampMixin


class AdsEnv(BaseModel, SoftDeleteMixin, TimestampMixin):
    """ADS 浏览器环境

    管理 ADS 浏览器（防关联浏览器）的环境实例，
    一个 ADS 环境可关联多个站点。
    """
    ads_env_id = fields.CharField(max_length=128, unique=True, db_index=True, description='ADS环境ID')
    sites = fields.ManyToManyField(
        'models.Site', related_name='ads_envs',
        description='关联站点（一对多）',
    )
    domain = fields.CharField(max_length=255, default='', description='域名（冗余，便于搜索）')
    status = fields.CharField(max_length=32, default='正常', db_index=True, description='状态: 正常/异常/离线')
    remark = fields.CharField(max_length=512, default='', description='备注')

    class Meta:
        table = 'ads_env'
