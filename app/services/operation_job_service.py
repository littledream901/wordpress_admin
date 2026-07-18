"""
统一任务服务 (OperationJobService)

所有业务操作的统一入口，替换散落在各处的手动任务管理逻辑。
能力：
  - 创建任务 / 批量创建
  - Worker 领取任务
  - 上报进度 / 结果
  - 自动联动 Site 状态更新
  - 重试失败任务
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Optional

from app.controllers.operation_job import operation_job_controller
from app.models.operation_job import OperationJob
from app.models.site_pipeline import Site


# ── Site 状态字段映射 ──
# action_type → Site 模型的状态字段名 + pipeline_status 前缀
_SITE_STATUS_MAP: dict[str, tuple[str, str]] = {
    "dns": ("cloudflare_status", "dns"),
    "dynadot_ns": ("dynadot_status", "dynadot_ns"),
    "redirect": ("cloudflare_status", "redirect"),
    "provision": ("onepanel_status", "provision"),
    "assign_gmail": ("pipeline_status", "assign_gmail"),
    "woo_import": ("woo_import_status", "woo_import"),
    "hub_create_env": ("hub_status", "hubstudio"),
    "hub_create_account": ("hub_status", "hubstudio"),
    "hub_update_env": ("hub_status", "hubstudio"),
    "hub_website_control": ("hub_status", "hubstudio"),
    "hub_gmc_check": ("gmc_status", "hubstudio"),
}

# action_type → provider_type（用于日志中记录所用账号）
_ACTION_PROVIDER_MAP: dict[str, str] = {
    "dns": "cloudflare",
    "dynadot_ns": "dynadot",
    "redirect": "cloudflare",
    "provision": "onepanel",
    "woo_import": "woo",
}
for _hub_key in ["hub_create_env", "hub_create_account", "hub_update_env", "hub_website_control", "hub_gmc_check"]:
    _ACTION_PROVIDER_MAP[_hub_key] = "hubstudio"


class OperationJobService:
    """统一任务服务"""

    # ── 创建任务 ──

    @staticmethod
    async def create_task(
        resource_type: str,
        resource_id: int,
        action_type: str,
        domain: str = "",
        payload: dict = None,
        max_retry: int = 3,
    ) -> OperationJob:
        """创建单个任务"""
        job = await operation_job_controller.create(
            dict(
                resource_type=resource_type,
                resource_id=resource_id,
                domain=domain,
                action_type=action_type,
                payload_json=json.dumps(payload or {}, ensure_ascii=False),
                max_retry=max_retry,
            )
        )
        return job

    @staticmethod
    async def batch_create(
        resource_type: str,
        resource_ids: list[int],
        action_type: str,
        domains: list[str] = None,
        payload: dict = None,
    ) -> list[OperationJob]:
        """批量创建任务，返回 batch_id 关联的一组任务"""
        return await operation_job_controller.batch_create(
            resource_type, resource_ids, action_type, domains or [], payload
        )

    # ── Worker 操作 ──

    @staticmethod
    async def claim_task(
        action_type: str = None, worker_name: str = "worker"
    ) -> Optional[OperationJob]:
        """Worker 领取一个待执行任务"""
        job = await operation_job_controller.claim_next_pending(action_type, worker_name)
        if job:
            job.started_at = datetime.now()
            await job.save(update_fields=["started_at"])
        return job

    @staticmethod
    async def report_progress(
        job_id: int, step: str, total_steps: int = None
    ) -> bool:
        """上报任务进度（更新 step 字段）"""
        update_kw = {"step": step}
        if total_steps is not None:
            update_kw["total_steps"] = total_steps
        await OperationJob.filter(id=job_id).update(**update_kw)
        return True

    @staticmethod
    async def report_success(
        job_id: int,
        result: dict = None,
        step: str = None,
    ) -> bool:
        """上报任务成功，自动联动更新 Site 状态"""
        update_kw = {
            "status": "success",
            "finished_at": datetime.now(),
        }
        if result is not None:
            update_kw["result_json"] = json.dumps(result, ensure_ascii=False)
        if step is not None:
            update_kw["step"] = str(step)
        await OperationJob.filter(id=job_id).update(**update_kw)

        # 联动更新 Site
        await OperationJobService._sync_site_status(job_id, "success", result or {})
        return True

    @staticmethod
    async def report_failure(
        job_id: int,
        error_message: str,
        step: str = None,
    ) -> bool:
        """上报任务失败，自动联动更新 Site 状态"""
        update_kw = {
            "status": "failed",
            "error_message": error_message,
            "finished_at": datetime.now(),
        }
        if step is not None:
            update_kw["step"] = str(step)
        await OperationJob.filter(id=job_id).update(**update_kw)

        # 联动更新 Site
        await OperationJobService._sync_site_status(job_id, "failed", {})
        return True

    # ── 重试 ──

    @staticmethod
    async def retry_task(job_id: int) -> Optional[OperationJob]:
        """重试失败的任务（重置为 pending，retry_count + 1）"""
        job = await OperationJob.filter(id=job_id).first()
        if not job:
            return None
        if job.retry_count >= job.max_retry:
            return None  # 超过最大重试次数
        await OperationJob.filter(id=job_id).update(
            status="pending",
            retry_count=job.retry_count + 1,
            error_message="",
            result_json="{}",
            step="",
            started_at=None,
            finished_at=None,
        )
        return await OperationJob.filter(id=job_id).first()

    # ── 查询 ──

    @staticmethod
    async def get_batch_summary(batch_id: str) -> dict[str, Any]:
        """获取批次任务的汇总状态"""
        jobs = await operation_job_controller.get_by_batch(batch_id)
        total = len(jobs)
        status_counts = {}
        for j in jobs:
            status_counts[j.status] = status_counts.get(j.status, 0) + 1
        return {
            "batch_id": batch_id,
            "total": total,
            "pending": status_counts.get("pending", 0),
            "running": status_counts.get("running", 0),
            "success": status_counts.get("success", 0),
            "failed": status_counts.get("failed", 0),
            "finished": status_counts.get("success", 0) + status_counts.get("failed", 0),
            "is_done": all(j.status in ("success", "failed", "cancelled", "skipped") for j in jobs),
        }

    @staticmethod
    async def get_pending_count(
        resource_type: str = None, action_type: str = None
    ) -> int:
        """获取待处理任务数"""
        qs = OperationJob.filter(status="pending")
        if resource_type:
            qs = qs.filter(resource_type=resource_type)
        if action_type:
            qs = qs.filter(action_type=action_type)
        return await qs.count()

    # ── 取消 ──

    @staticmethod
    async def cancel_task(job_id: int) -> bool:
        """取消任务"""
        job = await OperationJob.filter(id=job_id).first()
        if not job or job.status in ("success", "cancelled"):
            return False
        await OperationJob.filter(id=job_id).update(
            status="cancelled", finished_at=datetime.now()
        )
        return True

    # ── 内部方法 ──

    @staticmethod
    async def _sync_site_status(job_id: int, status: str, result: dict):
        """联动更新 Site 的状态、日志"""
        job = await OperationJob.filter(id=job_id).first()
        if not job or job.resource_type != "site":
            return
        site = await Site.filter(id=job.resource_id).first()
        if not site:
            return

        mapping = _SITE_STATUS_MAP.get(job.action_type)
        if not mapping:
            return
        status_field, pipeline_prefix = mapping

        # 更新 Site 状态字段
        setattr(site, status_field, status)
        site.pipeline_status = f"{pipeline_prefix}:{status}"

        # 追加 pipeline_log
        provider_type = _ACTION_PROVIDER_MAP.get(job.action_type, "")
        from app.utils.config_reader import get_provider_info
        provider = get_provider_info(provider_type) if provider_type else {}
        log_entry = json.dumps({
            "job_id": job.id,
            "action": job.action_type,
            "status": status,
            "error_message": job.error_message,
            "result": result if result and len(str(result)) < 500 else {},
            "provider": provider,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False)
        old_log = site.pipeline_log or ""
        site.pipeline_log = (old_log + "\n" + log_entry).strip()

        # HubStudio 特殊处理：提取 env_id
        if job.action_type.startswith("hub_") and status == "success":
            env_id = (
                result.get("env_id")
                or result.get("containerCode")
                or result.get("id")
                or result.get("code")
            )
            if env_id:
                site.hub_env_id = str(env_id)

        await site.save()


# 全局单例
operation_job_service = OperationJobService()
