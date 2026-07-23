"""
Task Runner 基类 —— 所有后台任务执行器的抽象基类。

职责：
  - 提供统一的 _exec() 线程池执行器
  - 提供标准的任务生命周期：create → update_step → complete
  - 自动注入 Provider 信息到任务结果
"""

import asyncio
import json
import logging
import os
import traceback
import uuid
from datetime import datetime
from typing import Any, Callable, Optional

from app.core.exceptions import (
    ExternalAPIError,
    ProviderConfigError,
    ResourceBusyError,
    TaskExecutionError,
)
from app.log.log import set_trace_id, get_trace_id, logger as loguru_logger
from app.models.operation_job import OperationJob
from app.models.site_pipeline import Site

_log = logging.getLogger(__name__)

# ── 实例标识（用于 worker 归属和心跳） ──
_INSTANCE_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"

# ── action_type → provider_type 映射 ──
_ACTION_PROVIDER: dict[str, str] = {
    "dns": "cloudflare",
    "dynadot_ns": "dynadot",
    "redirect": "cloudflare",
    "provision": "onepanel",
    "woo_import": "woo",
    "hub_create_env": "hubstudio",
    "hub_create_account": "hubstudio",
    "hub_update_env": "hubstudio",
    "hub_wp_login": "hubstudio",
}


class TaskRunner:
    """后台任务执行器基类"""

    @staticmethod
    def _with_trace(site_id: int, action: str) -> str:
        """生成并设置 trace_id，返回 trace_id 字符串"""
        tid = f"{action}-{site_id}-{uuid.uuid4().hex[:8]}"
        set_trace_id(tid)
        loguru_logger.info("任务开始", site_id=site_id, action=action, trace_id=tid)
        return tid

    def _provider_type(self, job: OperationJob) -> str:
        return _ACTION_PROVIDER.get(job.action_type, "")

    # ── 错误分类 ──

    @staticmethod
    def _classify_error(exc: Exception) -> dict:
        """分类异常并返回结构化信息，供日志和 API 响应使用"""
        if isinstance(exc, ProviderConfigError):
            return {"category": "config", "recoverable": False}
        if isinstance(exc, ExternalAPIError):
            return {"category": "external_api", "recoverable": True}
        if isinstance(exc, ResourceBusyError):
            return {"category": "resource_busy", "recoverable": False}
        if isinstance(exc, asyncio.TimeoutError):
            return {"category": "timeout", "recoverable": True}
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            return {"category": "network", "recoverable": True}
        return {"category": "unknown", "recoverable": False}

    @staticmethod
    def _format_error(exc: Exception) -> str:
        """格式化异常为可读字符串，保留完整堆栈"""
        if isinstance(exc, (ExternalAPIError, ProviderConfigError, ResourceBusyError)):
            return str(exc)
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        return f"{exc.__class__.__name__}: {exc}" + (
            f"\n{tb[-1].strip()}" if tb else ""
        )

    # ── 线程池执行 ──

    @staticmethod
    def _exec(fn: Callable, timeout: int = 600) -> Any:
        """在线程池中执行同步函数，避免阻塞事件循环。

        严禁传入捕获 Tortoise ORM 模型实例的闭包！
        fn 内部不能访问 ORM（模型查询/保存/关联属性懒加载），只能做 HTTP 调用或纯计算。
        跨线程共享 ORM 模型实例会污染事件循环连接状态，导致数据丢失。
        """
        loop = asyncio.get_event_loop()
        fn_name = getattr(fn, '__name__', str(fn))
        try:
            return asyncio.wait_for(
                loop.run_in_executor(None, fn), timeout=timeout
            )
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(
                f"[runner] 步骤超时（{timeout}s）: {fn_name}"
            )
        except Exception:
            loguru_logger.error(
                "[runner] _exec 线程池异常: fn=%s", fn_name, exc_info=True,
            )
            raise

    @staticmethod
    def _schedule_cleanup(fn: Callable, timeout: int = 30) -> None:
        """后台异步清理，不阻塞主流程，失败静默忽略。"""
        async def _wrapper():
            try:
                await TaskRunner._exec(fn, timeout=timeout)
            except Exception:
                loguru_logger.warning("[runner] 后台清理失败（非关键）", exc_info=True)
        asyncio.create_task(_wrapper())

    # ── 任务生命周期 ──

    @staticmethod
    async def _create_job(
        site_id: int,
        domain: str,
        action_type: str,
        payload: dict = None,
        batch_id: str = "",
        total_steps: int = 1,
    ) -> OperationJob:
        return await OperationJob.create(
            resource_type="site",
            resource_id=site_id,
            domain=domain,
            action_type=action_type,
            status="running",
            step="0",
            total_steps=total_steps,
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
            batch_id=batch_id,
            worker_name=_INSTANCE_ID,
            last_heartbeat=datetime.now(),
            started_at=datetime.now(),
        )

    @staticmethod
    async def _update_step(job: OperationJob, step: str):
        job.step = step
        job.last_heartbeat = datetime.now()
        await job.save(update_fields=["step", "last_heartbeat"])

    async def _complete_job(
        self,
        job: OperationJob,
        ok: bool,
        result: dict = None,
        error: str = "",
        site: Site = None,
        exc: Exception = None,
    ):
        """完成任务并回写结果，自动注入 Provider 信息，追加站点日志"""
        # 错误分类
        error_category = ""
        if exc:
            error_category = self._classify_error(exc)["category"]
            error = error or self._format_error(exc)
            loguru_logger.error(
                "任务失败",
                action=job.action_type,
                site_id=job.resource_id,
                category=error_category,
                error=error[:300],
            )

        job.status = "success" if ok else "failed"
        ptype = self._provider_type(job)
        provider_info = None
        if result:
            if ptype:
                from app.utils.config_reader import get_provider_info_async
                provider_info = await get_provider_info_async(ptype)
                result = {**result, "provider": provider_info}
            job.result_json = json.dumps(result, ensure_ascii=False)
        if error:
            job.error_message = error
        job.finished_at = datetime.now()
        if ok and job.total_steps > 1:
            job.step = "done"
        await job.save()

        # 自动追加站点日志（site 允许为 None，资源不存时不崩）
        if not site and job.resource_id:
            try:
                from app.controllers.site_pipeline import site_controller
                site = await site_controller.get(id=job.resource_id)
            except Exception:
                _log.warning("_complete_job: 无法获取关联站点 resource_id=%s action=%s job_id=%s",
                             job.resource_id, job.action_type, job.id)
                pass
        if site:
            self._append_site_log(
                site, job.action_type,
                data={"result": result} if result else {},
                provider_info=provider_info,
                action=job.action_type,
                status=job.status,
                started_at=job.started_at,
                completed_at=job.finished_at,
                error=error,
            )

    @staticmethod
    def _append_site_log(
        site: Site,
        source: str,
        data: dict,
        provider_info: dict = None,
        action: str = "",
        status: str = "success",
        started_at: datetime = None,
        completed_at: datetime = None,
        error: str = "",
    ):
        """追加站点流水线日志（结构化的 JSON 条目）"""

        now = datetime.now()
        started = started_at or now
        completed = completed_at or now
        # 统一去除时区信息
        if hasattr(started, 'tzinfo') and started.tzinfo is not None:
            started = started.replace(tzinfo=None)
        if hasattr(completed, 'tzinfo') and completed.tzinfo is not None:
            completed = completed.replace(tzinfo=None)
        duration_ms = int((completed - started).total_seconds() * 1000)

        entry = {
            "ts": now.isoformat(),
            "source": source,
            "action": action or source,
            "status": status,
            "started_at": started.isoformat() if started else None,
            "completed_at": completed.isoformat() if completed else None,
            "duration_ms": duration_ms,
            "error": error,
            **data,
        }
        if provider_info:
            entry["provider"] = provider_info

        old_log = site.pipeline_log or ""
        site.pipeline_log = (old_log + "\n" + json.dumps(entry, ensure_ascii=False)).strip()


# 模块级单例 —— site_pipeline.py 等 API 层可直接复用
task_runner = TaskRunner()
