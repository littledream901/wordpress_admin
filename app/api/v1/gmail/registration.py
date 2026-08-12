"""Gmail 企业邮箱注册路由

只做路由注册、参数校验、调用 controller。
"""
from fastapi import APIRouter, Body, Query
from tortoise.expressions import Q

from app.controllers.gmail_registration import gmail_registration_controller
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.gmail_registration import (
    GmailRegistrationActionSingle,
    GmailRegistrationAssignOutlook,
    GmailRegistrationBatchAssignEnv,
    GmailRegistrationBatchAssignOutlook,
    GmailRegistrationBatchFetch,
    GmailRegistrationConfirmSms,
    GmailRegistrationCreate,
    GmailRegistrationGetPhone,
    GmailRegistrationStatusUpdate,
    GmailRegistrationUpdateTwoFaKey,
    GmailRegistrationWaitSms,
)

router = APIRouter(tags=["Gmail注册"])


# ── 列表与 CRUD ──


@router.get('/list', summary='Gmail 注册记录列表')
async def list_registration(
    page: int = Query(1),
    page_size: int = Query(10),
    alias: str = Query(''),
    domain: str = Query(''),
    registration_status: str = Query(''),
    outlook_account_username: str = Query(''),
    outlook_assigned: str = Query('', description='yes=已分配 / no=未分配'),
):
    q = Q(is_deleted=False)
    if alias:
        q &= Q(alias__contains=alias)
    if domain:
        q &= Q(domain__contains=domain)
    if registration_status:
        q &= Q(registration_status=registration_status)
    if outlook_account_username:
        q &= Q(outlook_account_username__contains=outlook_account_username)
    if outlook_assigned == 'yes':
        q &= Q(outlook_account_id__isnull=False)
    elif outlook_assigned == 'no':
        q &= Q(outlook_account_id__isnull=True)
    total, objs = await gmail_registration_controller.list(
        page=page, page_size=page_size, search=q, order=['-id']
    )
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get('/available-outlook', summary='可分配的 Outlook 账号列表')
async def available_outlook(
    keyword: str = Query('', description='按用户名模糊搜索'),
    limit: int = Query(200, le=500),
):
    data = await gmail_registration_controller.list_available_outlook(keyword=keyword, limit=limit)
    return Success(data=data)


@router.post('/create', summary='新增 Gmail 注册记录')
async def create_registration(payload: GmailRegistrationCreate):
    existed = await gmail_registration_controller.get_by_alias_domain(payload.alias, payload.domain)
    if existed:
        return Fail(code=400, msg=f'该域名下别名 {payload.alias} 已存在')
    reg = await gmail_registration_controller.create_registration(payload)
    return Success(data=await reg.to_dict(), msg='Created Successfully')


@router.post('/batch-update-status', summary='批量更新注册状态')
async def batch_update_registration_status(payload: GmailRegistrationStatusUpdate):
    count = await gmail_registration_controller.bulk_update(
        ids=payload.ids, updates={'registration_status': payload.registration_status}
    )
    return Success(data={'updated': count}, msg='Status Updated Successfully')


@router.post('/batch-delete', summary='批量删除注册记录（级联软删除 Outlook 至回收站）')
async def batch_delete_registration(ids: list[int] = Body(...)):
    result = await gmail_registration_controller.batch_soft_remove_cascade(ids)
    return Success(data=result, msg='Deleted Successfully')


@router.post('/assign-outlook', summary='分配/解绑 Outlook 邮箱')
async def assign_outlook(payload: GmailRegistrationAssignOutlook):
    result = await gmail_registration_controller.assign_outlook(
        registration_id=payload.registration_id,
        outlook_account_id=payload.outlook_account_id,
    )
    if not result.get('success'):
        return Fail(code=400, msg=result.get('error') or '分配失败')
    return Success(data=result.get('registration'), msg=result.get('message') or 'Outlook 已分配')


@router.post('/batch-assign-outlook', summary='批量自动分配 Outlook 邮箱')
async def batch_assign_outlook(payload: GmailRegistrationBatchAssignOutlook):
    result = await gmail_registration_controller.batch_assign_outlook(payload.ids)
    return Success(data=result)


@router.post('/update-two-fa-key', summary='回填 2FA Key')
async def update_two_fa_key(payload: GmailRegistrationUpdateTwoFaKey):
    reg = await gmail_registration_controller.get_or_none(id=payload.registration_id)
    if not reg:
        return Fail(code=404, msg='注册记录不存在')
    reg.two_fa_key = payload.two_fa_key.strip()
    await reg.save(update_fields=['two_fa_key', 'updated_at'])
    return Success(msg='2FA Key 已保存')


# ── 流程步骤（单条） ──


@router.post('/create-forwarding', summary='步骤1：创建 ImprovMX 转发邮箱')
async def create_forwarding(payload: GmailRegistrationActionSingle):
    result = await gmail_registration_controller.create_forwarding(payload.registration_id)
    if not result.get('success'):
        return Fail(code=400, msg=result.get('error') or '创建转发失败')
    return Success(data=result.get('registration'), msg='转发邮箱创建成功')





@router.post('/get-phone', summary='步骤3：获取 SMS 号码')
async def get_phone(payload: GmailRegistrationGetPhone):
    result = await gmail_registration_controller.get_phone_number(
        registration_id=payload.registration_id,
        country_id=payload.country_id,
        application_id=payload.application_id,
        max_price=payload.max_price,
    )
    if not result.get('success'):
        return Fail(code=400, msg=result.get('error') or '获取号码失败')
    return Success(data=result.get('registration'), msg='号码获取成功')


@router.post('/wait-sms', summary='步骤4：等待 SMS 验证码')
async def wait_sms(payload: GmailRegistrationWaitSms):
    result = await gmail_registration_controller.wait_for_sms(
        registration_id=payload.registration_id,
        timeout=payload.timeout,
        interval=payload.interval,
    )
    if not result.get('success'):
        return Fail(code=400, msg=result.get('error') or '等待验证码失败')
    return Success(data=result.get('registration'), msg='验证码接收成功')


@router.post('/confirm-sms', summary='步骤5：确认 SMS 使用完成')
async def confirm_sms(payload: GmailRegistrationConfirmSms):
    result = await gmail_registration_controller.confirm_sms(
        registration_id=payload.registration_id,
        status=payload.status,
    )
    if not result.get('success'):
        return Fail(code=400, msg=result.get('error') or '确认失败')
    return Success(data=result.get('registration'), msg='SMS 已确认')


# ── 批量流程操作 ──


@router.post('/batch-create-forwarding', summary='批量创建转发邮箱')
async def batch_create_forwarding(ids: list[int] = Body(...)):
    result = await gmail_registration_controller.batch_create_forwarding(ids)
    return Success(data=result)





@router.post('/batch-get-phone', summary='批量获取 SMS 号码')
async def batch_get_phone(ids: list[int] = Body(...)):
    result = await gmail_registration_controller.batch_get_phone(ids)
    return Success(data=result)


@router.post('/batch-wait-sms', summary='批量等待 SMS 验证码')
async def batch_wait_sms(ids: list[int] = Body(...), timeout: int = Query(60)):
    result = await gmail_registration_controller.batch_wait_sms(ids, timeout=timeout)
    return Success(data=result)


@router.post('/batch-confirm-sms', summary='批量确认 SMS 完成')
async def batch_confirm_sms(ids: list[int] = Body(...)):
    result = await gmail_registration_controller.batch_confirm_sms(ids)
    return Success(data=result)


# ── 批量获取与分配 ──


@router.post('/batch-fetch', summary='批量获取待注册站点')
async def batch_fetch(payload: GmailRegistrationBatchFetch):
    result = await gmail_registration_controller.batch_fetch_pending_sites(
        alias=payload.alias,
    )
    return Success(data=result)


@router.post('/batch-assign-env', summary='批量分配环境到站点')
async def batch_assign_env(payload: GmailRegistrationBatchAssignEnv):
    result = await gmail_registration_controller.batch_assign_env_to_sites(payload.ids)
    return Success(data=result)
