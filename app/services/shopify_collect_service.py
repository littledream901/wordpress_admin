"""Shopify 产品采集服务（全异步）

通过 Shopify 公开 API 采集产品数据：
- 单品页: {domain}/products/{handle}.json
- 分类页: {domain}/collections/{handle}/products.json
- 全店:   {domain}/products.json

支持自定义域名和 .myshopify.com 域名。
"""
import asyncio
import json
import logging
import random
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import httpx

from app.core.exceptions import ExternalAPIError

_log = logging.getLogger(__name__)


def _status_failed(msg: str) -> str:
    """截断错误信息到 64 字符以内（status 字段 max_length=64）"""
    prefix = "collect_failed:"
    return f"{prefix}{msg[:64 - len(prefix)]}"


class ShopifyCollectService:
    """Shopify 产品采集器（全异步）"""

    REQUEST_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/html,*/*",
    }

    def __init__(self, timeout: int = None, max_retries: int = None, retry_base_delay: float = None):
        self.timeout = timeout if timeout is not None else self._read_default_timeout()
        self.max_retries = max_retries if max_retries is not None else self._read_default_config_int("max_retries", 3)
        self.retry_base_delay = retry_base_delay if retry_base_delay is not None else self._read_default_config_float("retry_base_delay", 5.0)
        self.page_limit = self._read_default_config_int("page_limit", 100)
        self.session = httpx.AsyncClient(http2=True, headers=self.REQUEST_HEADERS)

    async def close(self):
        """关闭 HTTP 会话"""
        await self.session.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
        return False

    @staticmethod
    def _read_default_timeout() -> int:
        try:
            from app.utils.provider_resolver import ProviderResolver
            return int(ProviderResolver.sync_get_config("shopify", "request_timeout", "30"))
        except Exception:
            return 30

    @staticmethod
    def _read_default_config_int(key: str, default: int) -> int:
        try:
            from app.utils.provider_resolver import ProviderResolver
            return int(ProviderResolver.sync_get_config("shopify", key, str(default)))
        except Exception:
            return default

    @staticmethod
    def _read_default_config_float(key: str, default: float) -> float:
        try:
            from app.utils.provider_resolver import ProviderResolver
            return float(ProviderResolver.sync_get_config("shopify", key, str(default)))
        except Exception:
            return default

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
    def _build_collection_api_url(url: str, page: int, limit: int) -> str:
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

    async def _request_json(self, api_url: str) -> Dict[str, Any]:
        """请求 JSON API，429 自动读取 Retry-After 并指数退避重试"""
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self.session.get(api_url, timeout=httpx.Timeout(self.timeout))

                # 429 限流：有剩余重试次数则退避重试，否则直接报错
                if resp.status_code == 429:
                    if attempt < self.max_retries:
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after and retry_after.isdigit():
                            delay = int(retry_after)
                        else:
                            delay = self.retry_base_delay * (2 ** attempt) + random.uniform(0, 1)
                        _log.warning(
                            "[ShopifyCollect] 429 限流 attempt=%d/%d delay=%.1fs url=%s",
                            attempt + 1, self.max_retries, delay, api_url[:120],
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise ExternalAPIError(
                        "Shopify", "fetch products",
                        detail=f"429 限流，重试 {self.max_retries} 次后仍失败",
                    )

                # 非 429 错误
                resp.raise_for_status()
                try:
                    return resp.json()
                except ValueError as exc:
                    raise ExternalAPIError(
                        "Shopify", "parse products",
                        detail=f"响应非 JSON (status={resp.status_code}): {str(exc)[:200]}",
                    ) from exc
            except (httpx.HTTPError, OSError) as exc:
                raise ExternalAPIError("Shopify", "fetch products", detail=str(exc)) from exc

    async def _fetch_collection_page(self, source_url: str, page: int) -> List[Dict[str, Any]]:
        """获取一页产品列表"""
        api_url = self._build_collection_api_url(source_url, page, self.page_limit)
        data = await self._request_json(api_url)
        products = data.get("products", [])
        return products if isinstance(products, list) else []

    async def _fetch_single_product(self, product_url: str) -> List[Dict[str, Any]]:
        """获取单个产品"""
        api_url = self._build_single_product_api_url(product_url)
        data = await self._request_json(api_url)
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

    # ── 数据库写入 ─────────────────────────────────────────────

    @staticmethod
    async def _insert_product(source, source_url: str, product_data: dict) -> bool:
        """去重写入产品（直接在当前事件循环中执行 ORM）"""
        from app.models.shopify_collect import ShopifyProduct

        url = product_data.get("product_url", "").strip()
        if not url:
            return False

        existing = await ShopifyProduct.filter(product_url=url).first()
        if existing:
            return False

        try:
            await ShopifyProduct.create(
                source_id=source.id,
                source_url=source_url,
                product_url=url,
                handle=product_data.get("handle", ""),
                title=product_data.get("title", ""),
                vendor=product_data.get("vendor", ""),
                product_type=product_data.get("product_type", ""),
                tags=product_data.get("tags", ""),
                prod_info_json=product_data.get("prod_info_json", "{}"),
                status="ready",
                imported_result="{}",
            )
            return True
        except Exception as e:
            _log.warning("[ShopifyCollect] 写入产品失败 %s: %s", url, e)
            return False

    # ── 主采集逻辑 ─────────────────────────────────────────────

    async def collect_source(self, source, limit: int = 0) -> Dict[str, Any]:
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
                raw_list = await self._fetch_single_product(source_url)
                for raw in raw_list:
                    if max_products > 0 and collected >= max_products:
                        break
                    try:
                        parsed = self._parse_product(raw, source_url)
                        if not parsed.get("product_url"):
                            continue
                        inserted = await self._insert_product(source, source_url, parsed)
                        if inserted:
                            saved_urls.append(parsed["product_url"])
                            collected += 1
                    except Exception as e:
                        errors.append({"handle": raw.get("handle", ""), "error": str(e)})
            else:
                page = 1
                while True:
                    products = await self._fetch_collection_page(source_url, page)
                    if not products:
                        break
                    for raw in products:
                        if max_products > 0 and collected >= max_products:
                            break
                        try:
                            parsed = self._parse_product(raw, source_url)
                            if not parsed.get("product_url"):
                                continue
                            inserted = await self._insert_product(source, source_url, parsed)
                            if inserted:
                                saved_urls.append(parsed["product_url"])
                                collected += 1
                        except Exception as e:
                            errors.append({"handle": raw.get("handle", ""), "error": str(e)})

                    if max_products > 0 and collected >= max_products:
                        break
                    if len(products) < self.page_limit:
                        break
                    page += 1
                    await asyncio.sleep(0.5)

        except Exception as e:
            return {"ok": False, "error": str(e), "source_id": source.id, "count": collected,
                    "source_status": _status_failed(str(e)), "last_collect_count": collected}

        return {
            "ok": True, "source_id": source.id, "count": collected,
            "domain": domain, "is_single_product": is_single,
            "product_urls": saved_urls[:50], "errors": errors[:20],
            "source_status": "collected", "last_collect_count": collected,
        }
