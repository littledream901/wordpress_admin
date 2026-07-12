from fastapi import APIRouter, Body, Query
from tortoise.expressions import Q
from datetime import datetime
import asyncio
import json
import random

from app.controllers.shopify_collect import shopify_product_controller, shopify_source_controller
from app.models.operation_job import OperationJob
from app.models.site_pipeline import Site
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.shopify_collect import ShopifyProductUpdate, ShopifySourceCreate, ShopifySourceUpdate
from app.services.shopify_collect_service import ShopifyCollectService
from app.services.woo_import_service import WooImportService

router = APIRouter()
shopify_collect_service = ShopifyCollectService()
woo_import_service = WooImportService()


# ── OperationJob 辅助 ──
async def _shopify_create_job(site_id: int, domain: str, action_type: str, payload: dict = None) -> OperationJob:
    return await OperationJob.create(
        resource_type="site" if site_id else "shopify_source",
        resource_id=site_id,
        domain=domain,
        action_type=action_type,
        status="running",
        step="0",
        total_steps=1,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
        started_at=datetime.now(),
    )


async def _shopify_complete_job(job: OperationJob, ok: bool, result: dict = None, error: str = ""):
    job.status = "success" if ok else "failed"
    if result:
        job.result_json = json.dumps(result, ensure_ascii=False)
    if error:
        job.error_message = error
    job.finished_at = datetime.now()
    await job.save()


async def _update_source_status(source, result: dict):
    """从采集结果更新 Source 状态（在 async 上下文中执行）"""
    source.status = result.get("source_status", source.status)
    source.last_collect_count = result.get("last_collect_count", source.last_collect_count)
    source.last_collect_at = datetime.now()
    await source.save()


@router.get('/source/list', summary='Shopify 待采集列表')
async def list_sources(page: int = Query(1), page_size: int = Query(10), source_url: str = Query('')):
    q = Q()
    if source_url:
        q &= Q(source_url__contains=source_url)
    total, objs = await shopify_source_controller.list(page=page, page_size=page_size, search=q, order=['-id'])
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


def _detect_source_type(url: str) -> str:
    """根据 URL 自动判断采集类型，仅支持集合和单品"""
    from urllib.parse import urlparse
    path = urlparse(url.strip()).path.rstrip('/')
    # 单品: /products/{handle}
    if '/products/' in path and path.count('/') >= 2:
        return 'product'
    # 集合: /collections/{handle}
    if '/collections/' in path and path.count('/') >= 2:
        return 'collection'
    raise ValueError('仅支持集合URL(含/collections/xxx)或单品URL(含/products/xxx)，不支持全店采集')


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
    source = await shopify_source_controller.get(id=source_id)
    if not source:
        return Fail(code=404, msg='source not found')
    job = await _shopify_create_job(0, source.source_url, "collect_shopify", {"source_id": source_id})
    try:
        result = await asyncio.to_thread(shopify_collect_service.collect_source, source)
        await _update_source_status(source, result)
        if result.get('ok'):
            await _shopify_complete_job(job, ok=True, result=result)
            return Success(data=result, msg='Collect completed')
        else:
            await _shopify_complete_job(job, ok=False, error=result.get('error', ''))
            return Fail(code=400, msg=f'采集失败: {result.get("error")}')
    except Exception as e:
        source.status = f"collect_failed:{str(e)[:80]}"
        source.last_collect_at = datetime.now()
        await source.save()
        await _shopify_complete_job(job, ok=False, error=str(e))
        return Fail(code=500, msg=f'采集失败: {e}')


@router.get('/product/list', summary='Shopify 产品列表')
async def list_products(page: int = Query(1), page_size: int = Query(10), title: str = Query(''), source_id: int = Query(0)):
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


@router.post('/product/random-assign', summary='随机给站点分配产品')
async def random_assign_products(site_id: int = Body(..., embed=True), count: int = Body(6, embed=True)):
    site = await Site.filter(id=site_id).first()
    if not site:
        return Fail(code=404, msg='site not found')
    job = await _shopify_create_job(site_id, site.domain, "assign_products", {"count": count})
    try:
        rows = await shopify_product_controller.model.filter(status='ready').all()
        if not rows:
            await _shopify_complete_job(job, ok=False, error='no ready products')
            return Fail(code=404, msg='no ready products')
        pool = [row for row in rows if row.imported_site_id != site.id]
        if not pool:
            await _shopify_complete_job(job, ok=False, error='no available products')
            return Fail(code=400, msg='no available products after excluding current site assignments')
        sample = random.sample(pool, k=min(max(count, 1), len(pool)))
        result_rows = []
        for row in sample:
            row.imported_site_id = site.id
            row.imported_status = 'assigned'
            row.imported_result = json.dumps({'assigned_only': True, 'site_id': site.id, 'site_domain': site.domain}, ensure_ascii=False)
            await row.save()
            result_rows.append({'id': row.id, 'title': row.title, 'product_url': row.product_url})
        from app.utils.config_reader import get_provider_info
        site.pipeline_log = (site.pipeline_log or '') + '\n' + json.dumps({'source': 'shopify_random_assign', 'site_id': site.id, 'count': len(result_rows), 'products': result_rows, 'provider': get_provider_info("shopify")}, ensure_ascii=False)
        await site.save()
        await _shopify_complete_job(job, ok=True, result={'assigned': len(result_rows)})
        return Success(data={'site_id': site.id, 'site_domain': site.domain, 'count': len(result_rows), 'products': result_rows}, msg='Assigned Successfully')
    except Exception as e:
        await _shopify_complete_job(job, ok=False, error=str(e))
        return Fail(code=500, msg=str(e))


@router.post('/product/{product_id}/import-to-site', summary='单产品导入到指定站点')
async def import_product_to_site(product_id: int, domain: str = Body(..., embed=True)):
    site = await Site.filter(domain=domain).first()
    if not site:
        return Fail(code=404, msg=f'站点不存在: {domain}')
    product = await shopify_product_controller.get(id=product_id)
    if not product:
        return Fail(code=404, msg='product not found')

    product.imported_site_id = site.id
    product.imported_status = 'assigned'
    product.imported_result = json.dumps({'assigned_only': True, 'site_id': site.id, 'site_domain': site.domain}, ensure_ascii=False)
    await product.save()

    job = await _shopify_create_job(site.id, site.domain, "woo_import", {"product_id": product_id})
    try:
        result = await woo_import_service.import_for_site(site, product_ids=[product_id])
        await _shopify_complete_job(job, ok=True, result=result)
        return Success(data=result, msg='Import completed')
    except Exception as e:
        await _shopify_complete_job(job, ok=False, error=str(e))
        return Fail(code=500, msg=str(e))


@router.post('/product/batch-import', summary='批量导入到指定站点')
async def batch_import_products(product_ids: list[int] = Body(..., embed=True), domain: str = Body(..., embed=True)):
    site = await Site.filter(domain=domain).first()
    if not site:
        return Fail(code=404, msg=f'站点不存在: {domain}')
    rows = await shopify_product_controller.model.filter(id__in=product_ids).all()
    if not rows:
        return Fail(code=404, msg='products not found')
    for row in rows:
        row.imported_site_id = site.id
        row.imported_status = 'assigned'
        row.imported_result = json.dumps({'assigned_only': True, 'site_id': site.id, 'site_domain': site.domain}, ensure_ascii=False)
        await row.save()

    job = await _shopify_create_job(site.id, site.domain, "woo_import", {"product_ids": product_ids})
    try:
        result = await woo_import_service.import_for_site(site, product_ids=product_ids)
        await _shopify_complete_job(job, ok=True, result=result)
        return Success(data=result, msg='Batch import completed')
    except Exception as e:
        await _shopify_complete_job(job, ok=False, error=str(e))
        return Fail(code=500, msg=str(e))


@router.post('/product/{product_id}/delete', summary='删除单个产品')
async def delete_product(product_id: int):
    try:
        await shopify_product_controller.remove(id=product_id)
        return Success(msg='Deleted Successfully')
    except Exception as e:
        return Fail(code=500, msg=str(e))


@router.post('/product/batch-delete', summary='批量删除产品')
async def batch_delete_products(ids: list[int] = Body(..., embed=True)):
    count = 0
    for pid in ids:
        try:
            await shopify_product_controller.remove(id=pid)
            count += 1
        except Exception:
            pass
    return Success(data={'deleted': count})


@router.post('/source/{source_id}/delete', summary='删除采集源')
async def delete_source(source_id: int):
    try:
        await shopify_source_controller.remove(id=source_id)
        return Success(msg='Deleted Successfully')
    except Exception as e:
        return Fail(code=500, msg=str(e))


@router.post('/source/batch-create', summary='批量新增采集源')
async def batch_create_sources(items: list[ShopifySourceCreate] = Body(...)):
    success, fail = 0, 0
    for item in items:
        try:
            existed = await shopify_source_controller.get_by_source_url(item.source_url)
            if existed:
                fail += 1
                continue
            await shopify_source_controller.create(item)
            success += 1
        except Exception:
            fail += 1
    return Success(data={'success': success, 'fail': fail})


@router.post('/source/batch-delete', summary='批量删除采集源')
async def batch_delete_sources(ids: list[int] = Body(...)):
    count = 0
    for sid in ids:
        try:
            await shopify_source_controller.remove(id=sid)
            count += 1
        except Exception:
            pass
    return Success(data={'deleted': count})


async def _run_collect_bg(source_id: int, job_id: int):
    """后台执行单个采集源采集"""
    try:
        source = await shopify_source_controller.get(id=source_id)
        if not source:
            await _shopify_complete_job(await OperationJob.get(id=job_id), ok=False, error='source not found')
            return
        result = await asyncio.to_thread(shopify_collect_service.collect_source, source)
        await _update_source_status(source, result)
        if result.get('ok'):
            await _shopify_complete_job(await OperationJob.get(id=job_id), ok=True, result=result)
        else:
            await _shopify_complete_job(await OperationJob.get(id=job_id), ok=False, error=result.get('error', ''))
    except Exception as e:
        try:
            source = await shopify_source_controller.get(id=source_id)
            if source:
                source.status = f"collect_failed:{str(e)[:80]}"
                source.last_collect_at = datetime.now()
                await source.save()
        except Exception:
            pass
        await _shopify_complete_job(await OperationJob.get(id=job_id), ok=False, error=str(e))


@router.post('/source/batch-collect', summary='批量执行采集（异步）')
async def batch_collect_sources(source_ids: list[int] = Body(...)):
    results = []
    for source_id in source_ids:
        source = await shopify_source_controller.get(id=source_id)
        if not source:
            results.append({'source_id': source_id, 'ok': False, 'error': 'source not found'})
            continue
        job = await _shopify_create_job(0, source.source_url, "collect_shopify", {"source_id": source_id})
        asyncio.create_task(_run_collect_bg(source_id, job.id))
        results.append({'source_id': source_id, 'ok': True, 'job_id': job.id, 'status': 'running'})
    return Success(data={'total': len(results), 'success': sum(1 for r in results if r.get('ok')), 'fail': sum(1 for r in results if not r.get('ok')), 'results': results})


@router.post('/product/batch-random-assign', summary='批量随机分配产品到站点')
async def batch_random_assign(site_ids: list[int] = Body(...), count: int = Body(6)):
    results = []
    all_ready = await shopify_product_controller.model.filter(status='ready').all()
    if not all_ready:
        return Fail(code=404, msg='no ready products')
    for site_id in site_ids:
        site = await Site.filter(id=site_id).first()
        if not site:
            results.append({'site_id': site_id, 'error': 'site not found'})
            continue
        pool = [row for row in all_ready if row.imported_site_id != site.id]
        if not pool:
            results.append({'site_id': site_id, 'count': 0, 'error': 'no available products'})
            continue
        sample = random.sample(pool, k=min(max(count, 1), len(pool)))
        for row in sample:
            row.imported_site_id = site.id
            row.imported_status = 'assigned'
            row.imported_result = json.dumps({'assigned_only': True, 'site_id': site.id, 'site_domain': site.domain}, ensure_ascii=False)
            await row.save()
        # 更新 site pipeline_log
        from app.utils.config_reader import get_provider_info
        site.pipeline_log = (site.pipeline_log or '') + '\n' + json.dumps({
            'source': 'shopify_batch_random_assign', 'site_id': site.id, 'count': len(sample),
            'provider': get_provider_info("shopify"),
        }, ensure_ascii=False)
        await site.save()
        # 创建 OperationJob
        await _shopify_create_job(site.id, site.domain, "assign_products", {"count": len(sample)})
        results.append({'site_id': site_id, 'domain': site.domain, 'count': len(sample)})
    return Success(data=results)
