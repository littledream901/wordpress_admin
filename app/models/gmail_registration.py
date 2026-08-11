"""Gmail 企业邮箱注册模型

流程状态机（已移除 ImprovMX 转发步骤）：
  pending → env_created → registering → completed
                                    ↓
                                 failed
"""
from tortoise import fields

from .base import BaseModel, SoftDeleteMixin, TimestampMixin


class GmailRegistration(BaseModel, SoftDeleteMixin, TimestampMixin):
    """Gmail 注册流程记录表"""

    # ── 基础信息 ──
    alias = fields.CharField(max_length=100, description='邮箱别名（Gmail 前缀）', db_index=True)
    domain = fields.CharField(max_length=255, description='站点域名', db_index=True)
    
    # 关联站点（批量获取时自动绑定，便于复用站点配置）
    site_id = fields.IntField(null=True, description='关联站点ID', db_index=True)
    
    full_name = fields.CharField(max_length=200, default='', description='完整姓名')
    first_name = fields.CharField(max_length=100, default='', description='名')
    last_name = fields.CharField(max_length=100, default='', description='姓')
    password = fields.CharField(max_length=255, default='', description='Gmail 密码')

    # ── 地址信息 ──
    country = fields.CharField(max_length=100, default='', description='国家')
    province_state = fields.CharField(max_length=100, default='', description='省/州')
    city = fields.CharField(max_length=100, default='', description='城市')
    zip_code = fields.CharField(max_length=32, default='', description='邮编')
    shipping_address_1 = fields.CharField(max_length=255, default='', description='地址1')
    shipping_address_2 = fields.CharField(max_length=255, default='', description='地址2（可选）')
    phone = fields.CharField(max_length=64, default='', description='电话')

    # ── 转发配置 ──
    forward_to = fields.CharField(max_length=255, default='', description='ImprovMX 转发目标邮箱')
    recovery_email = fields.CharField(max_length=255, default='', description='恢复邮箱（自动生成：alias@domain）')
    api_url = fields.CharField(max_length=500, default='', description='API URL')
    two_fa_key = fields.CharField(max_length=255, default='', description='2FA Key')

    # ── ImprovMX 转发结果 ──
    improvmx_alias_id = fields.CharField(max_length=64, default='', description='ImprovMX 别名 ID')
    improvmx_status = fields.CharField(max_length=32, default='', description='转发状态：success / failed', db_index=True)
    improvmx_error = fields.TextField(default='', description='ImprovMX 错误信息')

    # ── HubStudio 环境结果 ──
    env_id = fields.CharField(max_length=128, default='', description='HubStudio 环境 ID (containerCode)', db_index=True)
    env_name = fields.CharField(max_length=255, default='', description='HubStudio 环境名称')
    env_status = fields.CharField(max_length=32, default='', description='环境状态：success / failed', db_index=True)
    env_error = fields.TextField(default='', description='环境创建错误信息')

    # ── SMS 验证结果 ──
    sms_request_id = fields.IntField(null=True, description='SMSMan request_id', db_index=True)
    sms_phone_number = fields.CharField(max_length=64, default='', description='SMS 号码')
    sms_code = fields.CharField(max_length=16, default='', description='SMS 验证码')
    sms_status = fields.CharField(max_length=32, default='', description='SMS 状态：acquired / code_received / used / failed', db_index=True)
    sms_error = fields.TextField(default='', description='SMS 错误信息')

    # ── 关联账号 ──
    outlook_account_id = fields.IntField(null=True, description='分配的 Outlook 账号 ID', db_index=True)
    outlook_account_username = fields.CharField(max_length=255, default='', description='Outlook 账号用户名（冗余，便于展示）')

    # ── 注册结果 ──
    registration_email = fields.CharField(max_length=255, default='', description='注册成功的 Gmail 地址', db_index=True)
    registration_status = fields.CharField(
        max_length=32,
        default='pending',
        description='注册状态：pending / forwarding_created / env_created / registering / completed / failed',
        db_index=True,
    )
    registration_error = fields.TextField(default='', description='注册失败错误信息')

    # ── 备注 ──
    remark = fields.TextField(default='', description='备注')

    class Meta:
        table = 'site_pipeline_gmail_registration'
        unique_together = (('alias', 'domain'),)  # 同域名下别名唯一，数据库层防重
