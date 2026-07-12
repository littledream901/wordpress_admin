"""通用操作任务模型 —— 统一的任务中心"""
from tortoise import fields

from .base import BaseModel, TimestampMixin


class OperationJob(BaseModel, TimestampMixin):
    """通用操作任务表

    所有流水线操作（DNS / 建站 / HubStudio / Woo 导入 等）皆通过此表统一管理。
    支持：单任务、批量任务、重试、步骤追踪。
    """

    RESOURCE_TYPES = [
        ("site", "站点"),
        ("gmail", "Gmail账号"),
        ("shopify_source", "采集源"),
        ("shopify_product", "商品"),
    ]

    ACTION_TYPES = [
        ("dns", "Cloudflare DNS"),
        ("dynadot_ns", "Dynadot NS"),
        ("redirect", "301重定向"),
        ("provision", "1Panel建站"),
        ("assign_gmail", "分配Gmail"),
        ("collect_shopify", "采集商品"),
        ("assign_products", "分配产品"),
        ("woo_import", "Woo导入"),
        ("hub_create_env", "Hub创建环境"),
        ("hub_create_account", "Hub创建账号"),
        ("hub_update_env", "Hub更新环境"),
        ("hub_website_control", "Hub网站控制"),
        ("import_sites", "导入站点"),
        ("import_gmail", "导入Gmail"),
        ("import_shopify_sources", "导入采集源"),
        ("import_shopify_products", "导入商品"),
    ]

    STATUS_CHOICES = [
        ("pending", "等待中"),
        ("queued", "已入队"),
        ("running", "执行中"),
        ("success", "成功"),
        ("failed", "失败"),
        ("partial_success", "部分成功"),
        ("retrying", "重试中"),
        ("cancelled", "已取消"),
        ("skipped", "已跳过"),
    ]

    resource_type = fields.CharField(max_length=32, description="资源类型", index=True)
    resource_id = fields.IntField(default=0, description="资源ID", index=True)
    domain = fields.CharField(max_length=255, default="", description="关联域名", index=True)
    action_type = fields.CharField(max_length=32, choices=ACTION_TYPES, description="操作类型", index=True)
    status = fields.CharField(max_length=16, default="pending", choices=STATUS_CHOICES, description="任务状态", index=True)
    step = fields.CharField(max_length=64, default="", description="当前步骤标识")
    total_steps = fields.IntField(default=1, description="总步骤数")
    payload_json = fields.TextField(default="{}", description="任务负载(JSON)")
    result_json = fields.TextField(default="{}", description="任务结果(JSON)")
    error_message = fields.TextField(default="", description="错误信息")
    worker_name = fields.CharField(max_length=128, default="", description="执行节点")
    batch_id = fields.CharField(max_length=64, default="", description="批次ID（批量操作）", index=True)
    retry_count = fields.IntField(default=0, description="已重试次数")
    max_retry = fields.IntField(default=3, description="最大重试次数")
    started_at = fields.DatetimeField(null=True, description="开始执行时间")
    finished_at = fields.DatetimeField(null=True, description="完成时间")

    class Meta:
        table = "operation_job"

    @classmethod
    async def create_batch(cls, resource_type: str, resource_ids: list[int], action_type: str,
                           domains: list[str] = None, payload: dict = None) -> list["OperationJob"]:
        import uuid
        batch_id = uuid.uuid4().hex[:12]
        jobs = []
        for i, rid in enumerate(resource_ids):
            domain = (domains or [""] * len(resource_ids))[i] if i < len(domains or []) else ""
            job = await cls.create(
                resource_type=resource_type,
                resource_id=rid,
                domain=domain,
                action_type=action_type,
                payload_json=str(payload or {}),
                batch_id=batch_id,
            )
            jobs.append(job)
        return jobs
