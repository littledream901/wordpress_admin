from tortoise import fields

from .base import BaseModel, TimestampMixin


class GmailAccount(BaseModel, TimestampMixin):
    last_name = fields.CharField(max_length=100, default='', description='last name')
    first_name = fields.CharField(max_length=100, default='', description='first name')
    full_name = fields.CharField(max_length=200, default='', description='full name')
    zip_code = fields.CharField(max_length=32, default='', description='zip code')
    shipping_address_1 = fields.CharField(max_length=255, default='', description='Shipping address 1')
    shipping_address_2 = fields.CharField(max_length=255, default='', description='Shipping address 2')
    country = fields.CharField(max_length=100, default='', description='Country')
    province_state = fields.CharField(max_length=100, default='', description='Province/State')
    city = fields.CharField(max_length=100, default='', description='City')
    phone = fields.CharField(max_length=64, default='', description='phone')
    username = fields.CharField(max_length=255, unique=True, index=True, description='Username')
    password = fields.CharField(max_length=255, default='', description='Password')
    two_fa_key = fields.CharField(max_length=255, default='', description='2FA Key')
    two_fa_code = fields.CharField(max_length=16, default='', description='2FA 验证码')
    link_to_generate_login_code = fields.CharField(max_length=500, default='', description='Link To Generate Login Code from 2FA Key')
    recovery_email = fields.CharField(max_length=255, default='', description='Recovery Email')
    status = fields.CharField(max_length=64, default='正常', description='健康状态', index=True)
    assigned_site_id = fields.IntField(null=True, description='分配站点ID', index=True)
    assigned_site_domain = fields.CharField(max_length=255, default='', description='分配站点域名')

    class Meta:
        table = 'site_pipeline_gmail_account'
