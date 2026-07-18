"""Shopify 产品导入器 — 通过 Shopify Admin API 导入产品。"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from app.models.site_pipeline import Site
from . import BaseProductImporter

_log = logging.getLogger(__name__)

SHOPIFY_API_VERSION = "2024-01"


class ShopifyProductImporter(BaseProductImporter):
    """Shopify Admin REST API 产品导入器。"""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    def _api_url(self, site: Site) -> str:
        """构建 REST API 基地址。"""
        store = (site.shopify_store_url or "").rstrip("/")
        if not store.startswith("http"):
            store = f"https://{store}"
        return f"{store}/admin/api/{SHOPIFY_API_VERSION}"

    @staticmethod
    def _validate_site(site: Site) -> Optional[str]:
        """校验站点配置，返回错误信息，None 表示 OK。"""
        if not site.shopify_store_url:
            return "Shopify Store URL 未配置"
        if not site.shopify_token:
            return "Shopify API Token 未配置"
        return None

    def _build_product_payload(self, prod_info_json: str) -> Optional[dict]:
        """从采集的 Shopify 产品 JSON 构建导入用的 product payload。

        采集 JSON 格式（来自 products.json）：
        {"product": {"id": ..., "title": ..., "body_html": ..., "vendor": ...,
         "product_type": ..., "tags": ..., "variants": [...], "images": [...], ...}}
        """
        try:
            raw = json.loads(prod_info_json or "{}")
        except Exception:
            _log.warning(f"[ShopifyImporter] JSON 解析失败，跳过")
            return None

        prod = raw.get("product", raw)

        variants = []
        for v in prod.get("variants", []):
            v_opts = {f"option{i}": v.get(f"option{i}") for i in range(1, 4) if v.get(f"option{i}")}
            variants.append({
                "price": v.get("price", "0.00"),
                "compare_at_price": v.get("compare_at_price"),
                "sku": v.get("sku", ""),
                "inventory_quantity": int(v.get("inventory_quantity", 0)),
                "inventory_management": v.get("inventory_management", "shopify"),
                "requires_shipping": v.get("requires_shipping", True),
                **v_opts,
            })

        images = []
        for img in prod.get("images", []):
            if img.get("src"):
                images.append({"src": img["src"]})
                if len(images) >= 10:  # Shopify 单产品图片上限
                    break

        payload = {
            "title": prod.get("title", ""),
            "body_html": prod.get("body_html", ""),
            "vendor": prod.get("vendor", ""),
            "product_type": prod.get("product_type", ""),
            "tags": prod.get("tags", ""),
            "status": "active",
            "variants": variants,
        }
        if images:
            payload["images"] = images

        return payload

    async def import_products(
        self, site: Site, products: list, **kwargs
    ) -> Dict[str, Any]:
        """将产品导入到目标 Shopify Store。

        Args:
            site: Site 模型实例
            products: ShopifyProduct 模型实例列表

        Returns:
            {"ok": True/False, "success": int, "failed": int, "errors": [...]}
        """
        err = self._validate_site(site)
        if err:
            return {"ok": False, "success": 0, "failed": len(products), "errors": [err]}

        api_url = self._api_url(site)
        self._client = httpx.AsyncClient(
            headers={
                "X-Shopify-Access-Token": site.shopify_token,
                "Content-Type": "application/json",
            },
            timeout=30,
        )

        # 连通性测试
        try:
            resp = await self._client.get(f"{api_url}/shop.json")
            if resp.status_code == 401:
                return {"ok": False, "success": 0, "failed": len(products),
                        "errors": ["Shopify API Token 无效 (HTTP 401)"]}
            elif resp.status_code >= 500:
                return {"ok": False, "success": 0, "failed": len(products),
                        "errors": [f"Shopify API 服务端错误 (HTTP {resp.status_code})"]}
        except Exception as e:
            return {"ok": False, "success": 0, "failed": len(products),
                    "errors": [f"无法连接 Shopify API: {e}"]}

        success = 0
        failed = 0
        errors: List[dict] = []

        for row in products:
            payload = self._build_product_payload(row.prod_info_json)
            if not payload:
                failed += 1
                row.imported_status = "failed"
                row.imported_result = json.dumps(
                    {"imported": False, "site_id": site.id, "reason": "JSON 解析失败"},
                    ensure_ascii=False,
                )
                await row.save()
                errors.append({"id": row.id, "title": row.title or "", "reason": "JSON 解析失败"})
                continue

            try:
                resp = await self._client.post(
                    f"{api_url}/products.json",
                    json={"product": payload},
                )
                if resp.status_code in (200, 201):
                    success += 1
                    row.imported_status = "success"
                    row.imported_result = json.dumps(
                        {"imported": True, "site_id": site.id, "site_domain": site.domain},
                        ensure_ascii=False,
                    )
                elif resp.status_code == 422:  # 参数验证失败
                    error_detail = ""
                    try:
                        error_detail = str(resp.json().get("errors", ""))
                    except Exception:
                        pass
                    failed += 1
                    row.imported_status = "failed"
                    row.imported_result = json.dumps(
                        {"imported": False, "site_id": site.id, "reason": f"参数错误: {error_detail}"},
                        ensure_ascii=False,
                    )
                    errors.append({"id": row.id, "title": payload.get("title", ""),
                                   "reason": f"参数错误: {error_detail}"})
                else:
                    failed += 1
                    reason = f"HTTP {resp.status_code}"
                    try:
                        reason = str(resp.json().get("errors", reason))
                    except Exception:
                        pass
                    row.imported_status = "failed"
                    row.imported_result = json.dumps(
                        {"imported": False, "site_id": site.id, "reason": reason},
                        ensure_ascii=False,
                    )
                    errors.append({"id": row.id, "title": payload.get("title", ""), "reason": reason})
                    # Token 无效 → 中止
                    if resp.status_code == 401:
                        await row.save()
                        # Close client before returning.
                        close_ok = await self._close_client()
                        return {"ok": True, "success": success, "failed": failed + len(products) - success - failed,
                                "errors": errors}
            except Exception as e:
                failed += 1
                row.imported_status = "failed"
                row.imported_result = json.dumps(
                    {"imported": False, "site_id": site.id, "reason": str(e)},
                    ensure_ascii=False,
                )
                errors.append({"id": row.id, "title": payload.get("title", ""), "reason": str(e)})

            await row.save()
            # 遵守 API 速率限制（REST API 每秒 2 请求）
            await asyncio.sleep(0.6)

        await self._close_client()

        return {"ok": True, "success": success, "failed": failed, "errors": errors}

    async def _close_client(self):
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None


shopify_importer = ShopifyProductImporter()
