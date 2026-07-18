"""ADS 环境管理 - API 路由"""

from typing import Optional
from fastapi import APIRouter, Query, Body
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.ads_manager import AdsEnvCreate, AdsEnvUpdate
from app.controllers.ads_manager import ads_env_controller
from app.services.operation_job_service import operation_job_service

router = APIRouter()


@router.get('/ads/list', summary='ADS 环境列表')
async def list_ads_env(
    page: int = Query(1), page_size: int = Query(20),
    ads_env_id: str = Query('', description='ADS环境ID搜索'),
    domain: str = Query('', description='域名搜索'),
    status: str = Query('', description='状态筛选'),
):
    result = await ads_env_controller.list_with_site(
        page=page, page_size=page_size,
        ads_env_id=ads_env_id, domain=domain, status=status,
    )
    return SuccessExtra(
        data=result['data'], total=result['total'],
        page=result['page'], page_size=result['page_size'],
    )


@router.post('/ads/create', summary='创建 ADS 环境')
async def create_ads_env(data: AdsEnvCreate):
    obj = await ads_env_controller.create_with_sites(data)
    d = await obj.to_dict(exclude_fields=['sites'])
    await obj.fetch_related('sites')
    d['site_ids'] = [s.id for s in obj.sites]
    d['site_domains'] = [s.domain for s in obj.sites]
    # 记录操作任务
    await operation_job_service.create_task(
        resource_type="ads", resource_id=obj.id,
        action_type="create_ads", domain=data.domain,
        payload={"ads_env_id": data.ads_env_id},
    )
    return Success(data=d, msg='ADS 环境已创建')


@router.post('/ads/update', summary='更新 ADS 环境')
async def update_ads_env(data: AdsEnvUpdate):
    obj = await ads_env_controller.update_with_sites(data.id, data)
    if not obj:
        return Fail(msg=f'ADS 环境不存在: id={data.id}')
    d = await obj.to_dict(exclude_fields=['sites'])
    await obj.fetch_related('sites')
    d['site_ids'] = [s.id for s in obj.sites]
    d['site_domains'] = [s.domain for s in obj.sites]
    # 记录操作任务
    await operation_job_service.create_task(
        resource_type="ads", resource_id=obj.id,
        action_type="update_ads", domain=obj.domain,
        payload={"ads_env_id": obj.ads_env_id},
    )
    return Success(data=d, msg='ADS 环境已更新')


@router.post('/ads/delete', summary='删除 ADS 环境')
async def delete_ads_env(ids: list[int] = Body(..., embed=True)):
    count = 0
    for id_ in ids:
        obj = await ads_env_controller.model.filter(id=id_).first()
        await ads_env_controller.soft_remove(id_)
        # 记录操作任务
        if obj:
            await operation_job_service.create_task(
                resource_type="ads", resource_id=id_,
                action_type="delete_ads", domain=obj.domain,
                payload={"ads_env_id": obj.ads_env_id},
            )
        count += 1
    return Success(data={'deleted': count}, msg=f'已删除 {count} 条记录（可在回收站恢复）')


@router.post('/ads/{ads_id}/add-site', summary='关联站点到 ADS 环境')
async def ads_add_site(ads_id: int, site_id: int = Body(..., embed=True)):
    obj = await ads_env_controller.model.filter(id=ads_id).first()
    if not obj:
        return Fail(msg=f'ADS 环境不存在: id={ads_id}')
    from app.models.site_pipeline import Site
    site = await Site.filter(id=site_id).first()
    if not site:
        return Fail(msg=f'站点不存在: id={site_id}')
    await obj.sites.add(site)
    await obj.fetch_related('sites')
    # 记录操作任务
    await operation_job_service.create_task(
        resource_type="ads", resource_id=ads_id,
        action_type="ads_add_site", domain=obj.domain,
        payload={"ads_env_id": obj.ads_env_id, "site_id": site_id, "site_domain": site.domain},
    )
    return Success(data={
        'site_ids': [s.id for s in obj.sites],
        'site_domains': [s.domain for s in obj.sites],
    }, msg='站点已关联')


@router.post('/ads/{ads_id}/remove-site', summary='从 ADS 环境移除站点')
async def ads_remove_site(ads_id: int, site_id: int = Body(..., embed=True)):
    obj = await ads_env_controller.model.filter(id=ads_id).first()
    if not obj:
        return Fail(msg=f'ADS 环境不存在: id={ads_id}')
    from app.models.site_pipeline import Site
    site = await Site.filter(id=site_id).first()
    if not site:
        return Fail(msg=f'站点不存在: id={site_id}')
    await obj.sites.remove(site)
    await obj.fetch_related('sites')
    # 记录操作任务
    await operation_job_service.create_task(
        resource_type="ads", resource_id=ads_id,
        action_type="ads_remove_site", domain=obj.domain,
        payload={"ads_env_id": obj.ads_env_id, "site_id": site_id, "site_domain": site.domain},
    )
    return Success(data={
        'site_ids': [s.id for s in obj.sites],
        'site_domains': [s.domain for s in obj.sites],
    }, msg='站点已移除')
