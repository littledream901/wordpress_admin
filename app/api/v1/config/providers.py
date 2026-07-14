"""配置中心 API — 管理 Provider、配置项、资源绑定"""
from fastapi import APIRouter, Query

from app.controllers.config_provider import binding_controller, provider_controller, provider_item_controller
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.config_provider import (
    BatchBindingRequest, BatchSaveItemsRequest, ConfigProviderCreate, ConfigProviderUpdate,
    ProviderConfigItemCreate, ProviderConfigItemUpdate,
    ResourceProviderBindingCreate,
)

router = APIRouter(tags=["Provider"])


# ── Provider CRUD ──

@router.get('/provider/list', summary='Provider 列表')
async def list_providers(provider_type: str = Query('')):
    if provider_type:
        objs = await provider_controller.get_by_type(provider_type)
    else:
        objs = await provider_controller.model.all().order_by('provider_type', '-priority')
    data = []
    for p in objs:
        d = await p.to_dict()
        d['item_count'] = await provider_item_controller.model.filter(provider_id=p.id).count()
        data.append(d)
    return SuccessExtra(data=data, total=len(data))


@router.get('/provider/get', summary='Provider 详情')
async def get_provider(id: int = Query(...)):
    obj = await provider_controller.get(id=id)
    if not obj:
        return Fail(code=404, msg='不存在')
    return Success(data=await obj.to_dict())


@router.post('/provider/create', summary='新增 Provider')
async def create_provider(payload: ConfigProviderCreate):
    created = await provider_controller.create(obj_in=payload)
    return Success(data={'id': created.id}, msg='创建成功')


@router.post('/provider/update', summary='更新 Provider')
async def update_provider(payload: ConfigProviderUpdate):
    await provider_controller.update(id=payload.id, obj_in=payload)
    return Success(msg='更新成功')


@router.post('/provider/delete', summary='删除 Provider')
async def delete_provider(id: int = Query(...)):
    await provider_controller.soft_remove(id=id)
    return Success(msg='已移入回收站')


@router.post('/provider/set-default', summary='设为默认')
async def set_default_provider(id: int = Query(...)):
    await provider_controller.set_default(id)
    return Success(msg='已设为默认')


@router.get('/provider/types', summary='Provider 类型列表')
async def get_provider_types():
    from app.models.config_provider import ConfigProvider
    return Success(data=[{"value": t[0], "label": t[1]} for t in ConfigProvider.PROVIDER_TYPES])


# ── Provider Config Items ──

@router.get('/items/list', summary='配置项列表')
async def list_items(provider_id: int = Query(...)):
    items = await provider_item_controller.get_by_provider(provider_id)
    data = [await it.to_dict() for it in items]
    return SuccessExtra(data=data, total=len(data))


@router.post('/items/update', summary='更新配置项')
async def update_item(payload: ProviderConfigItemUpdate):
    from app.controllers.config_provider import _validate_config_value
    if payload.config_value is not None and payload.config_type:
        _validate_config_value(f"id={payload.id}", payload.config_type, payload.config_value)
    await provider_item_controller.update(id=payload.id, obj_in=payload)
    return Success(msg='更新成功')


@router.post('/items/batch-save', summary='批量保存配置项')
async def batch_save_items(payload: BatchSaveItemsRequest):
    count = await provider_item_controller.batch_save(payload.provider_id, payload.items)
    return Success(data={'saved': count}, msg=f'批量保存 {count} 项成功')


# ── Resource Binding ──

@router.get('/bindings/list', summary='资源绑定列表')
async def list_bindings(resource_type: str = Query(''), resource_id: int = Query(None)):
    if resource_type and resource_id:
        objs = await binding_controller.get_for_resource(resource_type, resource_id)
    else:
        objs = await binding_controller.model.all()
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=len(data))


@router.post('/bindings/create', summary='创建绑定')
async def create_binding(payload: ResourceProviderBindingCreate):
    await binding_controller.create(obj_in=payload)
    return Success(msg='绑定成功')


@router.post('/bindings/delete', summary='删除绑定')
async def delete_binding(id: int = Query(...)):
    await binding_controller.remove(id=id)
    return Success(msg='删除成功')


@router.post('/bindings/batch-create', summary='批量创建绑定')
async def batch_create_bindings(payload: BatchBindingRequest):
    """批量将多个站点绑定到多个 Provider（站点×Provider 笛卡尔积）
    注意：如果绑定的是非默认 Provider，则对应站点将使用该 Provider 而非默认账号"""
    results = []
    for site_id in payload.site_ids:
        for provider_id in payload.provider_ids:
            try:
                await binding_controller.create(obj_in=ResourceProviderBindingCreate(
                    resource_type="site",
                    resource_id=site_id,
                    provider_type=payload.provider_type,
                    provider_id=provider_id,
                    bind_type=payload.bind_type,
                    remark=payload.remark,
                ))
                results.append({"site_id": site_id, "provider_id": provider_id, "ok": True})
            except Exception as e:
                results.append({"site_id": site_id, "provider_id": provider_id, "ok": False, "error": str(e)})
    return Success(data={"results": results, "total": len(results),
                         "success": sum(1 for r in results if r["ok"]),
                         "fail": sum(1 for r in results if not r["ok"])})
