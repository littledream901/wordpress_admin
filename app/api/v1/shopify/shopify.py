from fastapi import APIRouter, Body, Query
from tortoise.expressions import Q

from app.controllers.shopify_collect import (
    _detect_source_type,
    shopify_collect_controller,
    shopify_product_controller,
    shopify_source_controller,
)
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.shopify_collect import ShopifyProductUpdate, ShopifySourceCreate, ShopifySourceUpdate

router = APIRouter(tags=["Shopify"])


# ── Source CRUD ──
@router.get('/source/list', summary='Shopify 待采集列表')
async def list_sources(page: int = Query(1), page_size: int = Query(10), source_url: str = Query('')):
    q = Q()
    if source_url:
        q &= Q(source_url__contains=source_url)
    total, objs = await shopify_source_controller.list(page=page, page_size=page_size, search=q, order=['-id'])
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.post('/source/create', summary='新增 Shopify 待采集源')
async def create_source(payload: ShopifySourceCreate):
    existed = await shopify_source_controller.get_by_source_url(payload.source_url)
    if existed:
        return Fail(code=400, msg='source_url already exists')
    try:
        payload.source_type = _detect_source_type(payload.source_url)
    except ValueError as e:
        return Fail(code=400, msg=str(e))
    await shopify_source_controller.create(payload)
    return Success(msg='Created Successfully')


@router.post('/source/update', summary='更新 Shopify 采集源')
async def update_source(payload: ShopifySourceUpdate):
    if payload.source_url:
        try:
            payload.source_type = _detect_source_type(payload.source_url)
        except ValueError as e:
            return Fail(code=400, msg=str(e))
    await shopify_source_controller.update(id=payload.id, obj_in=payload)
    return Success(msg='Updated Successfully')


@router.post('/source/{source_id}/collect', summary='执行采集')
async def collect_source(source_id: int):
    result = await shopify_collect_controller.collect_source(source_id)
    if result['ok']:
        return Success(data=result.get('result'), msg='Collect completed')
    return Fail(code=400, msg=f"采集失败: {result.get('error')}")


@router.post('/source/{source_id}/delete', summary='删除采集源')
async def delete_source(source_id: int):
    try:
        await shopify_source_controller.remove(id=source_id)
        return Success(msg='Deleted Successfully')
    except Exception as e:
        return Fail(code=500, msg=str(e))


# ── Product CRUD ──
@router.get('/product/list', summary='Shopify 产品列表')
async def list_products(
    page: int = Query(1), page_size: int = Query(10),
    title: str = Query(''), source_id: int = Query(0),
):
    q = Q()
    if title:
        q &= Q(title__contains=title)
    if source_id:
        q &= Q(source_id=source_id)
    total, objs = await shopify_product_controller.list(page=page, page_size=page_size, search=q, order=['-id'])
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.post('/product/update', summary='更新 Shopify 产品')
async def update_product(payload: ShopifyProductUpdate):
    await shopify_product_controller.update(id=payload.id, obj_in=payload)
    return Success(msg='Updated Successfully')


@router.post('/product/{product_id}/delete', summary='删除单个产品')
async def delete_product(product_id: int):
    try:
        await shopify_product_controller.remove(id=product_id)
        return Success(msg='Deleted Successfully')
    except Exception as e:
        return Fail(code=500, msg=str(e))


# ── 分配 & 导入 ──
@router.post('/product/random-assign', summary='随机给站点分配产品')
async def random_assign_products(site_id: int = Body(..., embed=True), count: int = Body(6, embed=True)):
    result = await shopify_collect_controller.random_assign_products(site_id, count)
    if result['ok']:
        return Success(data=result['data'], msg='Assigned Successfully')
    return Fail(code=404 if 'not found' in str(result.get('error', '')) else 400, msg=result.get('error'))


@router.post('/product/{product_id}/import-to-site', summary='单产品导入到指定站点')
async def import_product_to_site(product_id: int, domain: str = Body(..., embed=True)):
    result = await shopify_collect_controller.import_product_to_site(product_id, domain)
    if result['ok']:
        return Success(data=result.get('data'), msg='Import completed')
    return Fail(code=404 if 'not found' in str(result.get('error', '')) else 500, msg=str(result.get('error')))


@router.post('/product/batch-import', summary='批量导入到指定站点')
async def batch_import_products(product_ids: list[int] = Body(..., embed=True), domain: str = Body(..., embed=True)):
    result = await shopify_collect_controller.batch_import_products(product_ids, domain)
    if result['ok']:
        return Success(data=result.get('data'), msg='Batch import completed')
    return Fail(code=404 if 'not found' in str(result.get('error', '')) else 500, msg=str(result.get('error')))


# ── 批量操作 ──
@router.post('/source/batch-create', summary='批量新增采集源')
async def batch_create_sources(items: list[ShopifySourceCreate] = Body(...)):
    data = await shopify_collect_controller.batch_create_sources(items)
    return Success(data=data)


@router.post('/source/batch-delete', summary='批量删除采集源')
async def batch_delete_sources(ids: list[int] = Body(...)):
    data = await shopify_collect_controller.batch_delete_sources(ids)
    return Success(data=data)


@router.post('/source/batch-collect', summary='批量执行采集（异步）')
async def batch_collect_sources(source_ids: list[int] = Body(...)):
    data = await shopify_collect_controller.batch_collect_sources(source_ids)
    return Success(data=data)


@router.post('/source/batch-set-max-products', summary='批量设置最大采集数量')
async def batch_set_max_products(ids: list[int] = Body(..., embed=True), max_products: int = Body(..., embed=True)):
    data = await shopify_collect_controller.batch_set_max_products(ids, max_products)
    return Success(data=data)


@router.post('/product/batch-random-assign', summary='批量随机分配产品到站点')
async def batch_random_assign(site_ids: list[int] = Body(...), count: int = Body(6)):
    result = await shopify_collect_controller.batch_random_assign(site_ids, count)
    if result['ok']:
        return Success(data=result['data'])
    return Fail(code=404, msg=result.get('error'))


@router.post('/product/batch-delete', summary='批量删除产品')
async def batch_delete_products(ids: list[int] = Body(..., embed=True)):
    data = await shopify_collect_controller.batch_delete_products(ids)
    return Success(data=data)
