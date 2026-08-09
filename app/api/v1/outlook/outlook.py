"""Outlook 账号管理路由 — 逻辑与 Gmail 老号一致"""
import json
from datetime import datetime

from fastapi import APIRouter, Body, Query
from tortoise.expressions import Q

from app.controllers.outlook_account import outlook_account_controller
from app.models.operation_job import OperationJob
from app.models.outlook_account import OutlookAccount
from app.models.site_pipeline import Site
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.outlook_account import (
    OutlookAccountCreate,
    OutlookAccountUpdate,
    OutlookAssign,
    OutlookHealthStatus,
)
from app.services.operation_job_service import operation_job_service

router = APIRouter(tags=["Outlook"])


@router.get('/list', summary='Outlook 列表')
async def list_outlook(page: int = Query(1), page_size: int = Query(10), username: str = Query(''),
                       unassigned_only: bool = Query(False, description='只显示未分配的 Outlook')):
    q = Q(is_deleted=False)
    if username:
        q &= Q(username__contains=username)
    if unassigned_only:
        q &= Q(assigned_site_id__isnull=True)
    total, objs = await outlook_account_controller.list(page=page, page_size=page_size, search=q, order=['-id'])
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.post('/create', summary='新增 Outlook 账号')
async def create_outlook(payload: OutlookAccountCreate):
    existed = await outlook_account_controller.get_by_username(payload.username)
    if existed:
        return Fail(code=400, msg='username already exists')
    await outlook_account_controller.create(payload)
    return Success(msg='Created Successfully')


@router.post('/update', summary='更新 Outlook 账号')
async def update_outlook(payload: OutlookAccountUpdate):
    await outlook_account_controller.update(id=payload.id, obj_in=payload)
    return Success(msg='Updated Successfully')


@router.post('/assign', summary='分配 Outlook 到站点')
async def assign_outlook(payload: OutlookAssign):
    outlook, site = await outlook_account_controller.assign_to_site(payload.outlook_id, payload.site_id)
    if not outlook or not site:
        return Fail(code=404, msg='outlook or site not found')
    if outlook.status == '不正常':
        return Fail(code=400, msg='该 Outlook 健康状态不正常，禁止分配')
    await OperationJob.create(
        resource_type="outlook", resource_id=outlook.id,
        domain=site.domain, action_type="assign_outlook",
        status="success", started_at=datetime.now(), finished_at=datetime.now(),
        result_json=json.dumps({"outlook_id": outlook.id, "site_id": site.id, "username": outlook.username}, ensure_ascii=False),
    )
    return Success(data={'outlook': await outlook.to_dict(), 'site': await site.to_dict()}, msg='Assigned Successfully')


@router.post('/batch-create', summary='批量新增 Outlook 账号')
async def batch_create_outlook(items: list[OutlookAccountCreate] = Body(...)):
    success, fail = 0, 0
    results = []
    for item in items:
        try:
            existed = await outlook_account_controller.get_by_username(item.username)
            if existed:
                results.append({'username': item.username, 'status': 'skipped', 'reason': '已存在'})
                fail += 1
                continue
            await outlook_account_controller.create(item)
            results.append({'username': item.username, 'status': 'success'})
            success += 1
        except Exception as e:
            results.append({'username': item.username, 'status': 'failed', 'reason': str(e)})
            fail += 1
    return Success(data={'success': success, 'fail': fail, 'results': results})


@router.post('/batch-assign', summary='批量分配 Outlook 到站点')
async def batch_assign_outlook(outlook_ids: list[int] = Body(...), site_id: int = Body(...)):
    site = await Site.filter(id=site_id).first()
    if not site:
        return Fail(code=404, msg='site not found')
    success = 0
    for oid in outlook_ids:
        outlook, _ = await outlook_account_controller.assign_to_site(oid, site_id)
        if outlook:
            await OperationJob.create(
                resource_type="outlook", resource_id=outlook.id,
                domain=site.domain, action_type="assign_outlook",
                status="success", started_at=datetime.now(), finished_at=datetime.now(),
                result_json=json.dumps({"outlook_id": outlook.id, "site_id": site_id, "username": outlook.username}, ensure_ascii=False),
            )
            success += 1
    return Success(data={'site_id': site_id, 'assigned': success})


@router.post('/batch-delete', summary='批量删除 Outlook 账号')
async def batch_delete_outlook(ids: list[int] = Body(...)):
    count = 0
    for oid in ids:
        try:
            outlook = await outlook_account_controller.get_or_none(id=oid)
            await outlook_account_controller.soft_remove(id=oid)
            if outlook:
                await operation_job_service.create_task(
                    resource_type="outlook", resource_id=oid,
                    action_type="delete_outlook", domain=outlook.username,
                )
            count += 1
        except Exception:
            pass
    return Success(data={'deleted': count}, msg='已移入回收站')


@router.post('/unassign', summary='取消站点已分配的 Outlook')
async def unassign_outlook(site_id: int = Body(..., embed=True)):
    """取消指定站点已分配的 Outlook，将 Outlook 恢复为未分配状态"""
    outlook = await outlook_account_controller.unassign_from_site(site_id)
    if not outlook:
        return Fail(code=404, msg='该站点没有已分配的 Outlook')
    await operation_job_service.create_task(
        resource_type="outlook", resource_id=outlook.id,
        action_type="unassign_outlook", domain=outlook.username,
        payload={"site_id": site_id},
    )
    return Success(data={'outlook': await outlook.to_dict(), 'site_id': site_id}, msg='Unassigned Successfully')


@router.post('/auto-assign', summary='自动分配未使用的 Outlook 到站点')
async def auto_assign_outlook(site_id: int = Body(..., embed=True)):
    """自动获取第一个未分配的 Outlook 并分配给指定站点"""
    outlook, site = await outlook_account_controller.auto_assign_to_site(site_id)
    if not site:
        return Fail(code=404, msg='site not found')
    if not outlook:
        return Fail(code=404, msg='没有可用的 Outlook 账号了')
    await OperationJob.create(
        resource_type="outlook", resource_id=outlook.id,
        domain=site.domain, action_type="assign_outlook",
        status="success", started_at=datetime.now(), finished_at=datetime.now(),
        result_json=json.dumps({"outlook_id": outlook.id, "site_id": site.id, "username": outlook.username}, ensure_ascii=False),
    )
    return Success(data={'outlook': await outlook.to_dict(), 'site_id': site.id}, msg='Auto Assigned Successfully')


@router.post('/batch-auto-assign', summary='批量自动分配 Outlook 到多个站点')
async def batch_auto_assign_outlook(site_ids: list[int] = Body(..., embed=True)):
    """为每个站点自动分配一个未使用的 Outlook（已有 Outlook 的站点自动跳过）"""
    results = []
    for site_id in site_ids:
        try:
            site = await Site.filter(id=site_id).first()
            if not site:
                results.append({"site_id": site_id, "ok": False, "error": "site not found"})
                continue
            if await OutlookAccount.filter(assigned_site_id=site_id, is_deleted=False).exists():
                results.append({"site_id": site_id, "domain": site.domain, "ok": False, "error": "已有 Outlook 分配"})
                continue
            outlook, _ = await outlook_account_controller.auto_assign_to_site(site_id)
            if outlook:
                await OperationJob.create(
                    resource_type="outlook", resource_id=outlook.id,
                    domain=site.domain, action_type="assign_outlook",
                    status="success", started_at=datetime.now(), finished_at=datetime.now(),
                    result_json=json.dumps({"outlook_id": outlook.id, "site_id": site_id, "username": outlook.username}, ensure_ascii=False),
                )
                results.append({"site_id": site_id, "domain": site.domain, "ok": True, "outlook": outlook.username})
            else:
                results.append({"site_id": site_id, "domain": site.domain, "ok": False, "error": "没有可用 Outlook"})
        except Exception as e:
            results.append({"site_id": site_id, "ok": False, "error": str(e)})
    return Success(data={"results": results, "total": len(results),
                         "success": sum(1 for r in results if r["ok"]),
                         "fail": sum(1 for r in results if not r["ok"])})


@router.post('/set-health', summary='设置 Outlook 健康状态')
async def set_health_status(payload: OutlookHealthStatus):
    outlook = await outlook_account_controller.get(id=payload.id)
    if not outlook:
        return Fail(code=404, msg='outlook not found')
    outlook.status = payload.status
    await outlook.save()
    return Success(data=await outlook.to_dict(), msg=f'健康状态已更新为 {payload.status}')
