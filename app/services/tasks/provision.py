"""
建站任务执行器 —— 1Panel WordPress 建站全流程

独立的执行器层，不依赖 API 层（site_pipeline.py）。

流程步骤（12 步，结合单脚本逻辑与生产环境 Cloudflare 需求）：
  1. create_site         - 创建 WordPress 网站
  2. apply_ssl           - 申请/绑定 SSL 证书（Cloudflare 代理必须先有 SSL）
  3. restore_db          - 恢复数据库
  4. restore_files       - 恢复模板文件
  5. rebuild_after_files - 重建容器
  6. replace_domain      - 域名替换
  7. patch_wp_config     - wp-config.php 配置
  8. inject_woo_ctx      - 注入 WooCommerce + CTX PHP 脚本
  9. rebuild_after_patch - 重建容器（脚本注入后 rebuild）
  10. fetch_woo_keys     - 获取 WooCommerce API Key
  11. health_check       - 健康检查
  12. fetch_feed_link    - 获取 Feed 链接
"""

import asyncio
import json
import logging
from datetime import datetime

from app.models.operation_job import OperationJob
from app.models.site_pipeline import Site
from app.core.exceptions import DomainAlreadyExistsError, ProviderConfigError, WordPressOperationError
from app.services.onepanel_service import (
    OnePanelAPI,
    OnePanelDatabaseRestorer,
    OnePanelFileManager,
    OnePanelSiteManager,
    OnePanelSSLManager,
    OnePanelWordPressRestorer,
)
from app.utils.provider_resolver import ProviderResolver
from .runner import TaskRunner

_log = logging.getLogger(__name__)

_PROVISION_TIMEOUT_MINUTES = 30


class ProvisionTaskRunner(TaskRunner):
    """1Panel 建站全流程执行器"""

    async def execute(self, site_id: int) -> dict:
        """建站入口：校验 → 创建任务 → 后台执行"""
        from app.controllers.site_pipeline import site_controller

        site = await site_controller.get(id=site_id)
        blocked = await _check_provision_blocked(site_id)
        if blocked:
            return {"ok": False, "code": 400, "msg": "该站点已有建站任务执行中，请勿重复触发"}

        job = await self._create_job(site_id, site.domain, "provision", total_steps=12)
        asyncio.create_task(self._run(job, site))
        return {"ok": True, "job_id": job.id, "step": "create_site", "total_steps": 12}

    async def _run(self, job: OperationJob, site):
        # 从 onepanel Provider 读取 max_concurrent
        _mc_val = await ProviderResolver.get_config('onepanel', 'max_concurrent', default='')
        max_cc = int(_mc_val) if _mc_val and _mc_val.isdigit() else 3
        async with asyncio.Semaphore(max_cc):
            await self._run_impl(job, site)

    async def _run_impl(self, job: OperationJob, site):
        self._with_trace(site.id, "provision")
        # 二次幂等检查：按 (resource_type, resource_id, action_type) 粒度，
        # 防止竞态条件下同一站点同类型任务被重复执行
        dup = await OperationJob.filter(
            resource_type=job.resource_type, resource_id=site.id,
            action_type=job.action_type, status__in=["running", "pending"],
        ).exclude(id=job.id).first()
        if dup:
            reason = f"已有同站点 {job.action_type} 任务执行中 (job_id={dup.id})"
            _log.warning("建站任务被取消（重复提交）: site_id=%s, existing_job=%s, current_job=%s",
                         site.id, dup.id, job.id)
            job.status = "cancelled"
            job.error_message = reason
            job.result_json = json.dumps({"cancel_reason": "duplicate_running_job", "existing_job_id": dup.id}, ensure_ascii=False)
            job.finished_at = datetime.now()
            await job.save()
            return
        try:
            api = OnePanelAPI()
            files = OnePanelFileManager(api)
            site_manager = OnePanelSiteManager(api, file_manager=files)
            ssl_manager = OnePanelSSLManager(api)
            db_restorer = OnePanelDatabaseRestorer(api)
            wp_restorer = OnePanelWordPressRestorer(api, files)

            # Step 1: create_site
            await self._update_step(job, "create_site")
            app_info = await self._exec(lambda: site_manager.create_wordpress_website(site.domain), timeout=300)

            app_id = int(app_info.get('app_id') or 0)
            onepanel_site_id = int(app_info.get('site_id') or 0)
            service_name = str(app_info.get('service_name') or '')
            params = app_info.get('params') or {}
            db_name = str(params.get('PANEL_DB_NAME') or params.get('DB_NAME') or '')

            for field, value in [
                ('onepanel_site_id', onepanel_site_id),
                ('onepanel_app_id', app_id),
                ('onepanel_service_name', service_name),
                ('db_name', db_name),
            ]:
                if hasattr(site, field):
                    setattr(site, field, value)
            site.onepanel_status = '创建中'
            site.pipeline_status = 'onepanel:site_created'
            await site.save()

            # Step 2: apply_ssl（Cloudflare 代理必须先申请 SSL，否则域名替换时 Cloudflare 无法连接源站）
            await self._update_step(job, "apply_ssl")
            protocol = 'http'
            if not onepanel_site_id:
                _log.warning("跳过 SSL 申请：site_id 为空")
            else:
                try:
                    protocol = await self._exec(
                        lambda: ssl_manager.apply_and_bind(onepanel_site_id, site.domain),
                        timeout=120,
                    )
                except Exception as exc:
                    _log.warning("SSL 申请异常：%s", exc)
            if protocol not in ('http', 'https'):
                protocol = 'http'

            # Step 3+4: restore_db + restore_files（无依赖，可并行）
            await self._update_step(job, "restore_db_files")
            await asyncio.gather(
                self._exec(lambda: db_restorer.restore(db_name), timeout=300),
                self._exec(lambda: wp_restorer.restore_files(service_name), timeout=300),
            )

            # Step 5: rebuild_after_files
            await self._update_step(job, "rebuild_after_files")
            await self._exec(lambda: site_manager.rebuild_app(app_id, service_name=service_name, domain=site.domain), timeout=180)

            # Step 6: replace_domain
            await self._update_step(job, "replace_domain")
            old_domain = (
                wp_restorer.old_source_domain
                or (await ProviderResolver.get_config('onepanel', 'old_source_domain', default='')).strip()
            )
            if not old_domain:
                raise ProviderConfigError("onepanel", "old_source_domain", "建站缺少旧域名配置")
            replace_token = ''
            try:
                replace_token = await self._exec(
                    lambda: wp_restorer.inject_domain_replace_script(
                        service_name=service_name, old_domain=old_domain,
                        new_domain=site.domain, target_protocol=protocol,
                    ),
                    timeout=60,
                )
                await self._exec(
                    lambda: wp_restorer.fetch_domain_replace(site.domain, replace_token),
                    timeout=120,
                )
            finally:
                if replace_token:
                    await self._exec(
                        lambda: wp_restorer.remove_domain_replace_script(service_name),
                        timeout=30,
                    )

            # Step 7+8: patch_wp_config + inject_woo_ctx（无依赖，可并行）
            await self._update_step(job, "patch_and_inject")
            _, woo_token, ctx_refresh_url = await asyncio.gather(
                self._exec(
                    lambda: wp_restorer.patch_wp_config(service_name, site.domain, protocol),
                    timeout=60,
                ),
                self._exec(lambda: wp_restorer.inject_woo_script(service_name), timeout=60),
                self._exec(
                    lambda: wp_restorer.inject_ctx_script(service_name, site.domain, protocol),
                    timeout=60,
                ),
            )

            # Step 9: rebuild_after_patch（对齐单脚本：woo/ctx 注入后 rebuild，确保容器加载新脚本）
            await self._update_step(job, "rebuild_after_patch")
            await self._exec(lambda: site_manager.rebuild_app(app_id, service_name=service_name, domain=site.domain), timeout=180)

            # Step 10: fetch_woo_keys（对齐单脚本：rebuild 后获取 WooCommerce Key）
            await self._update_step(job, "fetch_woo_keys")
            woo_ck, woo_cs = '', ''
            try:
                woo_ck, woo_cs = await self._exec(
                    lambda: wp_restorer.fetch_woo_keys(site.domain, woo_token, protocol),
                    timeout=45,
                )
            except Exception as exc:
                _log.warning("WooCommerce Key 获取失败（非阻断）：%s", exc)
            finally:
                try:
                    await self._exec(lambda: wp_restorer.remove_woo_script(service_name), timeout=15)
                except Exception:
                    pass

            # Step 11: health_check
            await self._update_step(job, "health_check")
            health_ok = await self._exec(
                lambda: wp_restorer.health_check(site.domain, protocol),
                timeout=60,
            )
            if not health_ok:
                raise WordPressOperationError("health check", domain=site.domain, detail=f"协议={protocol}")

            # Step 12: fetch_feed_link
            await self._update_step(job, "fetch_feed_link")
            feed_link = await self._exec(
                lambda: wp_restorer.fetch_last_feed_link(ctx_refresh_url),
                timeout=30,
            ) or ''
            login_url = f'{protocol}://{site.domain}/wp-admin'

            site.status = '已创建'
            site.login_url = login_url
            site.woo_ck = woo_ck
            site.woo_cs = woo_cs
            site.ctx_refresh_url = ctx_refresh_url
            site.feed_link = feed_link
            if hasattr(site, 'protocol'):
                site.protocol = protocol
            site.onepanel_status = '已创建'
            site.pipeline_status = 'onepanel:success'
            await site.save()

            await self._complete_job(job, ok=True, result={
                "service_name": service_name,
                "site_id": onepanel_site_id,
                "app_id": app_id,
                "db_name": db_name,
                "protocol": protocol,
                "login_url": login_url,
                "feed_link": feed_link,
                "ctx_refresh_url": ctx_refresh_url,
                "woo_ck": woo_ck,
                "woo_cs": woo_cs,
            }, site=site)

        except DomainAlreadyExistsError as exc:
            # 站点已在 1Panel 中存在，同步已有站点信息
            _log.info("建站跳过：域名已存在于 1Panel: %s", site.domain)
            op_site_id = exc.onepanel_site_id
            if not op_site_id:
                # 回退：异常中未携带 onepanel_site_id，再次查询
                loop = asyncio.get_event_loop()
                try:
                    op_site_id = await loop.run_in_executor(None, site_manager.get_site_id, site.domain)
                except Exception as sync_err:
                    _log.warning("同步已有站点信息失败: %s", sync_err)
            # 已完整建站的站点，只更新 onepanel_site_id 和 pipeline_status，不动其他字段
            if site.status == '已创建':
                _log.info("站点已完整建站，仅同步 1Panel ID: domain=%s", site.domain)
                update_kwargs = {'pipeline_status': 'onepanel:exists'}
                if op_site_id:
                    update_kwargs['onepanel_site_id'] = op_site_id
                    _log.info("已同步 1Panel 站点信息: domain=%s site_id=%s", site.domain, op_site_id)
                await Site.filter(id=site.id).update(**update_kwargs)
            else:
                # 首次建站但域名已存在，写入完整状态
                if op_site_id:
                    site.onepanel_site_id = op_site_id
                    _log.info("已同步 1Panel 站点信息: domain=%s site_id=%s", site.domain, op_site_id)
                site.status = '已存在'
                site.onepanel_status = '已存在'
                site.pipeline_status = 'onepanel:exists'
                await site.save()
            await self._complete_job(job, ok=False, error=str(exc), site=site)
        except Exception as exc:
            _log.exception("建站执行失败: %s", exc)
            site.status = '建站失败'
            site.onepanel_status = '创建失败'
            site.pipeline_status = 'onepanel:failed'
            await site.save()
            await self._complete_job(job, ok=False, error=str(exc), site=site, exc=exc)


async def _check_provision_blocked(site_id: int):
    """检查站点是否被阻塞的建站任务占用。超时任务自动标记失败。"""
    for status in ("running", "pending"):
        job = await OperationJob.filter(
            resource_type="site",
            resource_id=site_id,
            action_type="provision",
            status=status,
        ).first()
        if not job:
            continue
        if job.started_at:
            elapsed = (datetime.now() - job.started_at.replace(tzinfo=None)).total_seconds() / 60
            if elapsed > _PROVISION_TIMEOUT_MINUTES:
                job.status = "failed"
                job.error_message = f"建站超时（{elapsed:.0f}分钟）"
                job.finished_at = datetime.now()
                await job.save()
                _log.warning("自动清理超时建站任务: site_id=%s, job_id=%s", site_id, job.id)
                return None
        return job
    return None


provision_task_runner = ProvisionTaskRunner()
