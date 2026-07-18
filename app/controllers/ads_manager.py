"""ADS 环境管理 - 业务逻辑"""

from typing import Optional
from tortoise.expressions import Q
from app.models.ads_manager import AdsEnv
from app.models.site_pipeline import Site
from app.core.crud import CRUDBase
from app.schemas.ads_manager import AdsEnvCreate, AdsEnvUpdate


class AdsEnvController(CRUDBase[AdsEnv, AdsEnvCreate, AdsEnvUpdate]):
    """ADS 环境 CRUD，继承通用 CRUDBase"""

    def __init__(self):
        super().__init__(model=AdsEnv)

    async def create_with_sites(self, data: AdsEnvCreate) -> AdsEnv:
        """创建 ADS 环境并关联站点"""
        obj_dict = data.model_dump(exclude={'site_ids'})
        obj = await self.model.create(**obj_dict)
        if data.site_ids:
            sites = await Site.filter(id__in=data.site_ids).all()
            await obj.sites.add(*sites)
        return obj

    async def update_with_sites(self, id_: int, data: AdsEnvUpdate) -> Optional[AdsEnv]:
        """更新 ADS 环境并同步站点关联"""
        obj = await self.model.filter(id=id_).first()
        if not obj:
            return None
        # 更新标量字段
        update_dict = data.model_dump(exclude_unset=True, exclude={'id', 'site_ids'})
        if update_dict:
            await obj.update_from_dict(update_dict).save()
        # 同步站点关联（全量替换）
        if data.site_ids is not None:
            current_sites = await obj.sites.all()
            if current_sites:
                await obj.sites.remove(*current_sites)
            if data.site_ids:
                sites = await Site.filter(id__in=data.site_ids).all()
                await obj.sites.add(*sites)
        return obj

    async def list_with_site(self, page: int, page_size: int,
                             ads_env_id: str = '', domain: str = '',
                             status: str = '', order: list = None) -> dict:
        """分页查询 ADS 环境，补全关联站点信息"""
        q = Q()
        if ads_env_id:
            q &= Q(ads_env_id__contains=ads_env_id)
        if domain:
            q &= Q(domain__contains=domain)
        if status:
            q &= Q(status=status)

        total, objs = await self.list(
            page=page, page_size=page_size, search=q,
            order=order or ['-created_at'],
        )

        data = []
        for obj in objs:
            d = await obj.to_dict(exclude_fields=['sites'])
            await obj.fetch_related('sites')
            d['site_ids'] = [s.id for s in obj.sites]
            d['site_domains'] = [s.domain for s in obj.sites]
            data.append(d)

        return {'total': total, 'data': data, 'page': page, 'page_size': page_size}


ads_env_controller = AdsEnvController()
