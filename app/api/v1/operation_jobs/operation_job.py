from fastapi import APIRouter, Query

from app.controllers.operation_job import operation_job_controller
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.operation_job import BatchOperationCreate, OperationJobUpdate
from app.utils.db_utils import safe_count

router = APIRouter(tags=["OperationJob"])


@router.get('/list', summary='任务列表')
async def list_jobs(
    resource_type: str = Query('', description='资源类型'),
    resource_id: int = Query(None, description='资源ID'),
    action_type: str = Query('', description='操作类型'),
    status: str = Query('', description='任务状态'),
    batch_id: str = Query('', description='批次ID'),
    page: int = Query(1, description='页码'),
    page_size: int = Query(20, description='每页数量'),
):
    qs = operation_job_controller.model.all()
    if resource_type:
        qs = qs.filter(resource_type=resource_type)
    if resource_id:
        qs = qs.filter(resource_id=resource_id)
    if action_type:
        qs = qs.filter(action_type=action_type)
    if status:
        qs = qs.filter(status=status)
    if batch_id:
        qs = qs.filter(batch_id=batch_id)
    total = await safe_count(qs)
    objs = await qs.order_by('-created_at').offset((page - 1) * page_size).limit(page_size)
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get('/get', summary='查看任务详情')
async def get_job(id: int = Query(...)):
    obj = await operation_job_controller.get(id=id)
    if not obj:
        return Fail(code=404, msg='任务不存在')
    return Success(data=await obj.to_dict())


@router.post('/batch-create', summary='批量创建任务')
async def batch_create_jobs(payload: BatchOperationCreate):
    jobs = await operation_job_controller.batch_create(
        resource_type=payload.resource_type,
        resource_ids=payload.resource_ids,
        action_type=payload.action_type,
        domains=payload.domains,
        payload=payload.payload,
    )
    return Success(data={'count': len(jobs), 'batch_id': jobs[0].batch_id if jobs else ''})


@router.post('/update', summary='更新任务状态')
async def update_job(payload: OperationJobUpdate):
    await operation_job_controller.update(id=payload.id, obj_in=payload)
    return Success(msg='更新成功')


@router.post('/claim', summary='领取任务')
async def claim_job(action_type: str = Query(''), worker_name: str = Query('worker')):
    job = await operation_job_controller.claim_next_pending(
        action_type=action_type or None, worker_name=worker_name
    )
    if not job:
        return Fail(code=404, msg='没有可领取的任务')
    return Success(data=await job.to_dict())


@router.post('/report', summary='上报任务结果')
async def report_job(
    job_id: int = Query(...),
    success: bool = Query(True),
    result: str = Query('{}'),
    error_message: str = Query(''),
    step: int = Query(None),
):
    import json
    result_dict = json.loads(result) if result else {}
    await operation_job_controller.report_result(
        job_id=job_id, success=success, result=result_dict,
        error_message=error_message, step=step
    )
    return Success(msg='上报成功')


@router.post('/cancel', summary='取消任务')
async def cancel_job(id: int = Query(...)):
    await operation_job_controller.model.filter(id=id).update(status='cancelled')
    return Success(msg='已取消')
