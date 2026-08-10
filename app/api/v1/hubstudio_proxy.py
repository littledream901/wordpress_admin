"""HubStudio 代理配置 API"""
from fastapi import APIRouter, Depends, Query

from app.controllers.hubstudio_proxy import hubstudio_proxy_controller
from app.core.dependency import AuthControl
from app.models.admin import User
from app.schemas.base import Success, SuccessExtra
from app.schemas.hubstudio_proxy import (
    HubStudioProxyConfigCreate,
    HubStudioProxyConfigUpdate,
    HubStudioProxyBatchImport,
    SiteBatchAssignProxy,
    ProxyBatchDelete,
    ProxyBatchCheck,
)

router = APIRouter(tags=["HubStudioProxy"])


@router.get('/list', summary='查看代理配置列表')
async def list_proxies(
    page: int = Query(1, description='页码'),
    page_size: int = Query(10, description='每页数量'),
    status: str = Query('', description='状态筛选 active/disabled/testing'),
    keyword: str = Query('', description='代理地址或描述搜索'),
    current_user: User = Depends(AuthControl.is_authed),
):
    total, data = await hubstudio_proxy_controller.list_proxies(
        page=page, page_size=page_size,
        status=status, keyword=keyword,
    )
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get('/get', summary='查看代理配置详情')
async def get_proxy(
    proxy_id: int = Query(..., description='代理配置ID'),
    current_user: User = Depends(AuthControl.is_authed),
):
    data = await hubstudio_proxy_controller.get_proxy(proxy_id)
    return Success(data=data)


@router.post('/create', summary='创建代理配置')
async def create_proxy(
    payload: HubStudioProxyConfigCreate,
    current_user: User = Depends(AuthControl.is_authed),
):
    data = await hubstudio_proxy_controller.create_proxy(payload)
    return Success(data=data, msg='创建成功')


@router.post('/batch-import', summary='批量导入代理配置')
async def batch_import_proxies(
    payload: HubStudioProxyBatchImport,
    current_user: User = Depends(AuthControl.is_authed),
):
    """
    批量粘贴代理，每行格式：host:port:account:password
    
    示例：
    ```
    163.123.201.136:5921:powygrwn:mbe5zxysoih3
    164.234.111.22:6000:user123:pass456
    ```
    """
    data = await hubstudio_proxy_controller.batch_import(payload)
    return Success(data=data, msg=f"导入完成：成功 {data['success_count']} 条，失败 {data['failed_count']} 条")


@router.post('/update', summary='更新代理配置')
async def update_proxy(
    payload: HubStudioProxyConfigUpdate,
    current_user: User = Depends(AuthControl.is_authed),
):
    data = await hubstudio_proxy_controller.update_proxy(payload)
    return Success(data=data, msg='更新成功')


@router.delete('/delete', summary='删除代理配置')
async def delete_proxy(
    proxy_id: int = Query(..., description='代理配置ID'),
    current_user: User = Depends(AuthControl.is_authed),
):
    await hubstudio_proxy_controller.delete_proxy(proxy_id)
    return Success(msg='删除成功')


@router.get('/options', summary='获取可用代理下拉选项')
async def proxy_options(
    current_user: User = Depends(AuthControl.is_authed),
):
    data = await hubstudio_proxy_controller.list_options()
    return Success(data=data)


@router.post('/batch-assign-sites', summary='站点批量分配代理')
async def batch_assign_sites(
    payload: SiteBatchAssignProxy,
    current_user: User = Depends(AuthControl.is_authed),
):
    """
    批量为站点分配代理配置
    
    - **site_ids**: 站点ID列表
    - **use_default**: True=使用HubStudio默认代理，False=从可用代理池分配
    """
    data = await hubstudio_proxy_controller.batch_assign_sites(payload)
    return Success(data=data, msg=data.get('message', '分配成功'))


@router.post('/batch-delete', summary='批量删除代理（软删除）')
async def batch_delete_proxies(
    payload: ProxyBatchDelete,
    current_user: User = Depends(AuthControl.is_authed),
):
    """批量软删除代理配置，软删除后进入回收站"""
    data = await hubstudio_proxy_controller.batch_delete(payload)
    return Success(data=data, msg=data.get('message', '批量删除成功'))


@router.post('/batch-check', summary='批量检测代理')
async def batch_check_proxies(
    payload: ProxyBatchCheck,
    current_user: User = Depends(AuthControl.is_authed),
):
    """批量检测代理连通性，访问 Google 测试"""
    data = await hubstudio_proxy_controller.batch_check(payload)
    return Success(data=data, msg=f"检测完成：成功 {data['success_count']} 条，失败 {data['failed_count']} 条")


@router.post('/check', summary='检测单条代理')
async def check_proxy(
    proxy_id: int = Query(..., description='代理配置ID'),
    current_user: User = Depends(AuthControl.is_authed),
):
    """检测单条代理连通性"""
    data = await hubstudio_proxy_controller.check_single_proxy(proxy_id)
    return Success(data=data.dict(), msg='检测完成')


@router.get('/assigned-sites', summary='获取代理分配的站点列表')
async def get_assigned_sites(
    proxy_id: int = Query(..., description='代理配置ID'),
    current_user: User = Depends(AuthControl.is_authed),
):
    """查询某个代理分配了哪些站点"""
    data = await hubstudio_proxy_controller.get_assigned_sites(proxy_id)
    return Success(data=data)

