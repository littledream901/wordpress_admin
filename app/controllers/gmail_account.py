from app.core.crud import CRUDBase
from app.models.gmail_account import GmailAccount
from app.models.site_pipeline import Site
from app.schemas.gmail_account import GmailAccountCreate, GmailAccountUpdate


class GmailAccountController(CRUDBase[GmailAccount, GmailAccountCreate, GmailAccountUpdate]):
    def __init__(self):
        super().__init__(model=GmailAccount)

    async def get_by_username(self, username: str):
        return await self.model.filter(username=username).first()

    async def get_available(self):
        """获取第一个健康且未分配的 Gmail 账号（按 ID 顺序，排除不正常和已删除的）"""
        return await self.model.filter(assigned_site_id__isnull=True, is_deleted=False).exclude(status='不正常').order_by('id').first()

    async def assign_to_site(self, gmail_id: int, site_id: int):
        gmail = await self.get(id=gmail_id)
        site = await Site.filter(id=site_id).first()
        if not gmail or not site:
            return None, None
        gmail.assigned_site_id = site.id
        gmail.assigned_site_domain = site.domain
        await gmail.save()
        site.pipeline_log = (site.pipeline_log or '') + f"\n[gmail] assigned username={gmail.username}"
        site.pipeline_status = 'assign_gmail:success'
        await site.save()
        return gmail, site

    async def auto_assign_to_site(self, site_id: int):
        """自动分配一个未分配的 Gmail 到站点"""
        site = await Site.filter(id=site_id).first()
        if not site:
            return None, None
        gmail = await self.get_available()
        if not gmail:
            return None, site
        return await self.assign_to_site(gmail.id, site_id)

    async def unassign_from_site(self, site_id: int):
        """取消站点已分配的 Gmail"""
        gmail = await self.model.filter(assigned_site_id=site_id).first()
        if not gmail:
            return None
        gmail.assigned_site_id = None
        gmail.assigned_site_domain = ''
        site = await Site.filter(id=site_id).first()
        if site:
            site.pipeline_log = (site.pipeline_log or '') + f"\n[gmail] unassigned username={gmail.username}"
            if site.pipeline_status and 'assign_gmail' in site.pipeline_status:
                site.pipeline_status = site.pipeline_status.replace('assign_gmail:success', '').strip()
            await site.save()
        await gmail.save()
        return gmail

    async def soft_delete_by_site(self, site_id: int) -> int:
        """软删除分配给指定站点的所有 Gmail 账号（配合站点回收站）"""
        gmails = await self.model.filter(assigned_site_id=site_id).all()
        count = 0
        for g in gmails:
            await self.soft_remove(id=g.id)
            count += 1
        return count


gmail_account_controller = GmailAccountController()
