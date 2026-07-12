from app.core.crud import CRUDBase
from app.models.operation_job import OperationJob
from app.schemas.operation_job import OperationJobCreate, OperationJobUpdate


class OperationJobController(CRUDBase[OperationJob, OperationJobCreate, OperationJobUpdate]):
    def __init__(self):
        super().__init__(model=OperationJob)

    async def get_by_resource(self, resource_type: str, resource_id: int):
        return await self.model.filter(
            resource_type=resource_type, resource_id=resource_id
        ).order_by('-created_at').all()

    async def get_by_batch(self, batch_id: str):
        return await self.model.filter(batch_id=batch_id).order_by('id').all()

    async def claim_next_pending(self, action_type: str = None, worker_name: str = "worker"):
        """Worker 领取下一个待执行任务"""
        qs = self.model.filter(status="pending")
        if action_type:
            qs = qs.filter(action_type=action_type)
        job = await qs.order_by('id').first()
        if job:
            job.status = "running"
            job.worker_name = worker_name
            await job.save(update_fields=["status", "worker_name"])
        return job

    async def report_result(self, job_id: int, success: bool, result: dict = None,
                            error_message: str = "", step: int = None):
        """Worker 上报任务结果"""
        update_kw = {"status": "success" if success else "failed", "error_message": error_message}
        if result:
            update_kw["result_json"] = str(result)
        if step is not None:
            update_kw["step"] = step
        await self.model.filter(id=job_id).update(**update_kw)
        return True

    async def batch_create(self, resource_type: str, resource_ids: list[int], action_type: str,
                           domains: list[str] = None, payload: dict = None) -> list[OperationJob]:
        return await OperationJob.create_batch(resource_type, resource_ids, action_type, domains, payload)


operation_job_controller = OperationJobController()
