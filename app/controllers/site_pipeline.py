import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional

import httpx
from tortoise.expressions import Q

from app.core.crud import CRUDBase
from app.controllers.gmail_account import gmail_account_controller
from app.models.admin import Dept, User
from app.models.config_provider import ConfigProvider, ProviderConfigItem, ResourceProviderBinding
from app.models.gmail_account import GmailAccount
from app.models.operation_job import OperationJob
from app.models.site_pipeline import HubStudioJob, Site
from app.schemas.site_pipeline import HubStudioJobCreate, SiteCreate, SiteUpdate
from app.services.cloudflare_redirect_service import CloudflareRedirectService
from app.services.cloudflare_service import CloudflareService
from app.services.hubstudio_service import HubStudioService
from app.services.onepanel_service import (
    OnePanelAPI, OnePanelDatabaseRestorer, OnePanelFileManager,
    OnePanelSiteManager, OnePanelSSLManager, OnePanelWordPressRestorer,
)
from app.services.providers.dynadot_service import DynadotService
from app.services.tasks.runner import task_runner
from app.services.woo_import_service import WooImportService
from app.services.importers import get_importer
from app.utils.config_reader import get_config
from app.utils.provider_resolver import ProviderResolver

_log = logging.getLogger(__name__)

_PROVISION_TIMEOUT_MINUTES = 30


def _load_max_concurrent() -> int:
    try:
        val = ProviderResolver.sync_get_config('onepanel', 'max_concurrent', '')
        if val and val.isdigit():
            return int(val)
    except Exception:
        pass
    return 3


# ── Services ──
cloudflare_service = CloudflareService()
cloudflare_redirect_service = CloudflareRedirectService()
hubstudio_service = HubStudioService()
dynadot_service = DynadotService()

onepanel_api = OnePanelAPI()
onepanel_files = OnePanelFileManager(onepanel_api)
onepanel_site_manager = OnePanelSiteManager(onepanel_api)
onepanel_ssl_manager = OnePanelSSLManager(onepanel_api)
onepanel_db_restorer = OnePanelDatabaseRestorer(onepanel_api)
onepanel_wp_restorer = OnePanelWordPressRestorer(onepanel_api, onepanel_files)
woo_import_service = WooImportService()

_provision_semaphore = asyncio.Semaphore(_load_max_concurrent())
_import_semaphore = asyncio.Semaphore(_load_max_concurrent())


# ── 辅助工具函数 ──
def _build_onepanel_url(cfgs: dict) -> str:
    url = str(cfgs.get('url', cfgs.get('OP_URL', ''))).strip()
    if not url:
        return ''
    if not url.startswith('http'):
        url = 'https://' + url
    return url.rstrip('/') + '/api/v2'


def _make_onepanel_headers(api_key: str) -> dict:
    ts = str(int(time.time()))
    token = hashlib.md5(f'1panel{api_key}{ts}'.encode('utf-8')).hexdigest()
    return {
        '1Panel-Token': token,
        '1Panel-Timestamp': ts,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


def _onepanel_request(method: str, url: str, payload: dict, headers: dict):
    """同步 HTTP 请求（在线程池中调用）"""
    resp = httpx.request(method=method, url=url, headers=headers, json=payload,
                         timeout=httpx.Timeout(30))
    try:
        data = resp.json()
    except Exception:
        return False, f"HTTP {resp.status_code}: {resp.text[:500]}"
    if data.get('code') == 200:
        return True, data.get('data')
    return False, f"code={data.get('code')} message={data.get('message')}"


def _run_dns_sync(site):
    """在线程池中同步执行 DNS + NS 操作（避免阻塞事件循环）"""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        if site.platform == 'shopify':
            return loop.run_until_complete(cloudflare_service.provision_shopify_dns(site))
        return loop.run_until_complete(cloudflare_service.provision_dns(site))
    finally:
        loop.close()


# ── CRUD ──
class SiteController(CRUDBase[Site, SiteCreate, SiteUpdate]):
    def __init__(self):
        super().__init__(model=Site)

    async def get_by_domain(self, domain: str) -> Optional[Site]:
        return await self.model.filter(domain=domain).first()


class HubStudioJobController(CRUDBase[HubStudioJob, HubStudioJobCreate, HubStudioJobCreate]):
    def __init__(self):
        super().__init__(model=HubStudioJob)

    async def claim_next_pending_job(self, worker_name: str) -> Optional[HubStudioJob]:
        job = await self.model.filter(status='pending').order_by('id').first()
        if not job:
            return None
        job.status = 'running'
        job.worker_name = worker_name
        await job.save()
        return job

    async def report_job(self, job_id: int, status: str, result_json: str,
                         error_message: str, worker_name: str) -> Optional[HubStudioJob]:
        job = await self.get(id=job_id)
        if not job:
            return None
        job.status = status
        job.result_json = result_json
        job.error_message = error_message
        job.worker_name = worker_name or job.worker_name
        await job.save()
        site = await Site.filter(id=job.site_id).first()
        if site:
            site.hub_status = status
            site.pipeline_status = f'hubstudio:{status}'
            old_log = site.pipeline_log or ''
            from app.utils.config_reader import get_provider_info
            site.pipeline_log = (old_log + '\n' + json.dumps({
                'job_id': job.id,
                'job_type': job.job_type,
                'status': status,
                'worker_name': worker_name,
                'error_message': error_message,
                'result_json': result_json,
                'provider': get_provider_info("hubstudio"),
            }, ensure_ascii=False)).strip()
            if status == 'success':
                try:
                    result = json.loads(result_json or '{}')
                    env_id = result.get('env_id') or result.get('containerCode') or result.get('id') or result.get('code')
                    if env_id:
                        site.hub_env_id = str(env_id)
                except Exception:
                    pass
            await site.save()
        return job


site_controller = SiteController()
hubstudio_job_controller = HubStudioJobController()


# ══════════════════════════════════════════════════════════════════════════
#  SitePipeline 业务逻辑控制器
# ══════════════════════════════════════════════════════════════════════════

class SitePipelineController:
    """站点流水线业务逻辑控制器：站点 CRUD 增强 / 批量操作 / 建站 / DNS 等"""

    # ── OperationJob 辅助 ──
    async def _create_job(self, site_id: int, domain: str, action_type: str,
                          payload: dict = None, batch_id: str = "", total_steps: int = 1) -> OperationJob:
        return await task_runner._create_job(site_id, domain, action_type, payload, batch_id, total_steps)

    async def _update_job_step(self, job: OperationJob, step: str):
        await task_runner._update_step(job, step)

    async def _complete_job(self, job: OperationJob, ok: bool, result: dict = None, error: str = "",
                            provider_type: str = "", site=None, action_label: str = ""):
        await task_runner._complete_job(job=job, ok=ok, result=result, error=error, site=site)

    def _append_site_log(self, site, source: str, data: dict, provider_type: str = "",
                         action: str = "", status: str = "success", started_at: datetime = None,
                         completed_at: datetime = None, error: str = ""):
        task_runner._append_site_log(
            site=site, source=source, data=data,
            provider_type=provider_type, action=action,
            status=status, started_at=started_at,
            completed_at=completed_at, error=error,
        )

    # ── 站点 CRUD (增强) ──
    async def list_sites_with_enrichment(
        self, page: int, page_size: int,
        domain: str = '', dept_id: int = None, assign_to: int = None,
        current_user=None,
    ) -> dict:
        """查询站点列表并附加部门/用户/Gmail 信息"""
        from app.core.data_permission import DataPermissionFilter
        q = Q()
        if domain:
            q &= Q(domain__contains=domain)
        if current_user:
            data_filter = await DataPermissionFilter.get_filter_condition(
                current_user, None, resource="site", owner_field="create_by", dept_field="dept_id",
            )
            q &= data_filter
        if dept_id is not None:
            q &= Q(dept_id=dept_id)
        if assign_to is not None:
            q &= Q(create_by=assign_to)
        total, objs = await site_controller.list(page=page, page_size=page_size, search=q, order=['-id'])

        dept_ids = {obj.dept_id for obj in objs if obj.dept_id}
        user_ids = {obj.create_by for obj in objs if obj.create_by}
        site_ids_list = [obj.id for obj in objs]
        dept_map, user_map, gmail_map = {}, {}, {}
        if dept_ids:
            depts = await Dept.filter(id__in=list(dept_ids)).all()
            dept_map = {d.id: d.name for d in depts}
        if user_ids:
            users = await User.filter(id__in=list(user_ids)).all()
            user_map = {u.id: u.username for u in users}
        gmails = await GmailAccount.filter(assigned_site_id__in=site_ids_list).all()
        gmail_map = {g.assigned_site_id: g for g in gmails}
        data = []
        for obj in objs:
            d = await obj.to_dict()
            gmail = gmail_map.get(obj.id)
            d['gmail_username'] = gmail.username if gmail else ''
            d['gmail_status'] = gmail.status if gmail else ''
            d['dept_name'] = dept_map.get(obj.dept_id, '')
            d['assign_to_name'] = user_map.get(obj.create_by, '')
            data.append(d)
        return {"total": total, "data": data, "page": page, "page_size": page_size}

    async def get_site_detail(self, site_id: int) -> dict:
        """获取站点详情，附带部门/用户/Gmail/Provider 绑定信息"""
        obj = await site_controller.get(id=site_id)
        site_dict = await obj.to_dict()
        if obj.dept_id:
            dept = await Dept.get_or_none(id=obj.dept_id)
            site_dict['dept_name'] = dept.name if dept else ''
        else:
            site_dict['dept_name'] = ''
        if obj.create_by:
            owner = await User.get_or_none(id=obj.create_by)
            site_dict['assign_to_name'] = owner.username if owner else ''
        else:
            site_dict['assign_to_name'] = ''
        gmail = await GmailAccount.filter(assigned_site_id=obj.id).first()

        CORE_TYPES = ['cloudflare', 'dynadot', 'onepanel', 'hubstudio'] if obj.platform != 'shopify' \
                     else ['cloudflare', 'dynadot', 'hubstudio', 'shopify']

        # 批量查询：一次获取所有 bindings + 所有 provider 信息
        bindings = await ResourceProviderBinding.filter(
            resource_type='site', resource_id=site_id, provider_type__in=CORE_TYPES
        ).all()
        binding_map = {b.provider_type: b for b in bindings}
        bound_provider_ids = [b.provider_id for b in bindings]
        default_providers = await ConfigProvider.filter(
            provider_type__in=CORE_TYPES, is_default=True, status='active'
        ).all()
        default_map = {}
        for dp in default_providers:
            if dp.provider_type not in default_map:
                default_map[dp.provider_type] = dp
        # 补充非默认的 active provider
        for ptype in CORE_TYPES:
            if ptype not in default_map:
                dp = await ConfigProvider.filter(provider_type=ptype, status='active').order_by('-priority', 'id').first()
                if dp:
                    default_map[ptype] = dp

        bound_pids = set(bound_provider_ids)
        all_pids = bound_pids | {default_map[ptype].id for ptype in CORE_TYPES if ptype in default_map}
        provider_records = await ConfigProvider.filter(id__in=list(all_pids)).all() if all_pids else []
        provider_map = {p.id: p for p in provider_records}

        providers = {}
        for ptype in CORE_TYPES:
            binding = binding_map.get(ptype)
            if binding:
                p = provider_map.get(binding.provider_id)
                providers[ptype] = {
                    'provider_id': binding.provider_id,
                    'provider_name': p.provider_name if p else f'#{binding.provider_id}',
                    'is_default': p.is_default if p else False,
                    'bound': True,
                }
            else:
                dp = default_map.get(ptype)
                providers[ptype] = {
                    'provider_id': dp.id if dp else None,
                    'provider_name': dp.provider_name if dp else '无默认',
                    'is_default': True,
                    'bound': False,
                }
        return {
            'site': site_dict,
            'gmail': await gmail.to_dict() if gmail else None,
            'providers': providers,
        }

    async def create_site_with_permission(self, site_in: SiteCreate, current_user) -> dict:
        """创建站点并设置数据权限字段"""
        existed = await site_controller.get_by_domain(site_in.domain)
        if existed:
            await self._sync_onepanel_status(existed)
            return {"ok": False, "error": "域名已存在", "code": 400}
        site = await site_controller.create(site_in)
        if site_in.assign_to:
            assigned_user = await User.get_or_none(id=site_in.assign_to)
            site.create_by = site_in.assign_to
            site.dept_id = assigned_user.dept_id if assigned_user else current_user.dept_id
        else:
            site.create_by = current_user.id
            site.dept_id = site_in.dept_id if site_in.dept_id is not None else current_user.dept_id
        await site.save()
        return {"ok": True, "data": {"id": site.id}}

    # ── 1Panel 同步 ──
    async def _sync_onepanel_status(self, site):
        """同步 1Panel 中的站点状态到本地记录"""
        if not site.domain:
            return
        loop = asyncio.get_event_loop()
        try:
            ok, data = await loop.run_in_executor(
                None, lambda: onepanel_api.post(
                    '/websites/search',
                    {'page': 1, 'pageSize': 200, 'OrderBy': 'created_at', 'Order': 'descending'}
                )
            )
            if not ok or not isinstance(data, dict):
                return
            items = data.get('items') or []
            op_site_id = None
            for item in items:
                if item.get('primaryDomain') == site.domain:
                    op_site_id = int(item['id'])
                    break
            if op_site_id:
                site.onepanel_site_id = op_site_id
                if site.onepanel_status in ('', '待处理', 'site_created'):
                    site.onepanel_status = 'exists_in_panel'
                await site.save()
        except Exception as e:
            _log.warning("同步 onepanel_status 失败: domain=%s error=%s", site.domain, e)

    # ── 删除 ──
    async def delete_site(self, site_id: int) -> dict:
        """软删除站点并异步删除 1Panel 网站"""
        site = await site_controller.get(id=site_id)
        info = None
        if site:
            info = {"id": site.id, "domain": site.domain, "onepanel_status": site.onepanel_status}
        await site_controller.soft_remove(id=site_id)
        await gmail_account_controller.soft_delete_by_site(site_id)
        if info:
            asyncio.create_task(self._delete_from_1panel_by_info(info))
        return {"ok": True, "info": info}

    async def _delete_from_1panel_by_info(self, info: dict) -> dict:
        """通过域名和状态信息执行 1Panel 删除"""
        domain = info["domain"]
        if not domain:
            return {"status": "skip", "detail": "域名为空"}

        candidates = []
        seen_ids = set()
        binding = await ResourceProviderBinding.filter(
            resource_type='site', resource_id=info["id"],
            provider_type='onepanel', bind_type='preferred'
        ).first()
        if binding:
            p = await ConfigProvider.filter(id=binding.provider_id, status='active').first()
            if p:
                candidates.append(p)
                seen_ids.add(p.id)
        default_p = await ConfigProvider.get_default('onepanel')
        if default_p and default_p.id not in seen_ids:
            candidates.append(default_p)
        if not candidates:
            return {"status": "skip", "detail": "无可用 onepanel provider"}
        for provider in candidates:
            result = await self._try_delete_on_provider_by_domain(domain, provider)
            if result["status"] in ("deleted", "error"):
                return result
        return {"status": "not_found", "detail": "所有 provider 上均未找到"}

    async def _try_delete_on_provider_by_domain(self, domain: str, provider) -> dict:
        cfgs = await ProviderConfigItem.get_map(provider.id)
        base_url = _build_onepanel_url(cfgs)
        api_key = str(cfgs.get('api_key', cfgs.get('OP_API_KEY', '')))
        if not base_url or not api_key:
            return {"status": "not_found", "detail": f"provider={provider.provider_name} url/api_key 未配置"}
        headers = _make_onepanel_headers(api_key)
        loop = asyncio.get_event_loop()
        try:
            ok, data = await loop.run_in_executor(
                None,
                lambda: _onepanel_request('POST', base_url + '/websites/search',
                                          {'page': 1, 'pageSize': 200, 'OrderBy': 'created_at', 'Order': 'descending'},
                                          headers),
            )
            op_site_id = None
            if ok and isinstance(data, dict):
                for item in (data.get('items') or []):
                    if item.get('primaryDomain') == domain:
                        op_site_id = int(item['id'])
                        break
            if not op_site_id:
                return {"status": "not_found", "detail": f"provider={provider.provider_name} 上未找到"}
        except Exception as e:
            return {"status": "not_found", "detail": f"provider={provider.provider_name} 查询失败: {e}"}
        del_payload = {'id': op_site_id, 'deleteApp': True, 'deleteBackup': True, 'deleteDB': True, 'forceDelete': True}
        try:
            ok, msg = await loop.run_in_executor(
                None,
                lambda: _onepanel_request('POST', base_url + '/websites/del', del_payload, headers),
            )
            if ok:
                return {"status": "deleted", "detail": f"provider={provider.provider_name} site_id={op_site_id}"}
            return {"status": "error", "detail": f"provider={provider.provider_name} site_id={op_site_id} {msg}"}
        except Exception as e:
            return {"status": "error", "detail": f"provider={provider.provider_name} site_id={op_site_id} {e}"}

    # ── 批量创建 / 删除 ──
    async def batch_create_sites_bg(self, items: list, job_id: int, user_id: int = None, dept_id: int = None):
        results = []
        for item in items:
            try:
                existed = await site_controller.get_by_domain(item.domain)
                if existed:
                    await self._sync_onepanel_status(existed)
                    results.append({"domain": item.domain, "ok": False, "error": "already exists"})
                    continue
                site = await site_controller.create(item)
                item_assign_to = getattr(item, 'assign_to', None)
                if item_assign_to:
                    assigned_user = await User.get_or_none(id=item_assign_to)
                    site.create_by = item_assign_to
                    site.dept_id = assigned_user.dept_id if assigned_user else dept_id
                else:
                    site.create_by = user_id if user_id else 0
                    item_dept_id = getattr(item, 'dept_id', None)
                    site.dept_id = item_dept_id if item_dept_id is not None else dept_id
                await site.save()
                results.append({"domain": item.domain, "ok": True, "error": ""})
            except Exception as e:
                results.append({"domain": item.domain, "ok": False, "error": str(e)})
        success = sum(1 for r in results if r["ok"])
        fail = len(results) - success
        job = await OperationJob.get_or_none(id=job_id)
        if job:
            job.status = "success" if fail == 0 else "failed"
            job.result_json = json.dumps(
                {"results": results, "total": len(results), "success": success, "fail": fail},
                ensure_ascii=False,
            )
            job.finished_at = datetime.now()
            await job.save()

    async def batch_delete_sites(self, ids: List[int]) -> dict:
        """批量删除站点并异步删除 1Panel"""
        count = 0
        gmail_deleted = 0
        db_failed = 0
        sites_info = []
        for sid in ids:
            try:
                site = await site_controller.get(id=sid)
                if not site:
                    continue
                await site_controller.soft_remove(id=sid)
                gmail_deleted += await gmail_account_controller.soft_delete_by_site(sid)
                count += 1
                sites_info.append({"id": site.id, "domain": site.domain, "onepanel_status": site.onepanel_status})
            except Exception as e:
                _log.warning("删除站点失败 id=%s: %s", sid, e)
                db_failed += 1
        if not sites_info:
            return {"ok": True, "data": {"deleted": count, "db_failed": db_failed, "pending_1panel_delete": 0}}

        job = await self._create_job(0, f"batch-delete-{int(time.time())}", "batch_delete",
                                     batch_id=f"delete-{int(time.time())}", total_steps=len(sites_info))
        job.result_json = json.dumps({
            "deleted_from_db": count, "db_failed": db_failed, "gmail_deleted": gmail_deleted, "results": [],
        })
        await job.save()

        async def _bg_delete():
            del_ok, del_fail, del_skip = 0, 0, 0
            results = []
            for info in sites_info:
                try:
                    r = await self._delete_from_1panel_by_info(info)
                    results.append({"domain": info["domain"], "status": r["status"], "detail": r.get("detail", "")})
                    if r["status"] == "deleted":
                        del_ok += 1
                    elif r["status"] == "error":
                        del_fail += 1
                    else:
                        del_skip += 1
                except Exception as e:
                    results.append({"domain": info["domain"], "status": "exception", "detail": str(e)})
                    del_fail += 1
            job.status = "success" if del_fail == 0 else "failed"
            job.result_json = json.dumps({
                "deleted_from_db": count, "db_failed": db_failed, "gmail_deleted": gmail_deleted,
                "1panel_deleted": del_ok, "1panel_failed": del_fail, "1panel_skipped": del_skip, "results": results,
            }, ensure_ascii=False)
            job.finished_at = datetime.now()
            await job.save()

        asyncio.create_task(_bg_delete())
        return {"ok": True, "data": {
            "deleted": count, "db_failed": db_failed, "gmail_deleted": gmail_deleted,
            "pending_1panel_delete": len(sites_info), "job_id": job.id,
        }}

    # ── 批量分配 ──
    async def batch_assign_sites(self, site_ids: List[int], dept_id: int = None, assign_to: int = None) -> dict:
        updated = 0
        for sid in site_ids:
            site = await site_controller.get(id=sid)
            if not site:
                continue
            if assign_to:
                assigned_user = await User.get_or_none(id=assign_to)
                site.create_by = assign_to
                site.dept_id = assigned_user.dept_id if assigned_user else site.dept_id
            elif dept_id is not None:
                site.dept_id = dept_id
            else:
                continue
            await site.save()
            updated += 1
        return {"updated": updated, "total": len(site_ids)}

    # ── 建站 ──
    async def _check_provision_blocked(self, site_id: int) -> Optional[OperationJob]:
        for status in ("running", "pending"):
            job = await OperationJob.filter(
                resource_type="site", resource_id=site_id,
                action_type="provision", status=status,
            ).first()
            if not job:
                continue
            if job.started_at:
                elapsed = datetime.now().astimezone() - job.started_at.astimezone()
                if elapsed > timedelta(minutes=_PROVISION_TIMEOUT_MINUTES):
                    job.status = "failed"
                    job.error_message = f"任务超时自动取消（{status} 超过 {_PROVISION_TIMEOUT_MINUTES} 分钟）"
                    job.finished_at = datetime.now()
                    await job.save()
                    continue
            return job
        return None

    async def provision_site(self, site_id: int) -> dict:
        site = await site_controller.get(id=site_id)
        if site.platform == 'shopify':
            return {"ok": False, "error": "Shopify 站点无需建站，请手动填写 Token", "code": 400}
        blocked = await self._check_provision_blocked(site_id)
        if blocked:
            return {"ok": False, "error": "该站点已有建站任务执行中", "code": 400}
        job = await self._create_job(site_id, site.domain, "provision", total_steps=10)
        asyncio.create_task(self._run_provision_bg(job, site))
        return {"ok": True, "data": {"job_id": job.id, "step": "create_site", "total_steps": 10}}

    async def _run_provision_bg(self, job: OperationJob, site):
        async with _provision_semaphore:
            from app.services.tasks.provision import provision_task_runner
            await provision_task_runner._run_impl(job, site)

    async def batch_provision(self, site_ids: List[int], batch_id: str = "") -> dict:
        results = []
        for site_id in site_ids:
            site = await site_controller.get(id=site_id)
            if not site:
                results.append({"site_id": site_id, "ok": False, "error": "site not found"})
                continue
            if site.platform == 'shopify':
                results.append({"site_id": site_id, "domain": site.domain, "ok": False,
                              "error": "Shopify 站点无需建站"})
                continue
            blocked = await self._check_provision_blocked(site_id)
            if blocked:
                results.append({"site_id": site_id, "domain": site.domain, "ok": False, "error": "已有建站任务执行中"})
                continue
            job = await self._create_job(site_id, site.domain, "provision", batch_id=batch_id, total_steps=10)
            asyncio.create_task(self._run_provision_bg(job, site))
            results.append({"site_id": site_id, "domain": site.domain, "ok": True, "job_id": job.id, "status": "running"})
        return {"ok": True, "data": {"batch_id": batch_id, "results": results, "total": len(results),
                "success": sum(1 for r in results if r["ok"]), "fail": sum(1 for r in results if not r["ok"])}}

    # ── DNS ──
    async def provision_dns(self, site_id: int) -> dict:
        cf_token = get_config("CF_API_TOKEN")
        cf_account = get_config("CF_ACCOUNT_ID")
        if not cf_token or not cf_account:
            return {"ok": False, "error": "Cloudflare 未配置：请在 系统管理 → 提供商管理 中配置 Cloudflare API Token 和 Account ID", "code": 400}
        site = await site_controller.get(id=site_id)
        # Shopify 站点无需 server_ip
        if site.platform != 'shopify' and not site.server_ip:
            return {"ok": False, "error": "site server_ip is empty", "code": 400}
        job = await self._create_job(site_id, site.domain, "dns")
        asyncio.create_task(self._run_dns_single_bg(job, site))
        return {"ok": True, "data": {"job_id": job.id, "domain": site.domain, "status": "running"}}

    async def _run_dns_single_bg(self, job: OperationJob, site):
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _run_dns_sync, site)
            await self._complete_job(job, ok=True, result=result)
        except Exception as e:
            await self._complete_job(job, ok=False, error=str(e))

    async def batch_dns(self, site_ids: List[int]) -> dict:
        batch_id = f"dns-{int(time.time())}"
        valid_sites = []
        invalid = []
        for sid in site_ids:
            try:
                site = await site_controller.get(id=sid)
                if not site or (site.platform != 'shopify' and not site.server_ip):
                    invalid.append({"site_id": sid, "error": "no server_ip"})
                else:
                    valid_sites.append(site)
            except Exception as e:
                invalid.append({"site_id": sid, "error": str(e)})
        if not valid_sites:
            return {"ok": True, "data": {"batch_id": batch_id, "total": len(invalid), "results": invalid}}
        job = await self._create_job(0, f"batch-dns-{batch_id}", "batch_dns",
                                     batch_id=batch_id, total_steps=len(valid_sites))
        job.result_json = json.dumps({"total": len(valid_sites), "invalid": len(invalid), "results": []})
        await job.save()

        async def _bg_dns():
            sem = asyncio.Semaphore(3)
            results = []
            async def _run_one(site):
                async with sem:
                    try:
                        loop = asyncio.get_event_loop()
                        r = await loop.run_in_executor(None, _run_dns_sync, site)
                        results.append({"site_id": site.id, "domain": site.domain, "ok": True, "result": r})
                    except Exception as e:
                        results.append({"site_id": site.id, "domain": site.domain, "ok": False, "error": str(e)})
            await asyncio.gather(*[_run_one(s) for s in valid_sites])
            ok_count = sum(1 for r in results if r["ok"])
            fail_count = sum(1 for r in results if not r["ok"])
            job.status = "success" if fail_count == 0 else "failed"
            job.result_json = json.dumps(
                {"total": len(valid_sites), "dns_ok": ok_count, "dns_fail": fail_count, "results": results, "invalid": invalid},
                ensure_ascii=False,
            )
            job.finished_at = datetime.now()
            await job.save()
        asyncio.create_task(_bg_dns())
        return {"ok": True, "data": {"batch_id": batch_id, "job_id": job.id, "total": len(valid_sites), "invalid": len(invalid)}}

    # ── Dynadot NS ──
    async def set_dynadot_ns(self, site_id: int, ns_list: List[str] = None) -> dict:
        site = await site_controller.get(id=site_id)
        job = await self._create_job(site_id, site.domain, "dynadot_ns")
        try:
            if not ns_list:
                ns_list = ["a.ns.cloudflare.com", "b.ns.cloudflare.com"]
            result = dynadot_service.set_nameserver(site.domain, ns_list)
            ok = result.get("success", False)
            await self._complete_job(job, ok=ok, result=result, error=result.get("error", ""))
            self._append_site_log(site, "dynadot_ns", {"success": ok}, "dynadot")
            site.dynadot_status = "ns_updated" if ok else f"ns_failed:{str(result.get('error',''))[:80]}"
            await site.save()
            if ok:
                return {"ok": True, "data": {"domain": site.domain, "ns_list": ns_list, "raw": result}}
            return {"ok": False, "error": result.get("error", "Unknown error"), "code": 500}
        except Exception as e:
            await self._complete_job(job, ok=False, error=str(e))
            site.dynadot_status = f"ns_failed:{str(e)[:80]}"
            await site.save()
            return {"ok": False, "error": str(e), "code": 500}

    async def batch_dynadot_ns(self, site_ids: List[int], ns_list: List[str] = None) -> dict:
        batch_id = f"dynadot-ns-{int(time.time())}"
        results = []
        if not ns_list:
            ns_list = ["a.ns.cloudflare.com", "b.ns.cloudflare.com"]
        for site_id in site_ids:
            site = await site_controller.get(id=site_id)
            if not site:
                results.append({"site_id": site_id, "ok": False, "error": "site not found"})
                continue
            job = await self._create_job(site_id, site.domain, "dynadot_ns", batch_id=batch_id)
            asyncio.create_task(self._run_dynadot_ns_bg(job, site, ns_list))
            results.append({"site_id": site_id, "domain": site.domain, "ok": True, "job_id": job.id, "status": "running"})
        return {"ok": True, "data": {"batch_id": batch_id, "results": results, "total": len(results),
                "success": sum(1 for r in results if r["ok"]), "fail": sum(1 for r in results if not r["ok"])}}

    async def _run_dynadot_ns_bg(self, job: OperationJob, site, ns_list: list):
        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, dynadot_service.set_nameserver, site.domain, ns_list),
                timeout=120,
            )
            ok = result.get("success", False)
            await self._complete_job(job, ok=ok, result=result, error=result.get("error", ""))
            self._append_site_log(site, "dynadot_ns", {"success": ok, "raw": str(result.get("raw", ""))[:200]}, "dynadot")
            site.dynadot_status = "ns_updated" if ok else f"ns_failed:{str(result.get('error',''))[:80]}"
            await site.save()
        except Exception as e:
            await self._complete_job(job, ok=False, error=str(e))
            site.dynadot_status = f"ns_failed:{str(e)[:80]}"
            await site.save()

    # ── Redirect ──
    async def provision_redirect(self, site_id: int, target_url: str) -> dict:
        site = await site_controller.get(id=site_id)
        job = await self._create_job(site_id, site.domain, "redirect")
        try:
            result = await cloudflare_redirect_service.setup_redirect(site, target_url)
            await self._complete_job(job, ok=True, result=result)
            return {"ok": True, "data": result}
        except Exception as e:
            await self._complete_job(job, ok=False, error=str(e))
            return {"ok": False, "error": str(e), "code": 500}

    async def batch_redirect(self, site_ids: List[int], target_url: str) -> dict:
        batch_id = f"redirect-{int(time.time())}"
        results = []
        for site_id in site_ids:
            site = await site_controller.get(id=site_id)
            if not site:
                results.append({"site_id": site_id, "ok": False, "error": "site not found"})
                continue
            job = await self._create_job(site_id, site.domain, "redirect", batch_id=batch_id)
            asyncio.create_task(self._run_redirect_bg(job, site, target_url))
            results.append({"site_id": site_id, "domain": site.domain, "ok": True, "job_id": job.id, "status": "running"})
        return {"ok": True, "data": {"batch_id": batch_id, "results": results, "total": len(results),
                "success": sum(1 for r in results if r["ok"]), "fail": sum(1 for r in results if not r["ok"])}}

    async def _run_redirect_bg(self, job: OperationJob, site, target_url: str):
        try:
            result = await cloudflare_redirect_service.setup_redirect(site, target_url)
            await self._complete_job(job, ok=True, result=result)
        except Exception as e:
            await self._complete_job(job, ok=False, error=str(e))

    # ── 产品导入 ──
    async def import_products(self, site_id: int) -> dict:
        site = await site_controller.get(id=site_id)
        importer = get_importer(site.platform)
        rows = await woo_import_service.select_products_for_site(site)
        if not rows:
            return {"ok": False, "error": "没有可用的 ready 产品供导入", "code": 400}
        job = await self._create_job(site_id, site.domain, "woo_import", total_steps=len(rows))
        asyncio.create_task(self._run_import_bg(job, site, importer, pre_selected_rows=rows))
        return {"ok": True, "data": {"job_id": job.id, "domain": site.domain, "status": "running", "total": len(rows)}}

    async def batch_import_products(self, site_ids: List[int]) -> dict:
        batch_id = f"import-{int(time.time())}"
        sites = []
        results = []
        for site_id in site_ids:
            site = await site_controller.get(id=site_id)
            if site:
                sites.append(site)
            else:
                results.append({"site_id": site_id, "ok": False, "error": "site not found"})
        if not sites:
            return {"ok": True, "data": {"batch_id": batch_id, "results": results, "total": 0, "success": 0, "fail": len(site_ids)}}
        configured_count = int(await ProviderResolver.get_config("woo", "import_product_count", default="10"))
        for site in sites:
            importer = get_importer(site.platform)
            rows = await woo_import_service.select_products_for_site(site, import_count=configured_count)
            if not rows:
                results.append({"site_id": site.id, "domain": site.domain, "ok": False, "error": "没有可用的 ready 产品"})
                continue
            job = await self._create_job(site.id, site.domain, "woo_import", batch_id=batch_id, total_steps=len(rows))
            asyncio.create_task(self._run_import_bg(job, site, importer, pre_selected_rows=rows))
            results.append({"site_id": site.id, "domain": site.domain, "ok": True, "job_id": job.id, "status": "running", "product_count": len(rows)})
        return {"ok": True, "data": {"batch_id": batch_id, "results": results, "total": len(results),
                "success": sum(1 for r in results if r["ok"]), "fail": sum(1 for r in results if not r["ok"])}}

    async def _run_import_bg(self, job: OperationJob, site, importer, pre_selected_rows=None):
        async with _import_semaphore:
            await self._update_job_step(job, "importing")
            try:
                result = await importer.import_products(site, pre_selected_rows)
                ok = result.get("ok", False) if isinstance(result, dict) else False
                await self._complete_job(job, ok=ok, result=result)
                if ok and result.get("success", 0) > 0:
                    if site.platform == 'shopify':
                        await self._refresh_shopify_product_count(site)
                    else:
                        await self._refresh_product_count(site)
            except Exception as e:
                await self._complete_job(job, ok=False, error=str(e))

    async def refresh_product_count(self, site_id: int) -> dict:
        site = await site_controller.get(id=site_id)
        if site.platform == 'shopify':
            if not site.shopify_store_url or not site.shopify_token:
                return {"ok": False, "error": "Shopify Store URL 或 API Token 未配置", "code": 400}
            try:
                total = await self._refresh_shopify_product_count(site)
                return {"ok": True, "data": {"site_id": site_id, "domain": site.domain, "product_count": total}}
            except Exception as e:
                return {"ok": False, "error": f"无法连接 Shopify API: {e}", "code": 500}
        if not site.woo_ck or not site.woo_cs:
            return {"ok": False, "error": "该站点未配置 WooCommerce API 密钥（woo_ck / woo_cs）", "code": 400}
        if not site.login_url:
            return {"ok": False, "error": "该站点未配置登录地址", "code": 400}
        try:
            total = await self._refresh_product_count(site)
            return {"ok": True, "data": {"site_id": site_id, "domain": site.domain, "product_count": total}}
        except Exception as e:
            return {"ok": False, "error": f"无法连接 WooCommerce API: {e}", "code": 500}

    async def _refresh_product_count(self, site) -> int:
        from urllib.parse import urlparse
        from httpx import BasicAuth
        if not site.woo_ck or not site.woo_cs or not site.login_url:
            return 0
        parsed = urlparse(site.login_url)
        wc_api_url = f"{parsed.scheme}://{parsed.netloc}/wp-json/wc/v3/products"
        ssl_val = await ProviderResolver.get_config("onepanel", "wp_verify_ssl", "false")
        verify_ssl = ssl_val.lower() != "false"
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: httpx.get(
                wc_api_url,
                auth=BasicAuth(site.woo_ck, site.woo_cs),
                params={"per_page": 1},
                timeout=httpx.Timeout(10, read=30),
                verify=verify_ssl,
            ),
        )
        total_str = resp.headers.get("X-WP-Total", "0")
        total = int(total_str) if total_str.isdigit() else 0
        site.woo_product_count = total
        await site.save()
        return total

    async def _refresh_shopify_product_count(self, site) -> int:
        """通过 Shopify Admin API 查询远端产品总数。"""
        if not site.shopify_store_url or not site.shopify_token:
            return 0
        store = site.shopify_store_url.rstrip('/')
        if not store.startswith('http'):
            store = f'https://{store}'
        url = f'{store}/admin/api/2024-01/products/count.json'
        async with httpx.AsyncClient(
            headers={'X-Shopify-Access-Token': site.shopify_token},
            timeout=15,
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                _log.warning(f'[ShopifyCount] HTTP {resp.status_code}: {resp.text[:200]}')
                return 0
            data = resp.json()
            total = data.get('count', 0)
        site.woo_product_count = total
        await site.save()
        _log.info(f'[ShopifyCount] site={site.id} domain={site.domain} count={total}')
        return total


site_pipeline_controller = SitePipelineController()
