import json
from typing import Optional

from app.core.crud import CRUDBase
from app.models.site_pipeline import HubStudioJob, Site
from app.schemas.site_pipeline import HubStudioJobCreate, SiteCreate, SiteUpdate


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

    async def report_job(self, job_id: int, status: str, result_json: str, error_message: str, worker_name: str) -> Optional[HubStudioJob]:
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
