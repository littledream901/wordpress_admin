from fastapi import APIRouter, Body, Query
from datetime import datetime
import json
from tortoise.expressions import Q

from app.controllers.gmail_account import gmail_account_controller
from app.models.operation_job import OperationJob
from app.models.site_pipeline import Site
from app.models.gmail_account import GmailAccount
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.gmail_account import GmailAccountCreate, GmailAccountUpdate, GmailAssign, GmailHealthStatus

router = APIRouter()


@router.get('/list', summary='Gmail 列表')
async def list_gmail(page: int = Query(1), page_size: int = Query(10), username: str = Query(''),
                     unassigned_only: bool = Query(False, description='只显示未分配的 Gmail')):
    q = Q()
    if username:
        q &= Q(username__contains=username)
    if unassigned_only:
        q &= Q(assigned_site_id__isnull=True)
    total, objs = await gmail_account_controller.list(page=page, page_size=page_size, search=q, order=['-id'])
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.post('/create', summary='新增 Gmail 账号')
async def create_gmail(payload: GmailAccountCreate):
    existed = await gmail_account_controller.get_by_username(payload.username)
    if existed:
        return Fail(code=400, msg='username already exists')
    await gmail_account_controller.create(payload)
    return Success(msg='Created Successfully')


@router.post('/update', summary='更新 Gmail 账号')
async def update_gmail(payload: GmailAccountUpdate):
    await gmail_account_controller.update(id=payload.id, obj_in=payload)
    return Success(msg='Updated Successfully')


@router.post('/assign', summary='分配 Gmail 到站点')
async def assign_gmail(payload: GmailAssign):
    gmail, site = await gmail_account_controller.assign_to_site(payload.gmail_id, payload.site_id)
    if not gmail or not site:
        return Fail(code=404, msg='gmail or site not found')
    if gmail.status == '不正常':
        return Fail(code=400, msg='该 Gmail 健康状态不正常，禁止分配')
    # 创建 OperationJob 追踪
    await OperationJob.create(
        resource_type="gmail", resource_id=gmail.id,
        domain=site.domain, action_type="assign_gmail",
        status="success", started_at=datetime.now(), finished_at=datetime.now(),
        result_json=json.dumps({"gmail_id": gmail.id, "site_id": site.id, "username": gmail.username}, ensure_ascii=False),
    )
    return Success(data={'gmail': await gmail.to_dict(), 'site': await site.to_dict()}, msg='Assigned Successfully')


@router.post('/batch-create', summary='批量新增 Gmail 账号')
async def batch_create_gmail(items: list[GmailAccountCreate] = Body(...)):
    success, fail = 0, 0
    results = []
    for item in items:
        try:
            existed = await gmail_account_controller.get_by_username(item.username)
            if existed:
                results.append({'username': item.username, 'status': 'skipped', 'reason': '已存在'})
                fail += 1
                continue
            await gmail_account_controller.create(item)
            results.append({'username': item.username, 'status': 'success'})
            success += 1
        except Exception as e:
            results.append({'username': item.username, 'status': 'failed', 'reason': str(e)})
            fail += 1
    return Success(data={'success': success, 'fail': fail, 'results': results})


@router.post('/batch-assign', summary='批量分配 Gmail 到站点')
async def batch_assign_gmail(gmail_ids: list[int] = Body(...), site_id: int = Body(...)):
    site = await Site.filter(id=site_id).first()
    if not site:
        return Fail(code=404, msg='site not found')
    success = 0
    for gid in gmail_ids:
        gmail, _ = await gmail_account_controller.assign_to_site(gid, site_id)
        if gmail:
            await OperationJob.create(
                resource_type="gmail", resource_id=gmail.id,
                domain=site.domain, action_type="assign_gmail",
                status="success", started_at=datetime.now(), finished_at=datetime.now(),
                result_json=json.dumps({"gmail_id": gmail.id, "site_id": site_id, "username": gmail.username}, ensure_ascii=False),
            )
            success += 1
    return Success(data={'site_id': site_id, 'assigned': success})


@router.post('/batch-delete', summary='批量删除 Gmail 账号')
async def batch_delete_gmail(ids: list[int] = Body(...)):
    count = 0
    for gid in ids:
        try:
            await gmail_account_controller.remove(id=gid)
            count += 1
        except Exception:
            pass
    return Success(data={'deleted': count})


@router.post('/unassign', summary='取消站点已分配的 Gmail')
async def unassign_gmail(site_id: int = Body(..., embed=True)):
    """取消指定站点已分配的 Gmail，将 Gmail 恢复为未分配状态"""
    gmail = await gmail_account_controller.unassign_from_site(site_id)
    if not gmail:
        return Fail(code=404, msg='该站点没有已分配的 Gmail')
    return Success(data={'gmail': await gmail.to_dict(), 'site_id': site_id}, msg='Unassigned Successfully')


@router.post('/auto-assign', summary='自动分配未使用的 Gmail 到站点')
async def auto_assign_gmail(site_id: int = Body(..., embed=True)):
    """自动获取第一个未分配的 Gmail 并分配给指定站点"""
    gmail, site = await gmail_account_controller.auto_assign_to_site(site_id)
    if not site:
        return Fail(code=404, msg='site not found')
    if not gmail:
        return Fail(code=404, msg='没有可用的 Gmail 账号了')
    await OperationJob.create(
        resource_type="gmail", resource_id=gmail.id,
        domain=site.domain, action_type="assign_gmail",
        status="success", started_at=datetime.now(), finished_at=datetime.now(),
        result_json=json.dumps({"gmail_id": gmail.id, "site_id": site.id, "username": gmail.username}, ensure_ascii=False),
    )
    return Success(data={'gmail': await gmail.to_dict(), 'site_id': site.id}, msg='Auto Assigned Successfully')


@router.post('/batch-auto-assign', summary='批量自动分配 Gmail 到多个站点')
async def batch_auto_assign_gmail(site_ids: list[int] = Body(..., embed=True)):
    """为每个站点自动分配一个未使用的 Gmail（已有 Gmail 的站点自动跳过）"""
    results = []
    for site_id in site_ids:
        try:
            site = await Site.filter(id=site_id).first()
            if not site:
                results.append({"site_id": site_id, "ok": False, "error": "site not found"})
                continue
            # 跳过已有 Gmail 分配的站点
            if await GmailAccount.filter(assigned_site_id=site_id).exists():
                results.append({"site_id": site_id, "domain": site.domain, "ok": False, "error": "已有 Gmail 分配"})
                continue
            gmail, _ = await gmail_account_controller.auto_assign_to_site(site_id)
            if gmail:
                await OperationJob.create(
                    resource_type="gmail", resource_id=gmail.id,
                    domain=site.domain, action_type="assign_gmail",
                    status="success", started_at=datetime.now(), finished_at=datetime.now(),
                    result_json=json.dumps({"gmail_id": gmail.id, "site_id": site_id, "username": gmail.username}, ensure_ascii=False),
                )
                results.append({"site_id": site_id, "domain": site.domain, "ok": True, "gmail": gmail.username})
            else:
                results.append({"site_id": site_id, "domain": site.domain, "ok": False, "error": "没有可用 Gmail"})
        except Exception as e:
            results.append({"site_id": site_id, "ok": False, "error": str(e)})
    return Success(data={"results": results, "total": len(results),
                         "success": sum(1 for r in results if r["ok"]),
                         "fail": sum(1 for r in results if not r["ok"])})


@router.post('/set-health', summary='设置 Gmail 健康状态')
async def set_health_status(payload: GmailHealthStatus):
    gmail = await gmail_account_controller.get(id=payload.id)
    if not gmail:
        return Fail(code=404, msg='gmail not found')
    gmail.status = payload.status
    await gmail.save()
    return Success(data=await gmail.to_dict(), msg=f'健康状态已更新为 {payload.status}')
