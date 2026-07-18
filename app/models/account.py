from tortoise import fields

from .base import BaseModel, SoftDeleteMixin, TimestampMixin


class Account(BaseModel, SoftDeleteMixin, TimestampMixin):
    account_type = fields.CharField(max_length=50, description="账号类型", db_index=True)
    username = fields.CharField(max_length=200, description="账号", db_index=True)
    password = fields.CharField(max_length=500, description="密码")
    env_id = fields.IntField(default=0, description="环境ID", db_index=True)
    two_fa = fields.CharField(max_length=500, null=True, description="2FA")
    remark = fields.TextField(null=True, description="备注")
    provider = fields.ForeignKeyField("models.ConfigProvider", null=True, related_name="accounts", description="关联Provider")

    class Meta:
        table = "account"
