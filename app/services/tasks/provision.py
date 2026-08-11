"""
建站任务执行器 —— 1Panel WordPress 建站全流程

独立的执行器层，不依赖 API 层（site_pipeline.py）。

流程步骤（13 步，优化后减少 rebuild 次数）：
  0. dns_check           - DNS 解析检查（确保域名已解析到服务器）
  1. create_site         - 创建 WordPress 网站
  2. apply_ssl           - 申请/绑定 SSL 证书（Cloudflare 代理必须先有 SSL）
  3. restore_and_inject  - 恢复数据库+文件，注入 woo 和 ctx 脚本（4个并行）
  4. rebuild_once        - 重建容器（一次性加载所有变更）
  5. inject_mu_plugins   - 注入 mu-plugins（rebuild 后注入，避免文件丢失）
  6. replace_domain      - 域名替换
  7. patch_wp_config     - wp-config.php 配置
  8. verify_woo_files    - 验证 WooCommerce 文件完整性（如需要则恢复+rebuild）
  9. fetch_woo_keys      - 获取 WooCommerce API Key
  10. health_check       - 健康检查
  11. fetch_feed_link    - 获取 Feed 链接
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

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

    def __init__(self):
        super().__init__()
        self._step_timings = {}  # 记录每个步骤的开始时间

    async def _start_step(self, job: OperationJob, step: str):
        """开始步骤并记录时间"""
        self._step_timings[step] = datetime.now()
        await self._update_step(job, step)
        _log.info("步骤开始: %s (site_id=%s)", step, job.resource_id)

    async def _end_step(self, job: OperationJob, step: str, site: Optional[Site] = None):
        """结束步骤并记录耗时"""
        if step in self._step_timings:
            start_time = self._step_timings[step]
            end_time = datetime.now()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
            _log.info("步骤完成: %s, 耗时: %d ms (site_id=%s)", step, duration_ms, job.resource_id)
            
            # 追加到站点日志
            if site:
                try:
                    self._append_site_log(
                        site,
                        source=f"provision:{step}",
                        data={"step": step, "duration_ms": duration_ms},
                        action=step,
                        status="success",
                        started_at=start_time,
                        completed_at=end_time,
                    )
                    await site.save(update_fields=["pipeline_log"])
                except Exception as e:
                    _log.warning("记录步骤日志失败: %s", e)
            
            del self._step_timings[step]

    async def execute(self, site_id: int) -> dict:
        """建站入口：校验 → 创建任务 → 后台执行"""
        from app.controllers.site_pipeline import site_controller

        site = await site_controller.get(id=site_id)
        blocked = await _check_provision_blocked(site_id)
        if blocked:
            return {"ok": False, "code": 400, "msg": "该站点已有建站任务执行中，请勿重复触发"}

        job = await self._create_job(site_id, site.domain, "provision", total_steps=11)
        asyncio.create_task(self._run(job, site))
        return {"ok": True, "job_id": job.id, "step": "create_site", "total_steps": 11}

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
            # Step 0: DNS 就绪检查（快速检查 Zone 状态，不轮询等待）
            await self._start_step(job, "dns_check")
            if site.server_ip:
                from app.services.cloudflare_service import CloudflareService
                
                cf_service = CloudflareService()
                
                # 获取 zone_id
                _log.info(f"站点 {site.domain} 正在获取 Cloudflare Zone ID")
                zone_id_result = await self._exec(
                    lambda: cf_service.get_or_create_zone(site.domain),
                    timeout=30
                )
                zone_id = zone_id_result[0] if zone_id_result else None
                
                if not zone_id:
                    error_msg = "无法获取 Cloudflare Zone ID，请先执行 DNS 配置"
                    _log.error(f"站点 {site.domain} (ID={site.id}) {error_msg}")
                    site.status = '建站失败'
                    site.onepanel_status = 'DNS 配置缺失'
                    site.pipeline_status = 'dns:no_zone'
                    await site.save()
                    await self._complete_job(job, ok=False, error=error_msg, site=site)
                    return
                
                # 快速检查 DNS 就绪状态（Zone active + A 记录正确）
                _log.info(f"站点 {site.domain} 正在检查 DNS 就绪状态 (zone_id={zone_id})")
                dns_result = await self._exec(
                    lambda: cf_service.check_dns_ready_for_ssl(zone_id, site.domain, site.server_ip),
                    timeout=30
                )
                
                if not dns_result.get('ok'):
                    error_msg = f"DNS 未就绪: {dns_result.get('error', '未知错误')}"
                    _log.error(f"站点 {site.domain} (ID={site.id}) {error_msg}")
                    site.status = '建站失败'
                    site.onepanel_status = 'DNS 未就绪'
                    site.pipeline_status = f"dns:{dns_result.get('zone_status', 'unknown')}"
                    await site.save()
                    await self._complete_job(job, ok=False, error=error_msg, site=site)
                    return
                
                proxied = dns_result.get('proxied', False)
                _log.info(f"站点 {site.domain} DNS 就绪: zone=active, A={site.server_ip}, proxied={proxied}")
            
            await self._end_step(job, "dns_check", site)
            
            api = OnePanelAPI()
            files = OnePanelFileManager(api)
            site_manager = OnePanelSiteManager(api, file_manager=files)
            ssl_manager = OnePanelSSLManager(api)
            db_restorer = OnePanelDatabaseRestorer(api)
            wp_restorer = OnePanelWordPressRestorer(api, files)

            # Step 1: create_site
            await self._start_step(job, "create_site")
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
            await self._end_step(job, "create_site", site)

            # Step 2: apply_ssl（Cloudflare 代理必须先申请 SSL，否则域名替换时 Cloudflare 无法连接源站）
            await self._start_step(job, "apply_ssl")
            protocol = await self._exec(
                lambda: ssl_manager.apply_and_bind(onepanel_site_id, site.domain),
                timeout=120,
            )
            await self._end_step(job, "apply_ssl", site)

            # Step 3+4: restore_db + restore_files + inject_woo_ctx（并行操作）
            # 优化：先恢复数据库和文件，注入 woo 和 ctx 脚本，mu-plugins 在 rebuild 后注入
            await self._start_step(job, "restore_and_inject")
            _, _, woo_token, ctx_refresh_url = await asyncio.gather(
                self._exec(lambda: db_restorer.restore(db_name), timeout=300),
                self._exec(lambda: wp_restorer.restore_files(service_name), timeout=300),
                self._exec(lambda: wp_restorer.inject_woo_script(service_name), timeout=120),
                self._exec(
                    lambda: wp_restorer.inject_ctx_script(service_name, site.domain, protocol),
                    timeout=120,
                ),
            )
            await self._end_step(job, "restore_and_inject", site)

            # Step 5: rebuild_once（一次性 rebuild 加载数据库和文件变更）
            await self._start_step(job, "rebuild_once")
            rebuild_result = await self._exec(lambda: site_manager.rebuild_app(app_id, service_name=service_name, domain=site.domain), timeout=180)
            
            # ⚠️ 重要：rebuild 可能会生成新的 service_name，必须更新
            if rebuild_result and isinstance(rebuild_result, dict):
                new_service_name = rebuild_result.get('service_name', service_name)
                if new_service_name != service_name:
                    _log.warning("rebuild 后 service_name 已变更: %s → %s", service_name, new_service_name)
                    service_name = new_service_name
                    site.onepanel_service_name = new_service_name
                    await site.save()
            await self._end_step(job, "rebuild_once", site)

            # Step 6: inject_mu_plugins（rebuild 后注入 mu-plugins，避免文件丢失）
            await self._start_step(job, "inject_mu_plugins")
            await self._exec(lambda: wp_restorer.inject_mu_plugins(service_name), timeout=120)
            await self._end_step(job, "inject_mu_plugins", site)

            # Step 7: replace_domain
            await self._start_step(job, "replace_domain")
            # rebuild 后 Nginx config 可能异步 reload，稍等几秒
            await asyncio.sleep(5)
            old_domain = (
                wp_restorer.old_source_domain
                or (await ProviderResolver.get_config('onepanel', 'old_source_domain', default='')).strip()
            )
            if not old_domain:
                raise ProviderConfigError("onepanel", "old_source_domain", "建站缺少旧域名配置")
            
            # 获取 WordPress 根目录（优先使用 sitePath）
            wp_root = await self._exec(
                lambda: site_manager.get_wp_root(
                    service_name=service_name,
                    site_id=onepanel_site_id,
                    domain=site.domain
                ),
                timeout=30,
            )
            
            replace_token = ''
            try:
                replace_token = await self._exec(
                    lambda: wp_restorer.inject_domain_replace_script(
                        service_name=service_name, old_domain=old_domain,
                        new_domain=site.domain, target_protocol=protocol,
                        target_dir=wp_root or '',
                    ),
                    timeout=60,
                )
                replace_result = await self._exec(
                    lambda: wp_restorer.fetch_domain_replace(site.domain, replace_token),
                    timeout=120,
                )
                # 校验替换结果：静默成功（0 行变更）意味着旧域名与数据库不匹配
                if isinstance(replace_result, dict):
                    changed_rows = replace_result.get('changed_rows', 0)
                    changed_cells = replace_result.get('changed_cells', 0)
                    failed_rows = replace_result.get('failed_rows', 0)
                    failed_tables = replace_result.get('failed_tables', 0)
                    error_tables = replace_result.get('error_tables', [])
                    if changed_rows == 0 and changed_cells == 0:
                        _log.warning(
                            "站点 %s 域名替换未检测到任何变更（旧域名 %s → 新域名 %s），请确认 old_source_domain 配置正确",
                            site.domain, old_domain, site.domain,
                        )
                    else:
                        _log.info("站点 %s 域名替换完成: %s 行 %s 单元格", site.domain, changed_rows, changed_cells)
                    if failed_rows > 0 or failed_tables > 0:
                        _log.warning(
                            "站点 %s 域名替换部分失败: failed_rows=%s, failed_tables=%s, error_tables=%s",
                            site.domain, failed_rows, failed_tables, error_tables,
                        )
                else:
                    _log.warning("站点 %s 域名替换返回异常格式: %s", site.domain, replace_result)
            finally:
                if replace_token:
                    self._schedule_cleanup(lambda: wp_restorer.remove_domain_replace_script(service_name))
            await self._end_step(job, "replace_domain", site)

            # Step 8: patch_wp_config（域名替换后更新配置）
            await self._start_step(job, "patch_wp_config")
            await self._exec(
                lambda: wp_restorer.patch_wp_config(service_name, site.domain, protocol),
                timeout=120,
            )
            await self._end_step(job, "patch_wp_config", site)

            # Step 9: verify_woo_files（验证 WooCommerce 插件文件完整性）
            # 注意：mu-plugins 已在 rebuild 后注入，此处只验证 WooCommerce 核心文件
            await self._start_step(job, "verify_woo_files")
            needs_restore = await self._exec(
                lambda: wp_restorer.verify_and_restore_files(
                    service_name,
                    required_files=['wp-content/plugins/woocommerce/woocommerce.php']
                ),
                timeout=330,  # 包含可能的文件恢复时间
            )
            if needs_restore:
                _log.warning("rebuild 后 WooCommerce 文件丢失已自动恢复，需要再次 rebuild")
                # 恢复后需要再次 rebuild
                rebuild_result2 = await self._exec(
                    lambda: site_manager.rebuild_app(app_id, service_name=service_name, domain=site.domain),
                    timeout=180
                )
                # 更新 service_name（如果变更）
                if rebuild_result2 and isinstance(rebuild_result2, dict):
                    new_service_name = rebuild_result2.get('service_name', service_name)
                    if new_service_name != service_name:
                        _log.warning("第二次 rebuild 后 service_name 已变更: %s → %s", service_name, new_service_name)
                        service_name = new_service_name
                        site.onepanel_service_name = new_service_name
                        await site.save()
                # 第二次 rebuild 后，需要重新注入 mu-plugins
                _log.info("第二次 rebuild 后，重新注入 mu-plugins")
                await self._exec(lambda: wp_restorer.inject_mu_plugins(service_name), timeout=120)
            await self._end_step(job, "verify_woo_files", site)
            
            # Step 10: fetch_woo_keys
            await self._start_step(job, "fetch_woo_keys")
            woo_ck, woo_cs = await self._exec(
                lambda: wp_restorer.fetch_woo_keys(site.domain, woo_token, protocol),
                timeout=45,
            )
            self._schedule_cleanup(lambda: wp_restorer.remove_woo_script(service_name))
            await self._end_step(job, "fetch_woo_keys", site)

            # Step 11: health_check
            await self._start_step(job, "health_check")
            health_ok = await self._exec(
                lambda: wp_restorer.health_check(site.domain, protocol),
                timeout=60,
            )
            if not health_ok:
                raise WordPressOperationError("health check", domain=site.domain, detail=f"协议={protocol}")
            await self._end_step(job, "health_check", site)

            # Step 12: fetch_feed_link
            await self._start_step(job, "fetch_feed_link")
            feed_link = await self._exec(
                lambda: wp_restorer.fetch_last_feed_link(ctx_refresh_url),
                timeout=30,
            ) or ''
            login_url = f'{protocol}://{site.domain}/wp-admin'
            await self._end_step(job, "fetch_feed_link", site)

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
