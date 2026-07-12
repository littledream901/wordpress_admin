from app.core.crud import CRUDBase
from app.models.import_job import ImportJob
from app.schemas.import_job import ImportJobCreate, ImportJobUpdate


class ImportJobController(CRUDBase[ImportJob, ImportJobCreate, ImportJobUpdate]):
    def __init__(self):
        super().__init__(model=ImportJob)

    async def finish(self, id: int, success_count: int, fail_count: int,
                     error_report: str = ""):
        status = "success" if fail_count == 0 else ("partial" if success_count > 0 else "failed")
        await self.model.filter(id=id).update(
            status=status, success_count=success_count,
            fail_count=fail_count, error_report=error_report
        )


import_job_controller = ImportJobController()
