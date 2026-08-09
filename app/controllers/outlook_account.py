"""Outlook 账号 Controller"""
from app.core.crud import CRUDBase
from app.models.outlook_account import OutlookAccount
from app.models.site_pipeline import Site
from app.schemas.outlook_account import OutlookAccountCreate, OutlookAccountUpdate


class OutlookAccountController(CRUDBase[OutlookAccount, OutlookAccountCreate, OutlookAccountUpdate]):
    def __init__(self):
        super().__init__(model=OutlookAccount)

    async def get_by_username(self, username: str):
        return await self.model.filter(username=username).first()

    async def get_available(self):
        """获取第一个健康且未分配的 Outlook 账号（按 ID 顺序，排除不正常和已删除的）"""
        return await self.model.filter(assigned_site_id__isnull=True, is_deleted=False).exclude(status='不正常').order_by('id').first()

    async def assign_to_site(self, outlook_id: int, site_id: int):
        outlook = await self.get(id=outlook_id)
        site = await Site.filter(id=site_id).first()
        if not outlook or not site:
            return None, None
        outlook.assigned_site_id = site.id
        outlook.assigned_site_domain = site.domain
        await outlook.save()
        site.pipeline_log = (site.pipeline_log or '') + f"\n[outlook] assigned username={outlook.username}"
        site.pipeline_status = 'assign_outlook:success'
        await site.save()
        return outlook, site

    async def auto_assign_to_site(self, site_id: int):
        """自动分配一个未分配的 Outlook 到站点"""
        site = await Site.filter(id=site_id).first()
        if not site:
            return None, None
        outlook = await self.get_available()
        if not outlook:
            return None, site
        return await self.assign_to_site(outlook.id, site_id)

    async def unassign_from_site(self, site_id: int):
        """取消站点已分配的 Outlook"""
        outlook = await self.model.filter(assigned_site_id=site_id).first()
        if not outlook:
            return None
        outlook.assigned_site_id = None
        outlook.assigned_site_domain = ''
        site = await Site.filter(id=site_id).first()
        if site:
            site.pipeline_log = (site.pipeline_log or '') + f"\n[outlook] unassigned username={outlook.username}"
            if site.pipeline_status and 'assign_outlook' in site.pipeline_status:
                site.pipeline_status = site.pipeline_status.replace('assign_outlook:success', '').strip()
            await site.save()
        await outlook.save()
        return outlook

    async def soft_delete_by_site(self, site_id: int) -> int:
        """软删除分配给指定站点的所有 Outlook 账号（配合站点回收站）"""
        outlooks = await self.model.filter(assigned_site_id=site_id).all()
        count = 0
        for o in outlooks:
            await self.soft_remove(id=o.id)
            count += 1
        return count


outlook_account_controller = OutlookAccountController()
