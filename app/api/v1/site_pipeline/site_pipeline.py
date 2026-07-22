"""站点流水线 API —— 站点 CRUD / 批量操作 / DNS / 建站 / Dynadot / HubStudio / 产品导入"""
import asyncio
import logging
import time

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel

from app.controllers.site_pipeline import (
    hubstudio_job_controller,
    hubstudio_service,
    site_controller,
    site_pipeline_controller,
)
from app.core.dependency import AuthControl
from app.models.admin import User
from app.models.operation_job import OperationJob
from app.models.site_pipeline import HubStudioJob
from app.schemas.base import Fail, Success, SuccessExtra
from app.utils.db_utils import safe_count
from app.schemas.site_pipeline import (
    HubStudioJobCreate, HubStudioJobReport,
    SiteBatchCreate, SiteCreate, SiteUpdate,
)

_log = logging.getLogger(__name__)

router = APIRouter(tags=["SitePipeline"])


# ══════════════════════════════════════════════════════════════════════════
#  站点 CRUD
# ══════════════════════════════════════════════════════════════════════════

@router.get('/site/list', summary='查看站点列表')
async def list_sites(
    page: int = Query(1, description='页码'),
    page_size: int = Query(10, description='每页数量'),
    domain: str = Query('', description='域名搜索'),
    dept_id: int = Query(None, description='按部门筛选'),
    assign_to: int = Query(None, description='按归属用户筛选'),
    gmc_status: str = Query('', description='GMC状态筛选'),
    status: str = Query('', description='站点状态筛选'),
    current_user: User = Depends(AuthControl.is_authed),
):
    result = await site_pipeline_controller.list_sites_with_enrichment(
        page=page, page_size=page_size,
        domain=domain, dept_id=dept_id, assign_to=assign_to,
        gmc_status=gmc_status, status=status,
        current_user=current_user,
    )
    return SuccessExtra(
        data=result["data"], total=result["total"],
        page=result["page"], page_size=result["page_size"],
    )


@router.get('/site/get', summary='查看站点详情')
async def get_site(site_id: int = Query(..., description='站点ID')):
    data = await site_pipeline_controller.get_site_detail(site_id)
    return Success(data=data)


@router.post('/site/create', summary='创建站点记录')
async def create_site(site_in: SiteCreate, current_user: User = Depends(AuthControl.is_authed)):
    result = await site_pipeline_controller.create_site_with_permission(site_in, current_user)
    if result['ok']:
        return Success(data=result['data'], msg='Created Successfully')
    return Fail(code=result.get('code', 400), msg=result.get('error'))


@router.post('/site/update', summary='更新站点')
async def update_site(site_in: SiteUpdate):
    await site_controller.update(id=site_in.id, obj_in=site_in)
    return Success(msg='Updated Successfully')


@router.post('/site/delete', summary='删除站点（同时异步删除 1Panel 网站）')
async def delete_site(site_id: int = Query(...)):
    site = await site_controller.get_or_none(id=site_id)
    result = await site_pipeline_controller.delete_site(site_id)
    if site:
        from app.services.operation_job_service import operation_job_service
        await operation_job_service.create_task(
            resource_type="site", resource_id=site.id,
            action_type="delete_site", domain=site.domain,
        )
    return Success(msg='已移入回收站')


# ══════════════════════════════════════════════════════════════════════════
#  站点批量操作
# ══════════════════════════════════════════════════════════════════════════

@router.post('/site/batch-create', summary='批量新增站点（异步）')
async def batch_create_sites(payload: SiteBatchCreate, current_user: User = Depends(AuthControl.is_authed)):
    batch_id = f"create-{int(time.time())}"
    job = await site_pipeline_controller._create_job(0, f"batch-{batch_id}", "batch_create",
                                                      batch_id=batch_id, total_steps=len(payload.items))
    asyncio.create_task(site_pipeline_controller.batch_create_sites_bg(
        payload.items, job.id, current_user.id, current_user.dept_id,
    ))
    return Success(data={"batch_id": batch_id, "job_id": job.id, "total": len(payload.items), "status": "submitted"})


@router.post('/site/batch-delete', summary='批量删除站点（异步删除 1Panel 网站并创建追踪任务）')
async def batch_delete_sites(ids: list[int] = Body(...)):
    result = await site_pipeline_controller.batch_delete_sites(ids)
    if result['ok']:
        data = result['data']
        return Success(data=data,
                       msg=f'已删除 {data["deleted"]} 条记录，1Panel 删除在后台进行，请在任务中心查看进度')
    return Fail(code=500, msg='batch delete failed')


class BatchAssignPayload(BaseModel):
    site_ids: list[int]
    dept_id: int | None = None
    assign_to: int | None = None


@router.post('/site/batch-assign', summary='批量分配站点（部门或用户）')
async def batch_assign_sites(payload: BatchAssignPayload):
    data = await site_pipeline_controller.batch_assign_sites(
        payload.site_ids, dept_id=payload.dept_id, assign_to=payload.assign_to,
    )
    return Success(data=data)


@router.post('/site/batch-dns', summary='批量执行 DNS + NS（Cloudflare 解析 + Dynadot NS 修改）')
async def batch_dns(site_ids: list[int] = Body(...)):
    result = await site_pipeline_controller.batch_dns(site_ids)
    data = result['data']
    return Success(data=data, msg=f'已提交 {data["total"]} 个 DNS 任务，请在任务中心查看进度')


@router.post('/site/batch-provision', summary='批量执行 1Panel 建站')
async def batch_provision(site_ids: list[int] = Body(...)):
    batch_id = f"provision-{int(time.time())}"
    result = await site_pipeline_controller.batch_provision(site_ids, batch_id)
    data = result['data']
    return Success(data=data)


@router.post('/site/batch-redirect', summary='批量执行 301 重定向（根域名 + www 各一条规则）')
async def batch_redirect(site_ids: list[int] = Body(...), target_url: str = Body('')):
    result = await site_pipeline_controller.batch_redirect(site_ids, target_url)
    data = result['data']
    return Success(data=data)


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
            hub_job, _ = await hubstudio_service.dispatch_for_site(site_id, job_type)
            results.append({"site_id": site_id, "domain": site.domain, "ok": True,
                          "hub_job_id": hub_job.id, "status": "pending"})
        except Exception as e:
            results.append({"site_id": site_id, "domain": site.domain, "ok": False, "error": str(e)})
    return Success(data={"batch_id": batch_id, "results": results, "total": len(results),
                         "success": sum(1 for r in results if r["ok"]),
                         "fail": sum(1 for r in results if not r["ok"])})


@router.post('/site/batch-woo-import', summary='批量产品导入')
async def batch_import_products(site_ids: list[int] = Body(...)):
    result = await site_pipeline_controller.batch_import_products(site_ids)
    data = result['data']
    return Success(data=data)


# ══════════════════════════════════════════════════════════════════════════
#  单条操作端点
# ══════════════════════════════════════════════════════════════════════════

@router.post('/site/{site_id}/provision', summary='触发 1Panel 建站')
async def provision_site(site_id: int):
    result = await site_pipeline_controller.provision_site(site_id)
    if result['ok']:
        return Success(data=result['data'], msg='建站已触发')
    return Fail(code=result.get('code', 400), msg=result.get('error'))


@router.post('/site/{site_id}/dns', summary='触发 Cloudflare DNS + NS（含自动 Dynadot NS 修改）')
async def provision_dns(site_id: int):
    result = await site_pipeline_controller.provision_dns(site_id)
    if result['ok']:
        return Success(data=result['data'], msg='DNS 任务已提交，请在任务中心查看进度')
    return Fail(code=result.get('code', 400), msg=result.get('error'))


@router.post('/site/{site_id}/dynadot-ns', summary='触发 Dynadot NS 修改（独立操作，手动指定 NS）')
async def set_dynadot_ns(site_id: int, ns_list: list[str] = Body(None)):
    result = await site_pipeline_controller.set_dynadot_ns(site_id, ns_list)
    if result['ok']:
        return Success(data=result['data'], msg='Dynadot NS updated')
    return Fail(code=result.get('code', 500), msg=result.get('error'))


@router.post('/site/{site_id}/redirect', summary='触发 301 重定向（根域名 + www 各一条）')
async def provision_redirect(site_id: int, target_url: str = Body('', embed=True)):
    result = await site_pipeline_controller.provision_redirect(site_id, target_url)
    if result['ok']:
        return Success(data=result['data'], msg='Redirect triggered')
    return Fail(code=result.get('code', 500), msg=str(result.get('error')))


@router.post('/site/{site_id}/woo-import', summary='触发产品导入')
async def import_products(site_id: int):
    result = await site_pipeline_controller.import_products(site_id)
    if result['ok']:
        return Success(data=result['data'], msg=f'正在导入 {result["data"]["total"]} 个产品，请在任务中心查看进度')
    return Fail(code=result.get('code', 400), msg=result.get('error'))


@router.post('/site/{site_id}/inject-mu-plugins', summary='注入 mu-plugins（异步图片下载钩子）')
async def inject_mu_plugins(site_id: int):
    result = await site_pipeline_controller.inject_mu_plugins(site_id)
    if result['ok']:
        return Success(msg=result['msg'])
    return Fail(code=result.get('code', 500), msg=result.get('error'))


@router.post('/site/{site_id}/refresh-woo-count', summary='同步站点远端产品数量')
async def refresh_product_count(site_id: int):
    result = await site_pipeline_controller.refresh_product_count(site_id)
    if result['ok']:
        return Success(data=result['data'], msg=f'远端产品总数: {result["data"]["product_count"]}')
    return Fail(code=result.get('code', 500), msg=result.get('error'))


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
    op_job = await site_pipeline_controller._create_job(job_in.site_id, job_in.domain, f"hub_{job_in.job_type}")
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
        payload.error_message, payload.worker_name,
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
    return Success(data={"job": await job.to_dict(), "result": result,
                         "mode": "sync" if execute_now else "async"},
                   msg='Hub 环境创建已执行' if execute_now else 'Hub 环境创建任务已派发（等待 Agent）')


@router.post('/site/{site_id}/hub-account', summary='触发 Hub 账号创建')
async def trigger_hub_account(site_id: int, provider_id: int = Body(0, embed=True),
                                execute_now: bool = Body(False, embed=True)):
    job, result = await hubstudio_service.trigger_hub_account(site_id, provider_id=provider_id, execute_now=execute_now)
    return Success(data={"job": await job.to_dict(), "result": result,
                         "mode": "sync" if execute_now else "async"},
                   msg='Hub 账号创建已执行' if execute_now else 'Hub 账号创建任务已派发（等待 Agent）')


@router.post('/site/{site_id}/hub-update', summary='触发 Hub 环境更新')
async def trigger_hub_update(site_id: int, provider_id: int = Body(0, embed=True),
                              execute_now: bool = Body(False, embed=True)):
    job, result = await hubstudio_service.trigger_hub_update(site_id, provider_id=provider_id, execute_now=execute_now)
    return Success(data={"job": await job.to_dict(), "result": result,
                         "mode": "sync" if execute_now else "async"},
                   msg='Hub 环境更新已执行' if execute_now else 'Hub 环境更新任务已派发（等待 Agent）')


@router.post('/site/{site_id}/hub-control', summary='触发 Hub 登录WP')
async def trigger_hub_control(site_id: int, provider_id: int = Body(0, embed=True),
                               execute_now: bool = Body(False, embed=True)):
    job, result = await hubstudio_service.trigger_hub_control(site_id, provider_id=provider_id, execute_now=execute_now)
    return Success(data={"job": await job.to_dict(), "result": result,
                         "mode": "sync" if execute_now else "async"},
                   msg='Hub 登录WP已执行' if execute_now else 'Hub 登录WP任务已派发（等待 Agent）')


@router.post('/site/{site_id}/hub-gmc-check', summary='触发 Hub GMC 状态检查')
async def trigger_hub_gmc_check(site_id: int, provider_id: int = Body(0, embed=True),
                                 execute_now: bool = Body(False, embed=True)):
    job, result = await hubstudio_service.trigger_hub_gmc_check(site_id, provider_id=provider_id, execute_now=execute_now)
    return Success(data={"job": await job.to_dict(), "result": result,
                         "mode": "sync" if execute_now else "async"},
                   msg='Hub GMC 状态检查已执行' if execute_now else 'Hub GMC 状态检查任务已派发（等待 Agent）')


@router.post('/site/{site_id}/hub-open-env', summary='打开 Hub 浏览器环境')
async def trigger_hub_open_env(site_id: int, provider_id: int = Body(0, embed=True),
                                execute_now: bool = Body(False, embed=True)):
    job, result = await hubstudio_service.trigger_hub_open_env(site_id, provider_id=provider_id, execute_now=execute_now)
    return Success(data={"job": await job.to_dict(), "result": result},
                   msg='浏览器环境已打开' if result else '打开环境任务已派发（等待 Agent）')


# ══════════════════════════════════════════════════════════════════════════
#  Agent 心跳 & 状态
# ══════════════════════════════════════════════════════════════════════════

@router.get('/hub-job/agent-config', summary='Agent 拉取 Provider 配置（以 DB 为准）')
async def get_agent_config(provider_id: int = Query(0, description='Provider ID，0=使用默认')):
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
        pending_jobs = await safe_count(HubStudioJob.filter(status="pending"))
    except Exception:
        agents = []
        any_online = False
        pending_jobs = 0
    return Success(data={"agents": agents, "any_online": any_online, "pending_jobs": pending_jobs})
