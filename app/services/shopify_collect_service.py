"""Shopify 产品采集服务

通过 Shopify 公开 API 采集产品数据：
- 单品页: {domain}/products/{handle}.json
- 分类页: {domain}/collections/{handle}/products.json
- 全店:   {domain}/products.json

支持自定义域名和 .myshopify.com 域名。
"""
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import httpx

from app.core.exceptions import ExternalAPIError


class ShopifyCollectService:
    """Shopify 产品采集器"""

    REQUEST_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/html,*/*",
    }

    def __init__(self, timeout: int = None):
        from app.utils.provider_resolver import ProviderResolver
        self.timeout = timeout if timeout is not None else int(ProviderResolver.sync_get_config("shopify", "request_timeout", "30"))
        self.session = httpx.Client(http2=True)
        self.session.headers.update(self.REQUEST_HEADERS)

    # ── URL 工具 ──────────────────────────────────────────────

    @staticmethod
    def _extract_domain(url: str) -> Optional[str]:
        """从 URL 提取域名（支持自定义域名和 .myshopify.com）"""
        parsed = urlparse(url.strip())
        return parsed.netloc or None

    @staticmethod
    def _is_single_product_url(url: str) -> bool:
        """判断是否为单品页"""
        parsed = urlparse(url.strip())
        return "/products/" in parsed.path and not parsed.path.rstrip("/").endswith("/products.json")

    @staticmethod
    def _build_collection_api_url(url: str, page: int, limit: int = 250) -> str:
        """构建集合/全店的 JSON API 地址"""
        parsed = urlparse(url.strip())
        path = parsed.path.rstrip("/")
        if not path.endswith("/products.json"):
            path = f"{path}/products.json"
        query = f"limit={limit}&page={page}"
        return urlunparse((parsed.scheme, parsed.netloc, path, "", query, ""))

    @staticmethod
    def _build_single_product_api_url(url: str) -> str:
        """构建单品 JSON API 地址"""
        parsed = urlparse(url.strip())
        path = parsed.path.rstrip("/") + ".json"
        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

    @staticmethod
    def _is_valid_http_url(url: str) -> bool:
        """是否为有效 HTTP(S) URL"""
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)

    # ── API 请求 ──────────────────────────────────────────────

    def _request_json(self, api_url: str) -> Dict[str, Any]:
        """请求 JSON API"""
        try:
            resp = self.session.get(api_url, timeout=httpx.Timeout(self.timeout))
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, OSError) as exc:
            raise ExternalAPIError("Shopify", "fetch products", detail=str(exc)) from exc

    def _fetch_collection_page(self, source_url: str, page: int) -> List[Dict[str, Any]]:
        """获取一页产品列表"""
        api_url = self._build_collection_api_url(source_url, page)
        data = self._request_json(api_url)
        products = data.get("products", [])
        return products if isinstance(products, list) else []

    def _fetch_single_product(self, product_url: str) -> List[Dict[str, Any]]:
        """获取单个产品"""
        api_url = self._build_single_product_api_url(product_url)
        data = self._request_json(api_url)
        product = data.get("product")
        return [product] if product else []

    # ── 数据解析 ──────────────────────────────────────────────

    @staticmethod
    def _parse_product(raw: Dict[str, Any], source_url: str) -> Dict[str, Any]:
        """将 Shopify API 原始产品数据解析为可入库的字典"""
        domain = urlparse(source_url).netloc
        handle = raw.get("handle", "")
        return {
            "source_url": source_url,
            "product_url": f"https://{domain}/products/{handle}" if domain else "",
            "handle": handle,
            "title": raw.get("title", ""),
            "vendor": raw.get("vendor", ""),
            "product_type": raw.get("product_type", ""),
            "tags": ", ".join(raw.get("tags", []) if isinstance(raw.get("tags"), list) else [str(raw.get("tags", ""))]),
            "prod_info_json": json.dumps(raw, ensure_ascii=False),
            "status": "ready",
        }

    # ── 主采集逻辑 ─────────────────────────────────────────────

    def collect_source(self, source, limit: int = 0) -> Dict[str, Any]:
        """采集一个 Shopify 源的所有产品（不修改 source 对象，由调用方处理）"""
        source_url = source.source_url.strip()

        if not self._is_valid_http_url(source_url):
            return {"ok": False, "error": f"无效的 URL: {source_url}", "source_id": source.id, "count": 0,
                    "source_status": f"collect_failed:无效URL", "last_collect_count": 0}

        domain = self._extract_domain(source_url)
        is_single = self._is_single_product_url(source_url)

        max_products = max(limit, source.max_products) if limit else source.max_products
        collected = 0
        saved_urls = []
        errors = []

        try:
            if is_single:
                raw_list = self._fetch_single_product(source_url)
                for raw in raw_list:
                    if max_products > 0 and collected >= max_products:
                        break
                    try:
                        parsed = self._parse_product(raw, source_url)
                        if not parsed.get("product_url"):
                            continue
                        self._insert_product(source, source_url, parsed)
                        saved_urls.append(parsed["product_url"])
                        collected += 1
                    except Exception as e:
                        errors.append({"handle": raw.get("handle", ""), "error": str(e)})
            else:
                page = 1
                while True:
                    products = self._fetch_collection_page(source_url, page)
                    if not products:
                        break
                    for raw in products:
                        if max_products > 0 and collected >= max_products:
                            break
                        try:
                            parsed = self._parse_product(raw, source_url)
                            if not parsed.get("product_url"):
                                continue
                            self._insert_product(source, source_url, parsed)
                            saved_urls.append(parsed["product_url"])
                            collected += 1
                        except Exception as e:
                            errors.append({"handle": raw.get("handle", ""), "error": str(e)})

                    if max_products > 0 and collected >= max_products:
                        break
                    if len(products) < 250:
                        break
                    page += 1
                    time.sleep(0.5)

        except Exception as e:
            return {"ok": False, "error": str(e), "source_id": source.id, "count": collected,
                    "source_status": f"collect_failed:{str(e)[:80]}", "last_collect_count": collected}

        return {
            "ok": True, "source_id": source.id, "count": collected,
            "domain": domain, "is_single_product": is_single,
            "product_urls": saved_urls[:50], "errors": errors[:20],
            "source_status": "collected", "last_collect_count": collected,
        }

    @staticmethod
    def _insert_product(source, source_url: str, parsed: Dict[str, Any]) -> None:
        """去重写入产品到 SQLite（同步操作，在 asyncio.to_thread 内安全）"""
        import sqlite3
        conn = sqlite3.connect("db.sqlite3")
        try:
            exist = conn.execute(
                "SELECT id FROM site_pipeline_shopify_product WHERE product_url=?",
                (parsed["product_url"],),
            ).fetchone()
            if not exist:
                conn.execute(
                    "INSERT INTO site_pipeline_shopify_product "
                    "(source_id, source_url, product_url, handle, title, vendor, product_type, tags, "
                    "prod_info_json, status, assigned_status, imported_status, imported_result, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        source.id,
                        source_url,
                        parsed["product_url"],
                        parsed["handle"],
                        parsed["title"],
                        parsed["vendor"],
                        parsed["product_type"],
                        parsed["tags"],
                        parsed["prod_info_json"],
                        "ready",
                        "",
                        "",
                        "",
                        datetime.now().isoformat(),
                        datetime.now().isoformat(),
                    ),
                )
                conn.commit()
        finally:
            conn.close()
