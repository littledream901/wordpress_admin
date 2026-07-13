"""站点流水线 API —— 站点 CRUD / 批量操作 / DNS / 建站 / Dynadot / HubStudio / Woo

所有执行类操作均创建 OperationJob 统一追踪。
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

_log = logging.getLogger(__name__)

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel
from tortoise.expressions import Q

from app.controllers.site_pipeline import hubstudio_job_controller, site_controller
from app.core.data_permission import DataPermissionFilter
from app.core.dependency import AuthControl
from app.models.admin import User
from app.models.gmail_account import GmailAccount
from app.models.shopify_collect import ShopifyProduct
from app.utils.config_reader import get_config
from app.utils.provider_resolver import ProviderResolver
from app.models.operation_job import OperationJob
from app.models.site_pipeline import HubStudioJob
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.site_pipeline import (
    HubStudioJobCreate, HubStudioJobReport,
    SiteBatchCreate, SiteCreate, SiteUpdate,
)
from app.services.cloudflare_redirect_service import CloudflareRedirectService
from app.services.cloudflare_service import CloudflareService
from app.services.hubstudio_service import HubStudioService
from app.services.onepanel_service import (
    OnePanelAPI, OnePanelDatabaseRestorer, OnePanelFileManager,
    OnePanelSiteManager, OnePanelSSLManager, OnePanelWordPressRestorer,
)
from app.services.providers.dynadot_service import DynadotService
from app.services.woo_import_service import WooImportService

router = APIRouter(tags=["SitePipeline"])

# 建站并发控制（优先 pipeline Provider 的 max_concurrent，回退默认值 3）
def _load_max_concurrent() -> int:
    try:
        from app.utils.provider_resolver import ProviderResolver
        val = ProviderResolver.sync_get_config('pipeline', 'max_concurrent', '')
        if val and val.isdigit():
            return int(val)
    except Exception:
        pass
    return 3

_provision_semaphore = asyncio.Semaphore(_load_max_concurrent())
_woo_import_semaphore = asyncio.Semaphore(_load_max_concurrent())

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


# ══════════════════════════════════════════════════════════════════════════
#  OperationJob 辅助函数

from app.services.tasks.runner import task_runner
# ══════════════════════════════════════════════════════════════════════════

async def _create_job(site_id: int, domain: str, action_type: str, payload: dict = None, batch_id: str = "", total_steps: int = 1) -> OperationJob:
    """创建操作任务记录（委托到 TaskRunner）"""
    return await task_runner._create_job(site_id, domain, action_type, payload, batch_id, total_steps)

async def _update_job_step(job: OperationJob, step: str):
    """更新任务步骤进度（委托到 TaskRunner）"""
    await task_runner._update_step(job, step)

async def _complete_job(job: OperationJob, ok: bool, result: dict = None, error: str = "",
                          provider_type: str = "", site=None, action_label: str = ""):
    """完成任务（委托到 TaskRunner）"""
    await task_runner._complete_job(job=job, ok=ok, result=result, error=error, site=site)


def _append_site_log(site, source: str, data: dict, provider_type: str = "",
                     action: str = "", status: str = "success", started_at: datetime = None,
                     completed_at: datetime = None, error: str = ""):
    """追加站点流水线日志（委托到 TaskRunner）"""
    task_runner._append_site_log(
        site=site, source=source, data=data,
        provider_type=provider_type, action=action,
        status=status, started_at=started_at,
        completed_at=completed_at, error=error,
    )


# ── 建站辅助══════════════════════════════════════════════════════════════════════════
#  站点 CRUD
# ══════════════════════════════════════════════════════════════════════════

@router.get('/site/list', summary='查看站点列表')
async def list_sites(
    page: int = Query(1, description='页码'),
    page_size: int = Query(10, description='每页数量'),
    domain: str = Query('', description='域名搜索'),
    dept_id: int = Query(None, description='按部门筛选'),
    assign_to: int = Query(None, description='按归属用户筛选'),
    current_user: User = Depends(AuthControl.is_authed),
):
    q = Q()
    if domain:
        q &= Q(domain__contains=domain)

    # 数据权限过滤
    data_filter = await DataPermissionFilter.get_filter_condition(
        current_user, None, resource="site", owner_field="create_by", dept_field="dept_id",
    )
    q &= data_filter

    # 手动筛选（在数据权限过滤之后叠加）
    if dept_id is not None:
        q &= Q(dept_id=dept_id)
    if assign_to is not None:
        q &= Q(create_by=assign_to)

    total, objs = await site_controller.list(page=page, page_size=page_size, search=q, order=['-id'])
    # 批量查询部门名称 + 被分配人名称 + Gmail
    dept_ids = {obj.dept_id for obj in objs if obj.dept_id}
    user_ids = {obj.create_by for obj in objs if obj.create_by}
    site_ids = [obj.id for obj in objs]
    dept_map, user_map, gmail_map = {}, {}, {}
    if dept_ids:
        from app.models.admin import Dept
        depts = await Dept.filter(id__in=list(dept_ids)).all()
        dept_map = {d.id: d.name for d in depts}
    if user_ids:
        users = await User.filter(id__in=list(user_ids)).all()
        user_map = {u.id: u.username for u in users}
    gmails = await GmailAccount.filter(assigned_site_id__in=site_ids).all()
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
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get('/site/get', summary='查看站点详情')
async def get_site(site_id: int = Query(..., description='站点ID')):
    obj = await site_controller.get(id=site_id)
    site_dict = await obj.to_dict()
    # 附加部门名称和归属人
    from app.models.admin import Dept
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

    # 解析该站点的 Provider 绑定（按 CORE_TYPES）
    from app.models.config_provider import ConfigProvider, ResourceProviderBinding, ProviderConfigItem
    CORE_TYPES = ['cloudflare', 'dynadot', 'onepanel', 'hubstudio']
    providers = {}
    for ptype in CORE_TYPES:
        binding = await ResourceProviderBinding.filter(
            resource_type='site', resource_id=site_id, provider_type=ptype
        ).first()
        if binding:
            p = await ConfigProvider.filter(id=binding.provider_id).first()
            providers[ptype] = {
                'provider_id': binding.provider_id,
                'provider_name': p.provider_name if p else f'#{binding.provider_id}',
                'is_default': p.is_default if p else False,
                'bound': True,
            }
        else:
            dp = await ConfigProvider.get_default(ptype)
            providers[ptype] = {
                'provider_id': dp.id if dp else None,
                'provider_name': dp.provider_name if dp else '无默认',
                'is_default': True,
                'bound': False,
            }

    return Success(data={
        'site': site_dict,
        'gmail': await gmail.to_dict() if gmail else None,
        'providers': providers,
    })


@router.post('/site/create', summary='创建站点记录')
async def create_site(site_in: SiteCreate, current_user: User = Depends(AuthControl.is_authed)):
    existed = await site_controller.get_by_domain(site_in.domain)
    if existed:
        await _sync_onepanel_status(existed)
        return Fail(code=400, msg='域名已存在')
    site = await site_controller.create(site_in)
    # 数据权限字段：assign_to > dept_id > current_user 默认值
    if site_in.assign_to:
        assigned_user = await User.get_or_none(id=site_in.assign_to)
        site.create_by = site_in.assign_to
        site.dept_id = assigned_user.dept_id if assigned_user else current_user.dept_id
    else:
        site.create_by = current_user.id
        site.dept_id = site_in.dept_id if site_in.dept_id is not None else current_user.dept_id
    await site.save()
    return Success(data={'id': site.id}, msg='Created Successfully')


@router.post('/site/update', summary='更新站点')
async def update_site(site_in: SiteUpdate):
    await site_controller.update(id=site_in.id, obj_in=site_in)
    return Success(msg='Updated Successfully')


async def _sync_onepanel_status(site):
    """同步 1Panel 中的站点状态到本地记录"""
    if not site.domain:
        _log.info("同步 onepanel_status 跳过: site_id=%s 域名为空", site.id)
        return
    loop = asyncio.get_event_loop()
    try:
        # 直接调用 API 获取结果，便于排查
        ok, data = await loop.run_in_executor(
            None, lambda: onepanel_api.post(
                '/websites/search',
                {'page': 1, 'pageSize': 200, 'OrderBy': 'created_at', 'Order': 'descending'}
            )
        )
        if not ok:
            _log.warning("同步 onepanel_status: domain=%s 1Panel API 调用失败 data=%s", site.domain, data)
            return
        if not isinstance(data, dict):
            _log.warning("同步 onepanel_status: domain=%s API 返回非字典类型: %s", site.domain, type(data))
            return

        items = data.get('items') or []
        op_site_id = None
        for item in items:
            if item.get('primaryDomain') == site.domain:
                op_site_id = int(item['id'])
                break

        if op_site_id:
            site.onepanel_site_id = op_site_id
            old_status = site.onepanel_status
            if site.onepanel_status in ('', '待处理', 'site_created'):
                site.onepanel_status = 'exists_in_panel'
            _log.info("同步 onepanel_status: domain=%s site_id=%s old=%s new=%s",
                      site.domain, op_site_id, old_status, site.onepanel_status)
            await site.save()
        else:
            _log.info("同步 onepanel_status: domain=%s 未在 1Panel 中找到站点，API返回 %d 条记录，当前本地状态=%s",
                      site.domain, len(items), site.onepanel_status)
    except Exception as e:
        _log.warning("同步 onepanel_status 失败: domain=%s error=%s", site.domain, e)


def _build_onepanel_url(cfgs: dict) -> str:
    url = str(cfgs.get('url', cfgs.get('OP_URL', ''))).strip()
    if not url:
        return ''
    if not url.startswith('http'):
        url = 'https://' + url
    return url.rstrip('/') + '/api/v2'


def _make_onepanel_headers(api_key: str) -> dict:
    import hashlib
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
    import httpx
    resp = httpx.request(method=method, url=url, headers=headers, json=payload,
                         timeout=httpx.Timeout(30))
    try:
        data = resp.json()
    except Exception:
        return False, f"HTTP {resp.status_code}: {resp.text[:500]}"
    if data.get('code') == 200:
        return True, data.get('data')
    return False, f"code={data.get('code')} message={data.get('message')}"


@router.post('/site/delete', summary='删除站点（同时异步删除 1Panel 网站）')
async def delete_site(site_id: int = Query(...)):
    site = await site_controller.get(id=site_id)
    info = None
    if site:
        info = {"id": site.id, "domain": site.domain, "onepanel_status": site.onepanel_status}
    await site_controller.remove(id=site_id)
    if info:
        asyncio.create_task(_delete_from_1panel_by_info(info))
    return Success(msg='Deleted Successfully')


# ══════════════════════════════════════════════════════════════════════════
#  站点批量操作
# ══════════════════════════════════════════════════════════════════════════

async def _run_batch_create_bg(items: list, job_id: int, user_id: int = None, dept_id: int = None):
    """后台批量创建站点"""
    results = []
    for item in items:
        try:
            existed = await site_controller.get_by_domain(item.domain)
            if existed:
                await _sync_onepanel_status(existed)
                results.append({"domain": item.domain, "ok": False, "error": "already exists"})
                continue
            site = await site_controller.create(item)
            # 数据权限：assign_to > dept_id > 调用方默认值
            item_assign_to = getattr(item, 'assign_to', None)
            if item_assign_to:
                assigned_user = await User.get_or_none(id=item_assign_to)
                site.create_by = item_assign_to
                site.dept_id = assigned_user.dept_id if assigned_user else (dept_id or 0)
            else:
                site.create_by = user_id if user_id else 0
                item_dept_id = getattr(item, 'dept_id', None)
                site.dept_id = item_dept_id if item_dept_id is not None else (dept_id or 0)
            await site.save()
            results.append({"domain": item.domain, "ok": True, "error": ""})
        except Exception as e:
            results.append({"domain": item.domain, "ok": False, "error": str(e)})
    success = sum(1 for r in results if r["ok"])
    fail = len(results) - success
    job = await OperationJob.get_or_none(id=job_id)
    if job:
        job.status = "success" if fail == 0 else "failed"
        job.result_json = json.dumps({"results": results, "total": len(results), "success": success, "fail": fail}, ensure_ascii=False)
        job.finished_at = datetime.now()
        await job.save()


@router.post('/site/batch-create', summary='批量新增站点（异步）')
async def batch_create_sites(payload: SiteBatchCreate, current_user: User = Depends(AuthControl.is_authed)):
    batch_id = f"create-{int(time.time())}"
    job = await _create_job(0, f"batch-{batch_id}", "batch_create", batch_id=batch_id, total_steps=len(payload.items))
    asyncio.create_task(_run_batch_create_bg(payload.items, job.id, current_user.id, current_user.dept_id))
    return Success(data={"batch_id": batch_id, "job_id": job.id, "total": len(payload.items), "status": "submitted"})


@router.post('/site/batch-delete', summary='批量删除站点（异步删除 1Panel 网站并创建追踪任务）')
async def batch_delete_sites(ids: list[int] = Body(...)):
    count = 0
    sites_info = []  # 保存站点信息供异步删除使用
    for sid in ids:
        try:
            site = await site_controller.get(id=sid)
            if site:
                sites_info.append({"id": site.id, "domain": site.domain, "onepanel_status": site.onepanel_status})
            await site_controller.remove(id=sid)
            count += 1
        except Exception as e:
            _log.warning("删除站点失败 id=%s: %s", sid, e)

    if not sites_info:
        return Success(data={"deleted": count, "pending_1panel_delete": 0})

    # 创建追踪任务
    job = await _create_job(0, f"batch-delete-{int(time.time())}", "batch_delete",
                            batch_id=f"delete-{int(time.time())}", total_steps=len(sites_info))
    job.result_json = json.dumps({"deleted_from_db": count, "results": []})
    await job.save()

    # 后台异步删除 1Panel 网站
    async def _bg_delete():
        del_ok = 0
        del_fail = 0
        del_skip = 0
        results = []
        for info in sites_info:
            try:
                _log.info("batch_delete 开始异步删除1Panel: domain=%s onepanel_status=%s",
                          info["domain"], info["onepanel_status"])
                r = await _delete_from_1panel_by_info(info)
                _log.info("batch_delete 1Panel结果: domain=%s status=%s detail=%s",
                          info["domain"], r["status"], r.get("detail", ""))
                results.append({"domain": info["domain"], "status": r["status"], "detail": r.get("detail", "")})
                if r["status"] == "deleted":
                    del_ok += 1
                elif r["status"] == "error":
                    del_fail += 1
                else:
                    del_skip += 1
            except Exception as e:
                _log.error("batch_delete 1Panel删除异常: domain=%s error=%s", info["domain"], e, exc_info=True)
                results.append({"domain": info["domain"], "status": "exception", "detail": str(e)})
                del_fail += 1
        job.status = "success" if del_fail == 0 else "failed"
        job.result_json = json.dumps({
            "deleted_from_db": count,
            "1panel_deleted": del_ok,
            "1panel_failed": del_fail,
            "1panel_skipped": del_skip,
            "results": results
        }, ensure_ascii=False)
        job.finished_at = datetime.now()
        await job.save()
        _log.info("batch_delete 后台任务完成: ok=%s fail=%s skip=%s", del_ok, del_fail, del_skip)

    asyncio.create_task(_bg_delete())

    return Success(data={
        "deleted": count,
        "pending_1panel_delete": len(sites_info),
        "job_id": job.id
    }, msg=f'已删除 {count} 条记录，1Panel 删除在后台进行，请在任务中心查看进度')


async def _delete_from_1panel_by_info(info: dict) -> dict:
    """通过域名和状态信息执行 1Panel 删除。

    返回 {"status": "deleted"|"not_found"|"error"|"skip", "detail": str}
    """
    domain = info["domain"]

    if not domain:
        return {"status": "skip", "detail": "域名为空"}

    from app.models.config_provider import ConfigProvider, ResourceProviderBinding

    # 收集候选 provider
    candidates = []
    seen_ids = set()

    # 1) 绑定的 provider
    binding = await ResourceProviderBinding.filter(
        resource_type='site', resource_id=info["id"],
        provider_type='onepanel', bind_type='preferred'
    ).first()
    if binding:
        p = await ConfigProvider.filter(id=binding.provider_id, status='active').first()
        if p:
            candidates.append(p)
            seen_ids.add(p.id)
            _log.info("_delete_from_1panel: domain=%s 绑定 provider=%s", domain, p.provider_name)

    # 2) 默认 provider
    default_p = await ConfigProvider.get_default('onepanel')
    if default_p and default_p.id not in seen_ids:
        candidates.append(default_p)
        _log.info("_delete_from_1panel: domain=%s 默认 provider=%s", domain, default_p.provider_name)

    if not candidates:
        _log.warning("_delete_from_1panel 跳过: domain=%s 无可用 onepanel provider", domain)
        return {"status": "skip", "detail": "无可用 onepanel provider"}

    for provider in candidates:
        result = await _try_delete_on_provider_by_domain(domain, provider)
        if result["status"] in ("deleted", "error"):
            return result  # 找到了（已删除或删除失败），不再回退

    _log.info("_delete_from_1panel: domain=%s 在所有 provider 上均未找到，跳过删除", domain)
    return {"status": "not_found", "detail": "所有 provider 上均未找到"}


async def _try_delete_on_provider_by_domain(domain: str, provider) -> dict:
    """在指定 provider 上按域名搜索并删除站点。

    返回 {"status": "deleted"|"not_found"|"error", "detail": str}
    """
    from app.models.config_provider import ProviderConfigItem

    cfgs = await ProviderConfigItem.get_map(provider.id)
    base_url = _build_onepanel_url(cfgs)
    api_key = str(cfgs.get('api_key', cfgs.get('OP_API_KEY', '')))
    if not base_url or not api_key:
        _log.warning("_delete_from_1panel: domain=%s provider=%s url/api_key 未配置",
                     domain, provider.provider_name)
        return {"status": "not_found", "detail": f"provider={provider.provider_name} url/api_key 未配置"}

    headers = _make_onepanel_headers(api_key)
    loop = asyncio.get_event_loop()

    # 搜索站点
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
            _log.info("_delete_from_1panel: domain=%s 在 provider=%s 上未找到", domain, provider.provider_name)
            return {"status": "not_found", "detail": f"provider={provider.provider_name} 上未找到"}
    except Exception as e:
        _log.warning("_delete_from_1panel 查询失败: domain=%s provider=%s error=%s",
                     domain, provider.provider_name, e)
        return {"status": "not_found", "detail": f"provider={provider.provider_name} 查询失败: {e}"}

    # 删除站点
    del_payload = {'id': op_site_id, 'deleteApp': True, 'deleteBackup': True, 'deleteDB': True, 'forceDelete': True}
    try:
        ok, msg = await loop.run_in_executor(
            None,
            lambda: _onepanel_request('POST', base_url + '/websites/del', del_payload, headers),
        )
        if ok:
            _log.info("_delete_from_1panel 成功: domain=%s onepanel_site_id=%s provider=%s",
                      domain, op_site_id, provider.provider_name)
            return {"status": "deleted", "detail": f"provider={provider.provider_name} site_id={op_site_id}"}
        else:
            _log.error("_delete_from_1panel 失败: domain=%s onepanel_site_id=%s provider=%s response=%s",
                       domain, op_site_id, provider.provider_name, msg)
            return {"status": "error", "detail": f"provider={provider.provider_name} site_id={op_site_id} {msg}"}
    except Exception as e:
        _log.error("_delete_from_1panel 异常: domain=%s onepanel_site_id=%s provider=%s error=%s",
                   domain, op_site_id, provider.provider_name, e)
        return {"status": "error", "detail": f"provider={provider.provider_name} site_id={op_site_id} {e}"}


class BatchAssignPayload(BaseModel):
    site_ids: list[int]
    dept_id: int | None = None
    assign_to: int | None = None


@router.post('/site/batch-assign', summary='批量分配站点（部门或用户）')
async def batch_assign_sites(payload: BatchAssignPayload):
    updated = 0
    for sid in payload.site_ids:
        site = await site_controller.get(id=sid)
        if not site:
            continue
        if payload.assign_to:
            assigned_user = await User.get_or_none(id=payload.assign_to)
            site.create_by = payload.assign_to
            site.dept_id = assigned_user.dept_id if assigned_user else site.dept_id
        elif payload.dept_id is not None:
            site.dept_id = payload.dept_id
        else:
            continue
        await site.save()
        updated += 1
    return Success(data={"updated": updated, "total": len(payload.site_ids)})


@router.post('/site/batch-dns', summary='批量执行 DNS + NS（Cloudflare 解析 + Dynadot NS 修改）')
async def batch_dns(site_ids: list[int] = Body(...)):
    """DNS + NS 一起运行：
    1. 获取/创建 Cloudflare Zone
    2. 如果 Zone 状态为 pending 或 invalid_nameservers，自动调用 Dynadot 修改 NS
    3. 添加根域名 + www 的 A 记录
    """
    batch_id = f"dns-{int(time.time())}"

    # 快速收集站点信息，不阻塞
    valid_sites = []
    invalid = []
    for sid in site_ids:
        try:
            site = await site_controller.get(id=sid)
            if not site or not site.server_ip:
                invalid.append({"site_id": sid, "error": "no server_ip"})
            else:
                valid_sites.append(site)
        except Exception as e:
            invalid.append({"site_id": sid, "error": str(e)})

    if not valid_sites:
        return Success(data={"batch_id": batch_id, "total": len(invalid), "results": invalid})

    # 创建追踪任务
    job = await _create_job(0, f"batch-dns-{batch_id}", "batch_dns",
                            batch_id=batch_id, total_steps=len(valid_sites))
    job.result_json = json.dumps({"total": len(valid_sites), "invalid": len(invalid), "results": []})
    await job.save()

    # 后台异步执行 DNS，加并发限制
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
            ensure_ascii=False
        )
        job.finished_at = datetime.now()
        await job.save()

    asyncio.create_task(_bg_dns())

    return Success(data={"batch_id": batch_id, "job_id": job.id, "total": len(valid_sites), "invalid": len(invalid)},
                   msg=f'已提交 {len(valid_sites)} 个 DNS 任务，请在任务中心查看进度')


def _run_dns_sync(site):
    """在线程池中同步执行 DNS + NS 操作（避免阻塞事件循环）"""
    import asyncio as _asyncio
    loop = _asyncio.new_event_loop()
    try:
        _asyncio.set_event_loop(loop)
        return loop.run_until_complete(cloudflare_service.provision_dns(site))
    finally:
        loop.close()


@router.post('/site/batch-provision', summary='批量执行 1Panel 建站')
async def batch_provision(site_ids: list[int] = Body(...)):
    batch_id = f"provision-{int(time.time())}"
    results = []
    for site_id in site_ids:
        site = await site_controller.get(id=site_id)
        if not site:
            results.append({"site_id": site_id, "ok": False, "error": "site not found"})
            continue
        exists = await _check_provision_blocked(site_id)
        if exists:
            results.append({
                "site_id": site_id,
                "domain": site.domain,
                "ok": False,
                "error": "已有建站任务执行中"
            })
            continue
        job = await _create_job(site_id, site.domain, "provision", batch_id=batch_id, total_steps=10)
        # 后台异步执行
        asyncio.create_task(_run_provision_bg(job, site))
        results.append({"site_id": site_id, "domain": site.domain, "ok": True, "job_id": job.id, "status": "running"})
    return Success(data={"batch_id": batch_id, "results": results, "total": len(results),
                         "success": sum(1 for r in results if r["ok"]),
                         "fail": sum(1 for r in results if not r["ok"])})


@router.post('/site/batch-dynadot-ns', summary='批量执行 Dynadot NS（独立操作，手动指定 NS）')
async def batch_dynadot_ns(site_ids: list[int] = Body(...), ns_list: list[str] = Body(None)):
    """手动指定 NS 列表独立修改，不走 DNS 集成流程。
    自动流程请使用 batch-dns，会在创建 Zone 时自动调用 Dynadot 修改 NS。"""
    batch_id = f"dynadot-ns-{int(time.time())}"
    results = []
    if not ns_list:
        ns_list = ["a.ns.cloudflare.com", "b.ns.cloudflare.com"]
    for site_id in site_ids:
        site = await site_controller.get(id=site_id)
        if not site:
            results.append({"site_id": site_id, "ok": False, "error": "site not found"})
            continue
        job = await _create_job(site_id, site.domain, "dynadot_ns", batch_id=batch_id)
        asyncio.create_task(_run_dynadot_ns_bg(job, site, ns_list))
        results.append({"site_id": site_id, "domain": site.domain, "ok": True, "job_id": job.id, "status": "running"})
    return Success(data={"batch_id": batch_id, "results": results, "total": len(results),
                         "success": sum(1 for r in results if r["ok"]),
                         "fail": sum(1 for r in results if not r["ok"])})


async def _run_dynadot_ns_bg(job: OperationJob, site, ns_list: list):
    """后台执行 Dynadot NS 修改"""
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, dynadot_service.set_nameserver, site.domain, ns_list),
            timeout=120,
        )
        ok = result.get("success", False)
        await _complete_job(job, ok=ok, result=result, error=result.get("error", ""))
        _append_site_log(site, "dynadot_ns", {"success": ok, "raw": str(result.get("raw", ""))[:200]}, "dynadot")
        site.dynadot_status = "ns_updated" if ok else f"ns_failed:{str(result.get('error',''))[:80]}"
        await site.save()
    except Exception as e:
        await _complete_job(job, ok=False, error=str(e))
        site.dynadot_status = f"ns_failed:{str(e)[:80]}"
        await site.save()


@router.post('/site/batch-redirect', summary='批量执行 301 重定向（根域名 + www 各一条规则）')
async def batch_redirect(site_ids: list[int] = Body(...), target_url: str = Body('')):
    """参考 cf_redirect_YY.py 逻辑：每个域名创建两条 Page Rule
    - {domain}/* → target_url
    - www.{domain}/* → target_url"""
    batch_id = f"redirect-{int(time.time())}"
    results = []
    for site_id in site_ids:
        site = await site_controller.get(id=site_id)
        if not site:
            results.append({"site_id": site_id, "ok": False, "error": "site not found"})
            continue
        job = await _create_job(site_id, site.domain, "redirect", batch_id=batch_id)
        asyncio.create_task(_run_redirect_bg(job, site, target_url))
        results.append({"site_id": site_id, "domain": site.domain, "ok": True, "job_id": job.id, "status": "running"})
    return Success(data={"batch_id": batch_id, "results": results, "total": len(results),
                         "success": sum(1 for r in results if r["ok"]),
                         "fail": sum(1 for r in results if not r["ok"])})


async def _run_redirect_bg(job: OperationJob, site, target_url: str):
    """后台执行 301 重定向"""
    try:
        result = await cloudflare_redirect_service.setup_redirect(site, target_url)
        await _complete_job(job, ok=True, result=result)
    except Exception as e:
        await _complete_job(job, ok=False, error=str(e))


@router.post('/site/batch-hub-dispatch', summary='批量派发 HubStudio 任务（仅创建任务，由 Agent 执行）')
async def batch_hub_dispatch(site_ids: list[int] = Body(...), job_type: str = Body('create_env')):
    batch_id = f"hub-{int(time.time())}"
    results = []
    for site_id in site_ids:
        site = await site_controller.get(id=site_id)
        if not site:
            results.append({"site_id": site_id, "ok": False, "error": "site not found"})
            continue
        try:
            hub_job = await hubstudio_service.dispatch_for_site(site_id, job_type)
            results.append({"site_id": site_id, "domain": site.domain, "ok": True,
                          "hub_job_id": hub_job.id, "status": "pending"})
        except Exception as e:
            results.append({"site_id": site_id, "domain": site.domain, "ok": False, "error": str(e)})
    return Success(data={"batch_id": batch_id, "results": results, "total": len(results),
                         "success": sum(1 for r in results if r["ok"]),
                         "fail": sum(1 for r in results if not r["ok"])})


@router.post('/site/batch-woo-import', summary='批量执行 Woo 导入')
async def batch_woo_import(site_ids: list[int] = Body(...)):
    batch_id = f"woo-{int(time.time())}"
    # 预加载所有站点
    sites = []
    for site_id in site_ids:
        site = await site_controller.get(id=site_id)
        sites.append(site) if site else results.append({"site_id": site_id, "ok": False, "error": "site not found"})

    if not sites:
        return Success(data={"batch_id": batch_id, "results": results, "total": 0, "success": 0, "fail": len(site_ids)})

    # 每个站点按配置数量导入，串行分配不会重复
    from app.utils.provider_resolver import ProviderResolver
    configured_count = int(await ProviderResolver.get_config("woo", "import_product_count", default="10"))

    results = []
    for site in sites:
        if not site:
            continue
        rows = await woo_import_service.select_products_for_site(site, import_count=configured_count)
        if not rows:
            results.append({"site_id": site.id, "domain": site.domain, "ok": False, "error": "没有可用的 ready 产品"})
            continue
        job = await _create_job(site.id, site.domain, "woo_import", batch_id=batch_id, total_steps=len(rows))
        asyncio.create_task(_run_woo_import_bg(job, site, pre_selected_rows=rows))
        results.append({"site_id": site.id, "domain": site.domain, "ok": True, "job_id": job.id, "status": "running", "product_count": len(rows)})
    return Success(data={"batch_id": batch_id, "results": results, "total": len(results),
                         "success": sum(1 for r in results if r["ok"]),
                         "fail": sum(1 for r in results if not r["ok"])})


async def _run_woo_import_bg(job: OperationJob, site, pre_selected_rows=None):
    """后台执行 Woo 商品导入（受全局并发限制）"""
    async with _woo_import_semaphore:
        await _update_job_step(job, "importing")
        try:
            result = await woo_import_service.import_for_site(site, pre_selected_rows=pre_selected_rows)
            ok = result.get("ok", False) if isinstance(result, dict) else False
            await _complete_job(job, ok=ok, result=result)
            # 导入成功后自动刷新远端产品数量
            if ok and result.get("success", 0) > 0:
                await _refresh_woo_product_count(site)
        except Exception as e:
            await _complete_job(job, ok=False, error=str(e))


async def _refresh_woo_product_count(site) -> int:
    """查询 WooCommerce API 获取远端产品总数，更新 site.woo_product_count"""
    import httpx
    from httpx import BasicAuth
    from urllib.parse import urlparse

    if not site.woo_ck or not site.woo_cs or not site.login_url:
        return 0

    parsed = urlparse(site.login_url)
    wc_api_url = f"{parsed.scheme}://{parsed.netloc}/wp-json/wc/v3/products"

    # 读取 SSL 验证配置
    from app.utils.provider_resolver import ProviderResolver
    ssl_val = await ProviderResolver.get_config("pipeline", "wp_verify_ssl", "false")
    verify_ssl = ssl_val.lower() != "false"

    loop = asyncio.get_event_loop()
    try:
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
        _log.info("站点 %s 导入后产品数已刷新: %s", site.domain, total)
        return total
    except Exception as e:
        _log.warning("站点 %s 导入后刷新产品数失败: %s", site.domain, e)
        return 0


# ══════════════════════════════════════════════════════════════════════════
#  单条操作端点（含 OperationJob 追踪）
# ══════════════════════════════════════════════════════════════════════════

_PROVISION_TIMEOUT_MINUTES = 30


async def _check_provision_blocked(site_id: int) -> Optional[OperationJob]:
    """检查站点是否被阻塞的建站任务占用。

    如果存在 running/pending 任务，检查是否超时：
    - 超时 → 自动标记为 failed，返回 None（允许触发）
    - 未超时 → 返回阻塞的 job（前端显示错误）
    """
    for status in ("running", "pending"):
        job = await OperationJob.filter(
            resource_type="site",
            resource_id=site_id,
            action_type="provision",
            status=status
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
                _log.warning("自动取消超时任务 #%s (站点 #%s, status=%s, 运行了 %.0f 分钟)",
                             job.id, site_id, status, elapsed.total_seconds() / 60)
                continue
        return job
    return None

@router.post('/site/{site_id}/provision', summary='触发 1Panel 建站')
async def provision_site(site_id: int):
    site = await site_controller.get(id=site_id)
    blocked = await _check_provision_blocked(site_id)
    if blocked:
        return Fail(code=400, msg='该站点已有建站任务执行中，请勿重复触发')

    job = await _create_job(site_id, site.domain, "provision", total_steps=10)
    # 后台异步执行建站，前端轮询 /operation-jobs/get?id=X 获取步骤进度
    asyncio.create_task(_run_provision_bg(job, site))
    return Success(data={"job_id": job.id, "step": "create_site", "total_steps": 10}, msg='建站已触发')


async def _run_provision_bg(job: OperationJob, site):
    """后台异步执行 1Panel 建站全流程（按原脚本逻辑重排）"""
    async with _provision_semaphore:
        await _run_provision_impl(job, site)


async def _run_provision_impl(job: OperationJob, site):
    """委托到 app/services/tasks/provision.py 执行完整建站流程"""
    from app.services.tasks.provision import provision_task_runner
    await provision_task_runner._run_impl(job, site)

@router.post('/site/{site_id}/dns', summary='触发 Cloudflare DNS + NS（含自动 Dynadot NS 修改）')
async def provision_dns(site_id: int):
    """DNS + NS 一起运行：创建/获取Zone → 自动Dynadot NS → 添加A记录"""
    cf_token = get_config("CF_API_TOKEN")
    cf_account = get_config("CF_ACCOUNT_ID")
    if not cf_token or not cf_account:
        return Fail(code=400, msg='Cloudflare 未配置：请在 系统管理 → 提供商管理 中配置 Cloudflare API Token 和 Account ID')
    site = await site_controller.get(id=site_id)
    if not site.server_ip:
        return Fail(code=400, msg='site server_ip is empty')
    job = await _create_job(site_id, site.domain, "dns")
    asyncio.create_task(_run_dns_single_bg(job, site))
    return Success(data={"job_id": job.id, "domain": site.domain, "status": "running"},
                   msg='DNS 任务已提交，请在任务中心查看进度')


async def _run_dns_single_bg(job: OperationJob, site):
    """单站点后台 DNS（在线程池中运行，避免阻塞事件循环）"""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _run_dns_sync, site)
        await _complete_job(job, ok=True, result=result)
    except Exception as e:
        await _complete_job(job, ok=False, error=str(e))


@router.post('/site/{site_id}/dynadot-ns', summary='触发 Dynadot NS 修改（独立操作，手动指定 NS）')
async def set_dynadot_ns(site_id: int, ns_list: list[str] = Body(None)):
    """手动指定 NS 列表，独立 NS 修改操作。"""
    site = await site_controller.get(id=site_id)
    job = await _create_job(site_id, site.domain, "dynadot_ns")
    try:
        if not ns_list:
            ns_list = ["a.ns.cloudflare.com", "b.ns.cloudflare.com"]
        result = dynadot_service.set_nameserver(site.domain, ns_list)
        ok = result.get("success", False)
        await _complete_job(job, ok=ok, result=result, error=result.get("error", ""))
        _append_site_log(site, "dynadot_ns", {"success": ok}, "dynadot")
        site.dynadot_status = "ns_updated" if ok else f"ns_failed:{str(result.get('error',''))[:80]}"
        await site.save()
        if ok:
            return Success(data={"domain": site.domain, "ns_list": ns_list, "raw": result}, msg='Dynadot NS updated')
        return Fail(code=500, msg=result.get("error", "Unknown error"))
    except Exception as e:
        await _complete_job(job, ok=False, error=str(e))
        site.dynadot_status = f"ns_failed:{str(e)[:80]}"
        await site.save()
        return Fail(code=500, msg=str(e))


@router.post('/site/{site_id}/redirect', summary='触发 301 重定向（根域名 + www 各一条）')
async def provision_redirect(site_id: int, target_url: str = Body('', embed=True)):
    """参考 cf_redirect_YY.py 逻辑：每个域名创建两条 Page Rule"""
    site = await site_controller.get(id=site_id)
    job = await _create_job(site_id, site.domain, "redirect")
    try:
        result = await cloudflare_redirect_service.setup_redirect(site, target_url)
        await _complete_job(job, ok=True, result=result)
        return Success(data=result, msg='Redirect triggered')
    except Exception as e:
        await _complete_job(job, ok=False, error=str(e))
        return Fail(code=500, msg=str(e))


@router.post('/site/{site_id}/woo-import', summary='触发 Woo 商品导入')
async def woo_import(site_id: int):
    site = await site_controller.get(id=site_id)
    # 先选择产品以获取待导入数量（仅 DB 查询，不阻塞）
    rows = await woo_import_service.select_products_for_site(site)
    if not rows:
        return Fail(code=400, msg='没有可用的 ready 产品供导入')
    job = await _create_job(site_id, site.domain, "woo_import", total_steps=len(rows))
    asyncio.create_task(_run_woo_import_bg(job, site, pre_selected_rows=rows))
    return Success(data={"job_id": job.id, "domain": site.domain, "status": "running", "total": len(rows)},
                   msg=f'正在导入 {len(rows)} 个产品，请在任务中心查看进度')


@router.post('/site/{site_id}/refresh-woo-count', summary='同步站点 WooCommerce 远端产品数量')
async def refresh_woo_count(site_id: int):
    """调用 WooCommerce API 查询站点远端产品总数，并更新到数据库"""
    site = await site_controller.get(id=site_id)
    if not site.woo_ck or not site.woo_cs:
        return Fail(code=400, msg='该站点未配置 WooCommerce API 密钥（woo_ck / woo_cs）')
    if not site.login_url:
        return Fail(code=400, msg='该站点未配置登录地址，无法构造 WooCommerce API 地址')

    try:
        total = await _refresh_woo_product_count(site)
        return Success(data={"site_id": site_id, "domain": site.domain, "woo_product_count": total},
                       msg=f'远端产品总数: {total}')
    except Exception as e:
        return Fail(code=500, msg=f'无法连接 WooCommerce API: {e}')


# ══════════════════════════════════════════════════════════════════════════
#  HubStudio 任务管理
# ══════════════════════════════════════════════════════════════════════════

@router.get('/hub-job/list', summary='查看 HubStudio 任务列表')
async def list_hub_jobs(
    page: int = Query(1, description='页码'),
    page_size: int = Query(10, description='每页数量'),
    domain: str = Query('', description='域名搜索'),
    status: str = Query('', description='状态筛选'),
    job_type: str = Query('', description='任务类型筛选'),
):
    total, data = await hubstudio_service.list_jobs(
        page=page, page_size=page_size,
        domain=domain, status=status, job_type=job_type,
    )
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.post('/hub-job/create', summary='创建 HubStudio 任务')
async def create_hub_job(job_in: HubStudioJobCreate):
    hub_job = await hubstudio_job_controller.create(job_in)
    # 同步创建 OperationJob
    op_job = await _create_job(job_in.site_id, job_in.domain, f"hub_{job_in.job_type}")
    return Success(data={"hub_job_id": hub_job.id, "operation_job_id": op_job.id}, msg='Created Successfully')


@router.post('/hub-job/sites/{site_id}/dispatch', summary='按站点派发 HubStudio 任务（仅创建，由 Agent 执行）')
async def dispatch_hub_job(
    site_id: int,
    job_type: str = Body('create_env', embed=True),
    provider_id: int = Body(0, embed=True),
    execute_now: bool = Body(False, embed=True),
):
    job, result = await hubstudio_service.dispatch_for_site(
        site_id, job_type, provider_id=provider_id, execute_now=execute_now,
    )
    return Success(data={
        "job": await job.to_dict(),
        "result": result,
        "mode": "sync" if execute_now else "async",
    }, msg='已执行' if execute_now else 'Dispatched — 等待 Agent 领取执行')


@router.post('/hub-job/claim', summary='Agent 领取任务')
async def claim_hub_job(worker_name: str = Query(..., description='执行节点名称'),
                        provider_id: int = Query(0, description='指定 provider，0=不限制')):
    job = await hubstudio_service.claim_next_pending_job(worker_name, provider_id=provider_id if provider_id else None)
    if not job:
        return Success(data={'ok': False, 'job': None})
    return Success(data={'ok': True, 'job': await job.to_dict()})


@router.post('/hub-job/{job_id}/report', summary='Agent 回传任务结果')
async def report_hub_job(job_id: int, payload: HubStudioJobReport):
    job = await hubstudio_service.report_job_result(
        job_id, payload.status, payload.result_json,
        payload.error_message, payload.worker_name
    )
    if not job:
        return Fail(code=404, msg='job not found')
    return Success(data=await job.to_dict())


@router.post('/hub-job/{job_id}/retry', summary='重试失败任务')
async def retry_hub_job(job_id: int):
    job = await hubstudio_service.retry_job(job_id)
    if not job:
        return Fail(code=404, msg='job not found')
    return Success(data=await job.to_dict(), msg='已重置为 pending，等待 Agent 重新领取')


@router.post('/hub-job/{job_id}/cancel', summary='取消任务')
async def cancel_hub_job(job_id: int):
    try:
        job = await hubstudio_service.cancel_job(job_id)
        if not job:
            return Fail(code=404, msg='job not found')
        return Success(data=await job.to_dict(), msg='任务已取消')
    except ValueError as e:
        return Fail(code=400, msg=str(e))


@router.post('/hub-job/batch-cancel', summary='批量取消任务')
async def batch_cancel_hub_jobs(job_ids: list[int] = Body(..., embed=True)):
    result = await hubstudio_service.batch_cancel_jobs(job_ids)
    return Success(data=result, msg=f'取消完成: 成功 {result["success"]}, 失败 {result["fail"]}')


# ══════════════════════════════════════════════════════════════════════════
#  HubStudio Site 快捷入口
# ══════════════════════════════════════════════════════════════════════════

@router.post('/site/{site_id}/hub-env', summary='触发 Hub 环境创建')
async def trigger_hub_env(site_id: int, provider_id: int = Body(0, embed=True),
                           execute_now: bool = Body(False, embed=True)):
    job, result = await hubstudio_service.trigger_hub_env(site_id, provider_id=provider_id, execute_now=execute_now)
    return Success(data={
        "job": await job.to_dict(),
        "result": result,
        "mode": "sync" if execute_now else "async",
    }, msg='Hub 环境创建已执行' if execute_now else 'Hub 环境创建任务已派发（等待 Agent）')

@router.post('/site/{site_id}/hub-account', summary='触发 Hub 账号创建')
async def trigger_hub_account(site_id: int, provider_id: int = Body(0, embed=True),
                                execute_now: bool = Body(False, embed=True)):
    job, result = await hubstudio_service.trigger_hub_account(site_id, provider_id=provider_id, execute_now=execute_now)
    return Success(data={
        "job": await job.to_dict(),
        "result": result,
        "mode": "sync" if execute_now else "async",
    }, msg='Hub 账号创建已执行' if execute_now else 'Hub 账号创建任务已派发（等待 Agent）')

@router.post('/site/{site_id}/hub-update', summary='触发 Hub 环境更新')
async def trigger_hub_update(site_id: int, provider_id: int = Body(0, embed=True),
                              execute_now: bool = Body(False, embed=True)):
    job, result = await hubstudio_service.trigger_hub_update(site_id, provider_id=provider_id, execute_now=execute_now)
    return Success(data={
        "job": await job.to_dict(),
        "result": result,
        "mode": "sync" if execute_now else "async",
    }, msg='Hub 环境更新已执行' if execute_now else 'Hub 环境更新任务已派发（等待 Agent）')

@router.post('/site/{site_id}/hub-control', summary='触发 Hub 登录WP')
async def trigger_hub_control(site_id: int, provider_id: int = Body(0, embed=True),
                               execute_now: bool = Body(False, embed=True)):
    job, result = await hubstudio_service.trigger_hub_control(site_id, provider_id=provider_id, execute_now=execute_now)
    return Success(data={
        "job": await job.to_dict(),
        "result": result,
        "mode": "sync" if execute_now else "async",
    }, msg='Hub 登录WP已执行' if execute_now else 'Hub 登录WP任务已派发（等待 Agent）')

@router.post('/site/{site_id}/hub-gmc-check', summary='触发 Hub GMC 状态检查')
async def trigger_hub_gmc_check(site_id: int, provider_id: int = Body(0, embed=True),
                                 execute_now: bool = Body(False, embed=True)):
    job, result = await hubstudio_service.trigger_hub_gmc_check(site_id, provider_id=provider_id, execute_now=execute_now)
    return Success(data={
        "job": await job.to_dict(),
        "result": result,
        "mode": "sync" if execute_now else "async",
    }, msg='Hub GMC 状态检查已执行' if execute_now else 'Hub GMC 状态检查任务已派发（等待 Agent）')


# ══════════════════════════════════════════════════════════════════════════
#  Agent 心跳 & 状态
# ══════════════════════════════════════════════════════════════════════════

@router.get('/hub-job/agent-config', summary='Agent 拉取 Provider 配置（以 DB 为准）')
async def get_agent_config(provider_id: int = Query(0, description='Provider ID，0=使用默认')):
    """Agent 启动后调用，获取当前 Provider 的配置项。

    配置从数据库 config_provider / provider_config_item 读取，
    优先级：DB > 环境变量（兜底）。
    """
    config = await hubstudio_service.get_agent_config(provider_id)
    return Success(data=config)

@router.post('/hub-job/heartbeat', summary='Agent 心跳上报')
async def agent_heartbeat(
    worker_name: str = Query(..., description='节点名称'),
    provider_id: int = Query(0),
    task_id: int = Query(0),
    task_status: str = Query(''),
):
    try:
        result = await hubstudio_service.agent_heartbeat(worker_name, provider_id, task_id, task_status)
    except Exception as e:
        return Fail(msg=f"心跳写入失败: {e}")
    return Success(data=result)

@router.get('/hub-job/agents', summary='查询所有 Agent 在线状态')
async def get_agents_status():
    try:
        agents = await hubstudio_service.get_agents_status()
        any_online = any(a["online"] for a in agents)
        pending_jobs = await HubStudioJob.filter(status="pending").count()
    except Exception:
        agents = []
        any_online = False
        pending_jobs = 0
    return Success(data={
        "agents": agents,
        "any_online": any_online,
        "pending_jobs": pending_jobs,
    })