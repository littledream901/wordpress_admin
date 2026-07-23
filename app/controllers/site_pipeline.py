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
from app.utils.config_reader import get_config_async
from app.utils.provider_resolver import ProviderResolver
from app.utils.orm_guard import guard_thread_pool

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

woo_import_service = WooImportService()

_onepanel_api = None
_onepanel_files = None


def _get_onepanel_api():
    global _onepanel_api
    if _onepanel_api is None:
        _onepanel_api = OnePanelAPI()
    return _onepanel_api


def _get_onepanel_files():
    global _onepanel_files
    if _onepanel_files is None:
        _onepanel_files = OnePanelFileManager(_get_onepanel_api())
    return _onepanel_files

_provision_semaphore: asyncio.Semaphore | None = None
_import_semaphore: asyncio.Semaphore | None = None


def _get_provision_semaphore() -> asyncio.Semaphore:
    """惰性创建建站信号量（避免模块导入时触发 provider 配置读取）"""
    global _provision_semaphore
    if _provision_semaphore is None:
        _provision_semaphore = asyncio.Semaphore(_load_max_concurrent())
    return _provision_semaphore


def _get_import_semaphore() -> asyncio.Semaphore:
    """惰性创建导入信号量（避免模块导入时触发 provider 配置读取）"""
    global _import_semaphore
    if _import_semaphore is None:
        _import_semaphore = asyncio.Semaphore(_load_max_concurrent())
    return _import_semaphore


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


def _apply_dns_result_to_site(site, result: dict):
    """将 DNS 结果写入 site 对象（不 save，由调用方在 async 上下文中 save）"""
    now = datetime.now()

    # 明确失败的响应（如 Zone 创建失败）不覆盖 site 状态
    if result.get("ok") is False:
        return

    root_ok = result.get('root_ok', False)
    www_ok = result.get('www_ok', False)
    dynadot_r = result.get('dynadot_result')

    log_entry = json.dumps({
        "ts": now.isoformat(),
        "source": "cloudflare_dns_ns",
        "action": "Cloudflare DNS解析 + NS配置",
        "status": "success" if (root_ok and www_ok) else "partial_fail",
        "completed_at": now.isoformat(),
        "zone_id": result.get('zone_id'),
        "zone_status": result.get('zone_status'),
        "name_servers": result.get('name_servers'),
        "root_ok": root_ok,
        "www_ok": www_ok,
        "dynadot_result": dynadot_r,
    }, ensure_ascii=False)
    site.pipeline_log = (site.pipeline_log or '') + '\n' + log_entry

    # 更新 CF / Dynadot 状态供前端展示（与 cloudflare_service.py 保持一致）
    if root_ok and www_ok:
        site.cloudflare_status = '已解析'
    elif root_ok or www_ok:
        site.cloudflare_status = '部分失败'
    else:
        site.cloudflare_status = '失败'

    if dynadot_r:
        site.dynadot_status = 'ns_updated' if dynadot_r.get('success') else 'ns_failed'
    else:
        # Zone 已 active，NS 已正确配置，无需 Dynadot 操作
        zone_status = result.get('zone_status', '')
        site.dynadot_status = f'zone_{zone_status}' if zone_status else 'zone_active'


@guard_thread_pool
def _run_dns_sync(domain: str, platform: str, server_ip: str):
    """在线程池中同步执行 DNS + NS 操作（避免阻塞事件循环）

    注意：此函数运行在 run_in_executor 线程中，不可创建新 event loop 访问 Tortoise DB。
    参数使用纯数据类型，严禁传入 Tortoise ORM 模型实例（跨线程共享 ORM 对象会污染状态）。

    Cloudflare zone 创建 → CF 记录设置（含 0.3s 间隔）→ Dynadot NS 更新，串行执行防 API 限流。
    """
    # 运行时守卫：必须在 run_in_executor 线程池中执行，严禁在事件循环内直接调用
    try:
        asyncio.get_running_loop()
        raise RuntimeError(
            "_run_dns_sync 必须在 run_in_executor 线程池中运行（当前处于事件循环内），"
            "请通过 loop.run_in_executor(None, _run_dns_sync, ...) 调用"
        )
    except RuntimeError as e:
        if "no running event loop" in str(e):
            pass  # 正确：不在事件循环内，处于线程池线程
        else:
            raise
    from app.services.providers.dynadot_service import DynadotService

    cf = cloudflare_service

    if platform == 'shopify':
        SHOPIFY_IP = '23.227.38.65'
        SHOPIFY_CNAME = 'shops.myshopify.com.'
        zone_id, ns, status = cf.get_or_create_zone(domain)
        if not zone_id:
            return {'ok': False, 'error': f'Shopify zone 创建失败: domain={domain}'}

        # Cloudflare 记录先执行，然后更新 Dynadot NS（串行，避免 API 限流）
        cf_results = _setup_cf_records(cf, zone_id, domain,
            root_type='A', root_value=SHOPIFY_IP,
            www_type='CNAME', www_value=SHOPIFY_CNAME,
            www_name='www')
        dynadot_result = None
        if status in ('pending', 'invalid_nameservers'):
            try:
                dynadot_result = DynadotService().set_nameserver(domain, ns)
            except Exception as e:
                dynadot_result = {"success": False, "error": str(e)}

        return {
            'zone_id': zone_id, 'zone_status': status, 'name_servers': ns,
            'root_ok': cf_results.get('root_ok', False),
            'www_ok': cf_results.get('www_ok', False),
            'dynadot_result': dynadot_result,
        }
    else:
        zone_id, ns, status = cf.get_or_create_zone(domain)
        if not zone_id:
            return {'ok': False, 'error': f'Zone 创建失败: domain={domain}'}

        # Cloudflare 记录先执行，然后更新 Dynadot NS（串行，避免 API 限流）
        cf_results = _setup_cf_records(cf, zone_id, domain,
            root_type='A', root_value=server_ip,
            www_type='A', www_value=server_ip,
            www_name=f'www.{domain}')
        dynadot_result = None
        if status in ('pending', 'invalid_nameservers'):
            try:
                dynadot_result = DynadotService().set_nameserver(domain, ns)
            except Exception as e:
                dynadot_result = {"success": False, "error": str(e)}

        return {
            'zone_id': zone_id, 'zone_status': status, 'name_servers': ns,
            'root_ok': cf_results.get('root_ok', False),
            'www_ok': cf_results.get('www_ok', False),
            'dynadot_result': dynadot_result,
        }


def _setup_cf_records(cf, zone_id, domain, root_type, root_value, www_type, www_value, www_name=None):
    """在 ThreadPoolExecutor 中执行的 Cloudflare 记录设置（同步）"""
    if www_name is None:
        www_name = f'www.{domain}'
    cf.delete_records_by_type(zone_id, root_type)
    time.sleep(0.3)
    cf.delete_records_by_type(zone_id, 'AAAA')
    time.sleep(0.3)
    if root_type == 'CNAME':
        root_ok = cf.add_or_update_cname_record(zone_id, domain, root_value)
    else:
        root_ok = cf.add_or_update_a_record(zone_id, domain, root_value)
    time.sleep(0.3)
    if www_type == 'CNAME':
        www_ok = cf.add_or_update_cname_record(zone_id, 'www', www_value)
    else:
        www_ok = cf.add_or_update_a_record(zone_id, www_name, www_value)
    return {'root_ok': root_ok, 'www_ok': www_ok}


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
        """Agent 回传结果（已弃用：请走 hubstudio_service.report_job_result）"""
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
            site.hub_status = f"{job.job_type}:{status}"
            site.pipeline_status = f'hubstudio:{status}'
            old_log = site.pipeline_log or ''
            from app.utils.config_reader import get_provider_info_async as get_provider_info
            provider_info = await get_provider_info("hubstudio")
            site.pipeline_log = (old_log + '\n' + json.dumps({
                'job_id': job.id,
                'job_type': job.job_type,
                'status': status,
                'worker_name': worker_name,
                'error_message': error_message,
                'result_json': result_json,
                'provider': provider_info,
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
        gmc_status: str = '', status: str = '', hub_status: str = '',
        created_at_after: str = '', created_at_before: str = '',
        current_user=None,
    ) -> dict:
        """查询站点列表并附加部门/用户/Gmail 信息"""
        from app.core.data_permission import DataPermissionFilter
        t0 = time.perf_counter()
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
        if gmc_status:
            if gmc_status == '__empty__':
                q &= Q(gmc_status='')
            elif gmc_status == 'unknown':
                q &= Q(gmc_status__in=['unknown', 'pending', 'failed', 'query_failed'])
            else:
                q &= Q(gmc_status=gmc_status)
        if status:
            q &= Q(status=status)
        if hub_status == 'has_status':
            q &= ~Q(hub_status='')
        elif hub_status == 'no_status':
            q &= Q(hub_status='')
        if created_at_after:
            q &= Q(created_at__gte=created_at_after)
        if created_at_before:
            q &= Q(created_at__lte=created_at_before + ' 23:59:59')
        t1 = time.perf_counter()
        total, objs = await site_controller.list(page=page, page_size=page_size, search=q, order=['-id'])
        t2 = time.perf_counter()

        dept_ids = {d for obj in objs if (d := getattr(obj, 'dept_id', None))}
        user_ids = {u for obj in objs if (u := getattr(obj, 'create_by', None))}
        site_ids_list = [obj.id for obj in objs]

        # 并行查询三张关联表
        dept_task = Dept.filter(id__in=list(dept_ids)).all() if dept_ids else None
        user_task = User.filter(id__in=list(user_ids)).all() if user_ids else None
        gmail_task = None
        try:
            gmail_task = GmailAccount.filter(assigned_site_id__in=site_ids_list).all()
        except Exception:
            _log.warning("GmailAccount 查询失败（字段可能未迁移），跳过")

        results = await asyncio.gather(
            dept_task or asyncio.sleep(0),
            user_task or asyncio.sleep(0),
            gmail_task or asyncio.sleep(0),
        )
        depts, users, gmails = results[0] or [], results[1] or [], results[2] or []
        dept_map = {d.pk: d.name for d in depts}
        user_map = {u.id: u.username for u in users}
        gmail_map = {}
        for g in gmails:
            sid = getattr(g, 'assigned_site_id', None)
            if sid is not None:
                gmail_map[sid] = g

        # 并行序列化
        dicts = await asyncio.gather(*[obj.to_dict(exclude_fields=['pipeline_log']) for obj in objs])
        data = []
        for obj, d in zip(objs, dicts):
            gmail = gmail_map.get(obj.id)
            d['gmail_username'] = gmail.username if gmail else ''
            d['gmail_status'] = gmail.status if gmail else ''
            d['dept_name'] = dept_map.get(getattr(obj, 'dept_id', None), '')
            d['assign_to_name'] = user_map.get(getattr(obj, 'create_by', None), '')
            data.append(d)

        t3 = time.perf_counter()
        _log.info(
            "[site/list] 耗时分解 | 权限过滤: %dms | DB查询: %dms | 关联+序列化: %dms | 总计: %dms",
            int((t1 - t0) * 1000), int((t2 - t1) * 1000),
            int((t3 - t2) * 1000), int((t3 - t0) * 1000),
        )
        return {"total": total, "data": data, "page": page, "page_size": page_size}

    async def get_site_detail(self, site_id: int) -> dict:
        """获取站点详情，附带部门/用户/Gmail/Provider 绑定信息"""
        obj = await site_controller.get(id=site_id)
        site_dict = await obj.to_dict()
        dept_id = getattr(obj, 'dept_id', None)
        if dept_id:
            dept = await Dept.get_or_none(id=dept_id)
            site_dict['dept_name'] = dept.name if dept else ''
        else:
            site_dict['dept_name'] = ''
        create_by = getattr(obj, 'create_by', None)
        if create_by:
            owner = await User.get_or_none(id=create_by)
            site_dict['assign_to_name'] = owner.username if owner else ''
        else:
            site_dict['assign_to_name'] = ''
        try:
            gmail = await GmailAccount.filter(assigned_site_id=obj.id).first()
        except Exception:
            _log.warning("GmailAccount 详情查询失败（字段可能未迁移）")
            gmail = None

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
            if existed.is_deleted:
                return {"ok": False, "error": f"域名 {site_in.domain} 已在回收站中，请先从回收站恢复后再创建", "code": 409, "in_recycle_bin": True}
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
                None, lambda: _get_onepanel_api().post(
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
                if site.onepanel_status in ('', '待处理', '创建中'):
                    site.onepanel_status = '已存在'
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
                    if existed.is_deleted:
                        results.append({"domain": item.domain, "ok": False, "error": "in_recycle_bin"})
                    else:
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
            try:
                site = await site_controller.get(id=sid)
            except Exception:
                continue
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
        job = await self._create_job(site_id, site.domain, "provision", total_steps=12)
        asyncio.create_task(self._run_provision_bg(job, site))
        return {"ok": True, "data": {"job_id": job.id, "step": "create_site", "total_steps": 12}}

    async def _run_provision_bg(self, job: OperationJob, site):
        async with _get_provision_semaphore():
            from app.services.tasks.provision import provision_task_runner
            await provision_task_runner._run_impl(job, site)

    async def batch_provision(self, site_ids: List[int], batch_id: str = "") -> dict:
        results = []
        for site_id in site_ids:
            try:
                site = await site_controller.get(id=site_id)
            except Exception:
                results.append({"site_id": site_id, "ok": False, "error": "site not found"})
                continue
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
        cf_token = await get_config_async("CF_API_TOKEN")
        cf_account = await get_config_async("CF_ACCOUNT_ID")
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
            result = await loop.run_in_executor(None, _run_dns_sync, site.domain, site.platform, site.server_ip)
            _apply_dns_result_to_site(site, result)
            await site.save()
            await self._complete_job(job, ok=True, result=result, site=site)
        except Exception as e:
            await self._complete_job(job, ok=False, error=str(e), site=site)

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
            import asyncio
            results = []
            for site in valid_sites:
                try:
                    loop = asyncio.get_event_loop()
                    r = await loop.run_in_executor(None, _run_dns_sync, site.domain, site.platform, site.server_ip)
                    dns_ok = r.get("ok") is not False
                    _apply_dns_result_to_site(site, r)
                    await site.save()
                    results.append({"site_id": site.id, "domain": site.domain, "ok": dns_ok, "result": r})
                except Exception as e:
                    results.append({"site_id": site.id, "domain": site.domain, "ok": False, "error": str(e)})
                # 间隔 2 秒，避免 API 限流 / 并发冲突
                await asyncio.sleep(2)
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
        return {"ok": True, "data": {
            "batch_id": batch_id, "job_id": job.id, "total": len(valid_sites),
            "invalid": len(invalid),
            "results": [{"site_id": s.id, "domain": s.domain, "ok": True} for s in valid_sites] + invalid,
        }}

    # ── Dynadot NS ──
    async def set_dynadot_ns(self, site_id: int, ns_list: List[str] = None) -> dict:
        site = await site_controller.get(id=site_id)
        job = await self._create_job(site_id, site.domain, "dynadot_ns")
        try:
            if not ns_list:
                ns_list = ["a.ns.cloudflare.com", "b.ns.cloudflare.com"]
            result = dynadot_service.set_nameserver(site.domain, ns_list)
            ok = result.get("success", False)
            await self._complete_job(job, ok=ok, result=result, error=result.get("error", ""), site=site)
            self._append_site_log(site, "dynadot_ns", {"success": ok}, "dynadot")
            site.dynadot_status = "ns_updated" if ok else f"ns_failed:{str(result.get('error',''))[:80]}"
            await site.save()
            if ok:
                return {"ok": True, "data": {"domain": site.domain, "ns_list": ns_list, "raw": result}}
            return {"ok": False, "error": result.get("error", "Unknown error"), "code": 500}
        except Exception as e:
            await self._complete_job(job, ok=False, error=str(e), site=site)
            site.dynadot_status = f"ns_failed:{str(e)[:80]}"
            await site.save()
            return {"ok": False, "error": str(e), "code": 500}

    # ── Redirect ──
    async def provision_redirect(self, site_id: int, target_url: str) -> dict:
        site = await site_controller.get(id=site_id)
        job = await self._create_job(site_id, site.domain, "redirect")
        try:
            result = await cloudflare_redirect_service.setup_redirect(site, target_url)
            await self._complete_job(job, ok=True, result=result, site=site)
            return {"ok": True, "data": result}
        except Exception as e:
            await self._complete_job(job, ok=False, error=str(e), site=site)
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
            await self._complete_job(job, ok=True, result=result, site=site)
        except Exception as e:
            await self._complete_job(job, ok=False, error=str(e), site=site)

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
        """批量触发产品导入。

        为避免大量站点在主线程串行处理导致 HTTP 超时，
        实际建 Job 逻辑放入后台任务，接口秒返回 batch_id。
        """
        batch_id = f"import-{int(time.time())}"
        asyncio.create_task(self._batch_import_bg(site_ids, batch_id))
        return {"ok": True, "data": {
            "batch_id": batch_id, "total": len(site_ids),
            "msg": f"批量导入已触发（{len(site_ids)} 个站点），请在任务中心查看进度",
        }}

    async def _batch_import_bg(self, site_ids: List[int], batch_id: str):
        """后台逐站创建导入 Job"""
        sites = []
        for site_id in site_ids:
            site = await site_controller.get(id=site_id)
            if site:
                sites.append(site)
            else:
                _log.warning("[batch_import] 站点不存在: id=%s", site_id)
        if not sites:
            return

        configured_count = int(await ProviderResolver.get_config("woo", "import_product_count", default="10"))
        for site in sites:
            try:
                importer = get_importer(site.platform)
                rows = await woo_import_service.select_products_for_site(site, import_count=configured_count)
                if not rows:
                    _log.info("[batch_import] 无可用产品: domain=%s", site.domain)
                    continue
                job = await self._create_job(site.id, site.domain, "woo_import", batch_id=batch_id, total_steps=len(rows))
                asyncio.create_task(self._run_import_bg(job, site, importer, pre_selected_rows=rows))
            except Exception:
                _log.exception("[batch_import] 创建导入任务失败: domain=%s", site.domain)

    async def _run_import_bg(self, job: OperationJob, site, importer, pre_selected_rows=None):
        async with _get_import_semaphore():
            try:
                await self._update_job_step(job, "importing")
                result = await importer.import_products(site, pre_selected_rows)
                ok = result.get("ok", False) if isinstance(result, dict) else False
                await self._complete_job(job, ok=ok, result=result, site=site)
                if ok and result.get("success", 0) > 0:
                    if site.platform == 'shopify':
                        await self._refresh_shopify_product_count(site)
                    else:
                        await self._refresh_product_count(site)
            except Exception as e:
                # 兜底：确保即使 _complete_job 抛异常，任务状态也能落盘
                try:
                    await self._complete_job(job, ok=False, error=str(e), site=site)
                except Exception as inner_e:
                    _log.error("_run_import_bg _complete_job 失败: %s", inner_e)
                    job.status = "failed"
                    job.error_message = str(e)
                    job.finished_at = datetime.now()
                    await job.save()

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
                _log.warning('[ShopifyCount] HTTP %s: %s', resp.status_code, resp.text[:200])
                return 0
            data = resp.json()
            total = data.get('count', 0)
        site.woo_product_count = total
        await site.save()
        _log.info('[ShopifyCount] site=%s domain=%s count=%s', site.id, site.domain, total)
        return total


site_pipeline_controller = SitePipelineController()
