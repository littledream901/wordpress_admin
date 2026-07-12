from datetime import datetime
from tortoise import fields

from .base import BaseModel, TimestampMixin


class Site(BaseModel, TimestampMixin):
    domain = fields.CharField(max_length=255, unique=True, description='域名', index=True)
    server_ip = fields.CharField(max_length=64, default='', description='服务器IP')
    status = fields.CharField(max_length=64, default='待处理', description='站点状态', index=True)
    login_url = fields.CharField(max_length=500, default='', description='登录地址')
    woo_ck = fields.CharField(max_length=255, default='', description='Woo CK')
    woo_cs = fields.CharField(max_length=255, default='', description='Woo CS')
    ctx_refresh_url = fields.CharField(max_length=500, default='', description='CTX刷新链接')
    feed_link = fields.CharField(max_length=500, default='', description='Feed链接')
    cloudflare_status = fields.CharField(max_length=64, default='', description='Cloudflare状态', index=True)
    dynadot_status = fields.CharField(max_length=64, default='', description='Dynadot状态', index=True)
    onepanel_status = fields.CharField(max_length=64, default='', description='1Panel建站状态', index=True)
    hub_env_id = fields.CharField(max_length=255, default='', description='Hub环境ID')
    hub_env_name = fields.CharField(max_length=255, default='', description='Hub容器名称')
    hub_status = fields.CharField(max_length=64, default='', description='Hub状态', index=True)
    hub_account_id = fields.CharField(max_length=255, default='', description='Hub账号ID')
    hub_last_action = fields.CharField(max_length=64, default='', description='Hub最后操作类型')
    woo_import_status = fields.CharField(max_length=64, default='', description='Woo导入状态', index=True)
    gmc_status = fields.CharField(max_length=64, default='', description='GMC状态', index=True)
    gmc_data = fields.TextField(default='', description='GMC详细数据(JSON)')
    pipeline_status = fields.CharField(max_length=64, default='', description='流水线状态', index=True)
    pipeline_log = fields.TextField(default='', description='流水线日志')

    class Meta:
        table = 'site_pipeline_site'

    def append_log(self, entry: dict):
        import json
        entry['ts'] = datetime.now().isoformat()
        self.pipeline_log = (self.pipeline_log or '') + '\n' + json.dumps(entry, ensure_ascii=False)


class HubStudioJob(BaseModel, TimestampMixin):
    site_id = fields.IntField(description='站点ID', index=True)
    domain = fields.CharField(max_length=255, description='域名', index=True)
    provider_id = fields.IntField(default=0, description='执行节点 provider_id')
    job_type = fields.CharField(max_length=64, default='create_env', description='任务类型', index=True)
    status = fields.CharField(max_length=32, default='pending', description='任务状态', index=True)
    payload_json = fields.TextField(default='{}', description='任务负载')
    result_json = fields.TextField(default='{}', description='任务结果')
    error_message = fields.TextField(default='', description='错误信息')
    worker_name = fields.CharField(max_length=128, default='', description='执行节点名称')
    retry_count = fields.IntField(default=0, description='重试次数')
    started_at = fields.DatetimeField(null=True, description='开始执行时间')
    finished_at = fields.DatetimeField(null=True, description='完成时间')

    class Meta:
        table = 'site_pipeline_hubstudio_job'
        ordering = ['-id']


class HubStudioAgentHeartbeat(BaseModel):
    """Agent 心跳记录 — 用于检测 Agent 是否在线"""
    worker_name = fields.CharField(max_length=128, unique=True, description='节点名称')
    provider_id = fields.IntField(default=0, description='对应的 provider_id')
    last_heartbeat = fields.DatetimeField(auto_now=True, description='最后心跳时间')
    status = fields.CharField(max_length=32, default='online', description='状态: online / offline')
    version = fields.CharField(max_length=32, default='', description='Agent 版本')
    host_info = fields.CharField(max_length=255, default='', description='主机信息')
    last_task_id = fields.IntField(default=0, description='最后执行的任务ID')
    last_task_status = fields.CharField(max_length=32, default='', description='最后任务状态')
    total_tasks = fields.IntField(default=0, description='累计执行任务数')

    class Meta:
        table = 'site_pipeline_hubstudio_agent_heartbeat'
