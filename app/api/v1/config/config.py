from fastapi import APIRouter, Query

from app.controllers.config import config_controller
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.config import ConfigCreate, ConfigUpdate

router = APIRouter(tags=["Config"])

CATEGORY_LABELS = {
    'onepanel': '1Panel',
    'cloudflare': 'Cloudflare',
    'dynadot': 'Dynadot',
    'hubstudio': 'HubStudio',
    'woo': 'WooCommerce',
    'shopify': 'Shopify',
    'pipeline': '流水线',
    'general': '通用',
}


@router.get('/category/list', summary='获取配置分类列表')
async def get_categories():
    categories = await config_controller.get_categories()
    result = [{'value': c, 'label': CATEGORY_LABELS.get(c, c)} for c in categories]
    return Success(data=result)


@router.get('/list', summary='查看配置列表')
async def list_configs(category: str = Query('')):
    if category:
        objs = await config_controller.get_by_category(category)
    else:
        qs = config_controller.model.all().order_by('category', 'sort_order')
        objs = await qs
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=len(data))


@router.get('/get', summary='查看单个配置')
async def get_config(id: int = Query(...)):
    obj = await config_controller.get(id=id)
    if not obj:
        return Fail(code=404, msg='配置不存在')
    return Success(data=await obj.to_dict())


@router.post('/create', summary='新增配置')
async def create_config(payload: ConfigCreate):
    existed = await config_controller.get_by_name(payload.name)
    if existed:
        return Fail(code=400, msg=f'配置 {payload.name} 已存在')
    await config_controller.create(payload)
    return Success(msg='新增成功')


@router.post('/update', summary='更新配置')
async def update_config(payload: ConfigUpdate):
    await config_controller.update(id=payload.id, obj_in=payload)
    return Success(msg='更新成功')


@router.post('/delete', summary='删除配置')
async def delete_config(id: int = Query(...)):
    await config_controller.remove(id=id)
    return Success(msg='删除成功')


@router.post('/batch-save', summary='批量保存配置')
async def batch_save_configs(items: list[ConfigCreate]):
    """批量保存：按 name 存在则更新，不存在则新增"""
    saved = 0
    for item in items:
        existed = await config_controller.get_by_name(item.name)
        if existed:
            update_data = ConfigUpdate(
                id=existed.id,
                value=item.value,
                description=item.description,
                category=item.category,
                sort_order=item.sort_order,
                is_secret=item.is_secret,
                is_enabled=item.is_enabled,
            )
            await config_controller.update(id=existed.id, obj_in=update_data)
        else:
            await config_controller.create(item)
        saved += 1
    return Success(data={'saved': saved}, msg='批量保存成功')
