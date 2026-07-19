import asyncio
import json
import random
from datetime import datetime
from typing import List

from app.core.crud import CRUDBase
from app.models.operation_job import OperationJob
from app.models.site_pipeline import Site
from app.models.shopify_collect import ShopifyProduct, ShopifySource
from app.schemas.shopify_collect import ShopifyProductUpdate, ShopifySourceCreate, ShopifySourceUpdate
from app.services.shopify_collect_service import ShopifyCollectService
from app.services.woo_import_service import WooImportService
from app.services.importers import get_importer

_shopify_collect_service = None
woo_import_service = WooImportService()


def _get_shopify_collect_service():
    global _shopify_collect_service
    if _shopify_collect_service is None:
        _shopify_collect_service = ShopifyCollectService()
    return _shopify_collect_service


def _status_failed(msg: str) -> str:
    """截断错误信息到 64 字符以内（status 字段 max_length=64）"""
    prefix = "collect_failed:"
    return f"{prefix}{msg[:64 - len(prefix)]}"


def _detect_source_type(url: str) -> str:
    """根据 URL 自动判断采集类型，仅支持集合和单品"""
    from urllib.parse import urlparse
    path = urlparse(url.strip()).path.rstrip('/')
    if '/products/' in path and path.count('/') >= 2:
        return 'product'
    if '/collections/' in path and path.count('/') >= 2:
        return 'collection'
    raise ValueError('仅支持集合URL(含/collections/xxx)或单品URL(含/products/xxx)，不支持全店采集')


class ShopifyCollectController:
    """Shopify 采集业务逻辑控制器"""

    # ── OperationJob 辅助 ──
    async def _create_job(self, site_id: int, domain: str, action_type: str, payload: dict = None) -> OperationJob:
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

    async def _complete_job(self, job: OperationJob, ok: bool, result: dict = None, error: str = ""):
        job.status = "success" if ok else "failed"
        if result:
            job.result_json = json.dumps(result, ensure_ascii=False)
        if error:
            job.error_message = error
        job.finished_at = datetime.now()
        await job.save()

    async def _update_source_status(self, source, result: dict):
        """从采集结果更新 Source 状态"""
        source.status = result.get("source_status", source.status)
        source.last_collect_count = result.get("last_collect_count", source.last_collect_count)
        source.last_collect_at = datetime.now()
        await source.save()

    async def collect_source(self, source_id: int) -> dict:
        """执行单个采集源的采集，返回 {"ok": bool, "result": dict}"""
        source = await shopify_source_controller.get(id=source_id)
        if not source:
            return {"ok": False, "error": "source not found"}
        job = await self._create_job(0, source.source_url, "collect_shopify", {"source_id": source_id})
        try:
            result = await asyncio.to_thread(_get_shopify_collect_service().collect_source, source)
            await self._update_source_status(source, result)
            await self._complete_job(job, ok=result.get('ok', False), result=result, error=result.get('error', ''))
            return {"ok": result.get('ok', False), "result": result, "job_id": job.id}
        except Exception as e:
            source.status = _status_failed(str(e))
            source.last_collect_at = datetime.now()
            await source.save()
            await self._complete_job(job, ok=False, error=str(e))
            return {"ok": False, "error": str(e)}

    async def random_assign_products(self, site_id: int, count: int = 6) -> dict:
        """随机给站点分配产品"""
        site = await Site.filter(id=site_id).first()
        if not site:
            return {"ok": False, "error": "site not found"}
        job = await self._create_job(site_id, site.domain, "assign_products", {"count": count})
        try:
            rows = await shopify_product_controller.model.filter(status='ready').all()
            if not rows:
                await self._complete_job(job, ok=False, error='no ready products')
                return {"ok": False, "error": "no ready products"}
            pool = [row for row in rows if row.imported_site_id != site.id]
            if not pool:
                await self._complete_job(job, ok=False, error='no available products')
                return {"ok": False, "error": "no available products after excluding current site assignments"}
            sample = random.sample(pool, k=min(max(count, 1), len(pool)))
            result_rows = []
            for row in sample:
                row.imported_site_id = site.id
                row.imported_status = 'assigned'
                row.imported_result = json.dumps(
                    {'assigned_only': True, 'site_id': site.id, 'site_domain': site.domain},
                    ensure_ascii=False,
                )
                await row.save()
                result_rows.append({'id': row.id, 'title': row.title, 'product_url': row.product_url})
            from app.utils.config_reader import get_provider_info
            site.pipeline_log = (site.pipeline_log or '') + '\n' + json.dumps({
                'source': 'shopify_random_assign', 'site_id': site.id, 'count': len(result_rows),
                'products': result_rows, 'provider': get_provider_info("shopify"),
            }, ensure_ascii=False)
            await site.save()
            await self._complete_job(job, ok=True, result={'assigned': len(result_rows)})
            return {"ok": True, "data": {"site_id": site.id, "site_domain": site.domain,
                    "count": len(result_rows), "products": result_rows}}
        except Exception as e:
            await self._complete_job(job, ok=False, error=str(e))
            return {"ok": False, "error": str(e)}

    async def import_product_to_site(self, product_id: int, domain: str) -> dict:
        """单产品导入到指定站点"""
        site = await Site.filter(domain=domain).first()
        if not site:
            return {"ok": False, "error": f"站点不存在: {domain}"}
        product = await shopify_product_controller.get(id=product_id)
        if not product:
            return {"ok": False, "error": "product not found"}

        product.imported_site_id = site.id
        product.imported_status = 'assigned'
        product.imported_result = json.dumps(
            {'assigned_only': True, 'site_id': site.id, 'site_domain': site.domain},
            ensure_ascii=False,
        )
        await product.save()

        job = await self._create_job(site.id, site.domain, "woo_import", {"product_id": product_id})
        try:
            result = await woo_import_service.import_for_site(site, product_ids=[product_id])
            await self._complete_job(job, ok=True, result=result)
            return {"ok": True, "data": result}
        except Exception as e:
            await self._complete_job(job, ok=False, error=str(e))
            return {"ok": False, "error": str(e)}

    async def batch_import_products(self, product_ids: List[int], domain: str) -> dict:
        """批量导入到指定站点"""
        site = await Site.filter(domain=domain).first()
        if not site:
            return {"ok": False, "error": f"站点不存在: {domain}"}
        rows = await shopify_product_controller.model.filter(id__in=product_ids).all()
        if not rows:
            return {"ok": False, "error": "products not found"}
        for row in rows:
            row.imported_site_id = site.id
            row.imported_status = 'assigned'
            row.imported_result = json.dumps(
                {'assigned_only': True, 'site_id': site.id, 'site_domain': site.domain},
                ensure_ascii=False,
            )
            await row.save()

        job = await self._create_job(site.id, site.domain, "woo_import", {"product_ids": product_ids})
        try:
            result = await woo_import_service.import_for_site(site, product_ids=product_ids)
            await self._complete_job(job, ok=True, result=result)
            return {"ok": True, "data": result}
        except Exception as e:
            await self._complete_job(job, ok=False, error=str(e))
            return {"ok": False, "error": str(e)}

    async def batch_random_assign(self, site_ids: List[int], count: int = 6) -> dict:
        """批量随机分配产品到站点"""
        results = []
        all_ready = await shopify_product_controller.model.filter(status='ready').all()
        if not all_ready:
            return {"ok": False, "error": "no ready products"}
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
                row.imported_result = json.dumps(
                    {'assigned_only': True, 'site_id': site.id, 'site_domain': site.domain},
                    ensure_ascii=False,
                )
                await row.save()
            from app.utils.config_reader import get_provider_info
            site.pipeline_log = (site.pipeline_log or '') + '\n' + json.dumps({
                'source': 'shopify_batch_random_assign', 'site_id': site.id, 'count': len(sample),
                'provider': get_provider_info("shopify"),
            }, ensure_ascii=False)
            await site.save()
            await self._create_job(site.id, site.domain, "assign_products", {"count": len(sample)})
            results.append({'site_id': site_id, 'domain': site.domain, 'count': len(sample)})
        return {"ok": True, "data": results}

    async def _run_collect_bg(self, source_id: int, job_id: int):
        """后台执行单个采集源采集"""
        try:
            source = await shopify_source_controller.get(id=source_id)
            if not source:
                await self._complete_job(await OperationJob.get(id=job_id), ok=False, error='source not found')
                return
            result = await asyncio.to_thread(_get_shopify_collect_service().collect_source, source)
            await self._update_source_status(source, result)
            if result.get('ok'):
                await self._complete_job(await OperationJob.get(id=job_id), ok=True, result=result)
            else:
                await self._complete_job(await OperationJob.get(id=job_id), ok=False, error=result.get('error', ''))
        except Exception as e:
            try:
                source = await shopify_source_controller.get(id=source_id)
                if source:
                    source.status = _status_failed(str(e))
                    source.last_collect_at = datetime.now()
                    await source.save()
            except Exception:
                pass
            await self._complete_job(await OperationJob.get(id=job_id), ok=False, error=str(e))

    async def batch_collect_sources(self, source_ids: List[int]) -> dict:
        """批量执行采集（异步），返回提交结果"""
        results = []
        for source_id in source_ids:
            source = await shopify_source_controller.get(id=source_id)
            if not source:
                results.append({'source_id': source_id, 'ok': False, 'error': 'source not found'})
                continue
            job = await self._create_job(0, source.source_url, "collect_shopify", {"source_id": source_id})
            asyncio.create_task(self._run_collect_bg(source_id, job.id))
            results.append({'source_id': source_id, 'ok': True, 'job_id': job.id, 'status': 'running'})
        return {
            "total": len(results),
            "success": sum(1 for r in results if r.get('ok')),
            "fail": sum(1 for r in results if not r.get('ok')),
            "results": results,
        }

    async def batch_create_sources(self, items: List[ShopifySourceCreate]) -> dict:
        """批量新增采集源"""
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
        return {'success': success, 'fail': fail}

    async def batch_delete_sources(self, ids: List[int]) -> dict:
        """批量删除采集源"""
        count = 0
        for sid in ids:
            try:
                await shopify_source_controller.remove(id=sid)
                count += 1
            except Exception:
                pass
        return {'deleted': count}

    async def batch_set_max_products(self, ids: List[int], max_products: int) -> dict:
        """批量设置最大采集数量"""
        updated = await shopify_source_controller.model.filter(id__in=ids).update(max_products=max_products)
        return {'updated': updated}

    async def batch_delete_products(self, ids: List[int]) -> dict:
        """批量删除产品"""
        count = 0
        for pid in ids:
            try:
                await shopify_product_controller.remove(id=pid)
                count += 1
            except Exception:
                pass
        return {'deleted': count}


class ShopifySourceController(CRUDBase[ShopifySource, ShopifySourceCreate, ShopifySourceUpdate]):
    def __init__(self):
        super().__init__(model=ShopifySource)

    async def get_by_source_url(self, source_url: str):
        return await self.model.filter(source_url=source_url).first()


class ShopifyProductController(CRUDBase[ShopifyProduct, ShopifyProductUpdate, ShopifyProductUpdate]):
    def __init__(self):
        super().__init__(model=ShopifyProduct)

    async def get_by_product_url(self, product_url: str):
        return await self.model.filter(product_url=product_url).first()


shopify_source_controller = ShopifySourceController()
shopify_product_controller = ShopifyProductController()
shopify_collect_controller = ShopifyCollectController()
