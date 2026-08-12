"""
网关防御部署任务执行器 —— 统一接入 OperationJob 任务队列

职责：
  - 单站点/批量部署统一走 OperationJob，接口立即返回 job_id
  - 并发受信号量限制，防止 1Panel / Cloudflare API 被打爆
  - 单任务整体超时保护，避免 job 永久 running
  - 幂等：同站点已有 running/pending 的 gateway_defense 任务时拒绝重复提交

平台路由：
  - shopify  → CloudflareWorkerDefenseService
  - 其他平台 → NginxLuaDefenseService
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta

from app.models.operation_job import OperationJob
from app.services.gateway_defense import (
    CloudflareWorkerDefenseService,
    NginxLuaDefenseService,
)
from app.utils.provider_resolver import ProviderResolver
from .runner import TaskRunner

_log = logging.getLogger(__name__)

ACTION_TYPE = "gateway_defense"

# 单站点部署整体超时（nginx_lua 含多次文件上传 + 自检重试，留足余量）
DEPLOY_TIMEOUT_SECONDS = 600

# 卡死任务回收阈值
STALE_TIMEOUT_MINUTES = 15

_semaphore: asyncio.Semaphore | None = None


async def _get_semaphore() -> asyncio.Semaphore:
    """惰性创建部署信号量（复用 onepanel 的 max_concurrent 配置）"""
    global _semaphore
    if _semaphore is None:
        val = await ProviderResolver.get_config("onepanel", "max_concurrent", default="")
        _semaphore = asyncio.Semaphore(int(val) if val and val.isdigit() else 3)
    return _semaphore


async def _check_blocked(site_id: int) -> OperationJob | None:
    """检查站点是否已有进行中的部署任务，超过阈值的僵尸任务自动回收。"""
    for status in ("running", "pending", "queued"):
        job = await OperationJob.filter(
            resource_type="site", resource_id=site_id,
            action_type=ACTION_TYPE, status=status,
        ).first()
        if not job:
            continue
        if job.started_at:
            elapsed = datetime.now().astimezone() - job.started_at.astimezone()
            if elapsed > timedelta(minutes=STALE_TIMEOUT_MINUTES):
                job.status = "failed"
                job.error_message = (
                    f"任务超时自动回收（{status} 超过 {STALE_TIMEOUT_MINUTES} 分钟）"
                )
                job.finished_at = datetime.now()
                await job.save()
                _log.warning(
                    "[gateway_defense] 回收僵尸任务: job_id=%s site_id=%s", job.id, site_id
                )
                continue
        return job
    return None


class GatewayDefenseTaskRunner(TaskRunner):
    """网关防御部署任务执行器"""

    # ── 入口 ──

    async def execute(
        self,
        site_id: int,
        gateway_url: str,
        site_key: str | None = None,
        site_secret: str | None = None,
        fail_mode: str = "open",
        sdk_inject: bool = True,
        gateway_site_id: str | None = None,
        batch_id: str = "",
        auto_provision: bool = False,
        rule_ids: list | None = None,
    ) -> dict:
        """创建部署任务并后台执行，立即返回 job_id。

        auto_provision=True 时，后台先自动「建站 + 绑定规则」拿到 site_key/site_secret，
        再走部署流程；此时 site_key/site_secret/gateway_site_id 可留空（由自动建站回填）。
        """
        from app.controllers.site_pipeline import site_controller

        site = await site_controller.get(id=site_id)
        if not site:
            return {"ok": False, "code": 404, "error": f"站点不存在: id={site_id}"}

        # 密钥必须成对提供（自动建站模式下无需外部密钥）
        if not auto_provision and bool(site_key) != bool(site_secret):
            return {"ok": False, "code": 400, "error": "site_key 和 site_secret 必须同时提供"}

        blocked = await _check_blocked(site_id)
        if blocked:
            return {
                "ok": False, "code": 400,
                "error": f"该站点已有网关防御部署任务执行中 (job_id={blocked.id})",
                "job_id": blocked.id,
            }

        # payload 不落敏感密钥，只记录是否外部传入
        job = await self._create_job(
            site_id, site.domain, ACTION_TYPE,
            payload={
                "gateway_url": gateway_url,
                "fail_mode": fail_mode,
                "sdk_inject": sdk_inject,
                "has_external_key": bool(site_key),
                "has_external_gateway_site_id": bool(gateway_site_id),
                "auto_provision": auto_provision,
                "rule_ids": list(rule_ids or []),
                "defense_type": "worker" if site.platform == "shopify" else "nginx_lua",
            },
            batch_id=batch_id,
            total_steps=1,
        )

        asyncio.create_task(self._run(
            job.id, site_id, gateway_url, site_key, site_secret,
            fail_mode, sdk_inject, gateway_site_id, auto_provision, rule_ids,
        ))
        return {
            "ok": True,
            "job_id": job.id,
            "site_id": site_id,
            "domain": site.domain,
            "status": "running",
        }

    # ── Provider 归属（按平台动态判定，覆盖基类静态映射） ──

    def _provider_type(self, job: OperationJob) -> str:
        if job.action_type != ACTION_TYPE:
            return super()._provider_type(job)
        try:
            payload = json.loads(job.payload_json or "{}")
        except (ValueError, TypeError):
            return "onepanel"
        return "cloudflare" if payload.get("defense_type") == "worker" else "onepanel"

    # ── 执行 ──

    async def _run(
        self,
        job_id: int,
        site_id: int,
        gateway_url: str,
        site_key: str | None,
        site_secret: str | None,
        fail_mode: str,
        sdk_inject: bool,
        gateway_site_id: str | None,
        auto_provision: bool,
        rule_ids: list | None,
    ):
        """信号量内执行，全程不向外抛异常（后台任务异常无人接管）。"""
        sem = await _get_semaphore()
        async with sem:
            job = await OperationJob.get_or_none(id=job_id)
            if not job:
                _log.error("[gateway_defense] 任务不存在: job_id=%s", job_id)
                return
            try:
                await self._run_impl(job, site_id, gateway_url, site_key, site_secret,
                                     fail_mode, sdk_inject, gateway_site_id,
                                     auto_provision, rule_ids)
            except Exception as e:
                _log.exception("[gateway_defense] 任务执行异常: job_id=%s", job_id)
                await self._safe_fail(job, site_id, e)

    async def _run_impl(
        self,
        job: OperationJob,
        site_id: int,
        gateway_url: str,
        site_key: str | None,
        site_secret: str | None,
        fail_mode: str,
        sdk_inject: bool,
        gateway_site_id: str | None,
        auto_provision: bool,
        rule_ids: list | None,
    ):
        from app.controllers.site_pipeline import site_controller

        self._with_trace(site_id, ACTION_TYPE)

        # 二次幂等检查：防止并发提交下同站点被重复部署
        dup = await OperationJob.filter(
            resource_type=job.resource_type, resource_id=site_id,
            action_type=ACTION_TYPE, status__in=["running", "pending", "queued"],
        ).exclude(id=job.id).first()
        if dup:
            job.status = "cancelled"
            job.error_message = f"已有同站点 {ACTION_TYPE} 任务执行中 (job_id={dup.id})"
            job.result_json = json.dumps(
                {"cancel_reason": "duplicate_running_job", "existing_job_id": dup.id},
                ensure_ascii=False,
            )
            job.finished_at = datetime.now()
            await job.save()
            _log.warning("[gateway_defense] 重复提交已取消: site_id=%s existing_job=%s",
                         site_id, dup.id)
            return

        # 在任务协程内重新取 site，避免跨任务共享 ORM 实例
        site = await site_controller.get(id=site_id)
        if not site:
            job.status = "failed"
            job.error_message = f"站点不存在: id={site_id}"
            job.finished_at = datetime.now()
            await job.save()
            return

        if auto_provision:
            await self._update_step(job, "provisioning")
            site_key, site_secret, gateway_site_id = await self._auto_provision(site, rule_ids)

        service = (
            CloudflareWorkerDefenseService() if site.platform == "shopify"
            else NginxLuaDefenseService()
        )
        await self._update_step(job, "deploying")

        try:
            result = await asyncio.wait_for(
                service.deploy(
                    site,
                    gateway_url,
                    site_key=site_key,
                    site_secret=site_secret,
                    fail_mode=fail_mode,
                    sdk_inject=sdk_inject,
                    gateway_site_id=gateway_site_id,
                ),
                timeout=DEPLOY_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            error = f"部署超时（{DEPLOY_TIMEOUT_SECONDS}s），已中止"
            _log.error("[gateway_defense] %s: site_id=%s domain=%s",
                       error, site_id, site.domain)
            await self._mark_site_failed(site, error)
            await self._complete_job(job, ok=False, error=error, site=site)
            await site.save()
            return

        ok = bool(result.get("ok"))
        error = "" if ok else str(result.get("error", ""))[:500]

        # 服务层部分早退分支（校验失败/异常）不会回写站点状态，此处兜底保证一致
        if not ok and site.gateway_defense_status != "failed":
            await self._mark_site_failed(site, error)

        # 结果落库前剥离密钥类字段，task_log 仅保留步骤三元组
        await self._complete_job(
            job, ok=ok,
            result=self._sanitize_result(result),
            error=error,
            site=site,
        )
        # _complete_job 只改内存中的 pipeline_log，需显式落库
        await site.save()

    async def _auto_provision(self, site, rule_ids: list | None) -> tuple[str, str, str]:
        """自动建站 + 绑定规则，回写凭证，返回 (site_key, site_secret, gateway_site_id)。

        幂等：本地已有 gateway_site_id 时跳过建站，直接复用并重新绑定规则。
        """
        from app.services.gateway_defense.admin_client import GatewayAdminClient
        from app.settings.config import settings

        client = GatewayAdminClient()
        gateway_site_id = site.gateway_site_id
        if not gateway_site_id:
            created = await client.create_site(
                app_id=settings.GATEWAY_APP_ID,
                name=site.domain or f"site-{site.id}",
                domain=site.domain or "",
            )
            new_id = created.get("id")
            if not new_id:
                raise RuntimeError("创建网关站点失败：未返回站点ID")
            site.gateway_site_id = str(new_id)
            site.gateway_site_key = created.get("site_key") or ""
            site.gateway_site_secret = created.get("site_secret") or ""
            await site.save()
            gateway_site_id = str(new_id)

        await client.bind_rules(int(gateway_site_id), list(rule_ids or []))
        return site.gateway_site_key or "", site.gateway_site_secret or "", gateway_site_id

    # ── 失败兜底 ──

    async def _safe_fail(self, job: OperationJob, site_id: int, exc: Exception):
        """异常兜底：确保 job 与站点状态一定落盘，不留 running 僵尸任务。"""
        from app.controllers.site_pipeline import site_controller

        site = None
        try:
            site = await site_controller.get(id=site_id)
        except Exception:
            _log.warning("[gateway_defense] 兜底阶段无法获取站点: site_id=%s", site_id)
        try:
            if site:
                await self._mark_site_failed(site, self._format_error(exc))
            await self._complete_job(job, ok=False, site=site, exc=exc)
            if site:
                await site.save()
        except Exception:
            _log.exception("[gateway_defense] 兜底写库失败，强制置 failed: job_id=%s", job.id)
            job.status = "failed"
            job.error_message = str(exc)[:500]
            job.finished_at = datetime.now()
            await job.save()

    @staticmethod
    async def _mark_site_failed(site, error: str):
        """标记站点部署失败状态（不立即 save，由调用方统一落库）"""
        site.gateway_defense_status = "failed"
        site.gateway_last_error = error[:500]

    @staticmethod
    def _sanitize_result(result: dict) -> dict:
        """剔除结果中的敏感字段，压缩 task_log 体积后再落库。"""
        safe = {
            k: v for k, v in result.items()
            if k not in ("task_log", "site_key", "site_secret")
        }
        steps = result.get("task_log") or []
        if steps:
            safe["steps"] = [
                {"step": s.get("step"), "ok": s.get("ok"), "msg": s.get("msg")}
                for s in steps
            ]
        return safe


# ── 全局单例 ──

gateway_defense_task_runner = GatewayDefenseTaskRunner()

