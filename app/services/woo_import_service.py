import asyncio
import json
import logging
import random
import re
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from httpx import BasicAuth

from app.models.shopify_collect import ShopifyProduct
from app.models.site_pipeline import Site
from app.core.exceptions import ExternalAPIError, ProviderConfigError
from app.utils.provider_resolver import ProviderResolver

RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass
class RequestLimiterState:
    last_request_at: float = 0.0
    consecutive_errors: int = 0
    cooldown_until: float = 0.0


@dataclass
class WooRequestLimiter:
    min_interval_seconds: float = 2.5
    jitter_seconds: float = 0.8
    error_cooldown_seconds: float = 30
    max_error_cooldown_seconds: float = 120
    max_retries: int = 2
    timeout: httpx.Timeout = field(default_factory=lambda: httpx.Timeout(10, read=120))
    pool_maxsize: int = 1
    user_agent: str = "Mozilla/5.0 WooCommerce-Sync/1.0"
    verify_ssl: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _state: RequestLimiterState = field(default_factory=RequestLimiterState, init=False)
    _session: httpx.Client = field(init=False)

    def __post_init__(self) -> None:
        # 优先从数据库配置读取参数
        try:
            from app.utils.provider_resolver import ProviderResolver
            cfg = ProviderResolver.sync_get_config_map("woo")
            if cfg:
                if "request_timeout" in cfg:
                    self.timeout = httpx.Timeout(10, read=float(cfg["request_timeout"]))
                self.max_retries = int(cfg.get("retry_limit", self.max_retries))
                self.min_interval_seconds = float(cfg.get("min_interval_seconds", self.min_interval_seconds))
                self.error_cooldown_seconds = float(cfg.get("error_cooldown_seconds", self.error_cooldown_seconds))
                self.max_error_cooldown_seconds = float(cfg.get("max_error_cooldown_seconds", self.max_error_cooldown_seconds))
            # 读取 SSL 验证配置（默认不验证，避免 Cloudflare 代理导致握手超时）
            ssl_val = ProviderResolver.sync_get_config("onepanel", "wp_verify_ssl", "false")
            self.verify_ssl = ssl_val.lower() != "false"
        except Exception:
            pass

        self._session = httpx.Client(http2=True, verify=self.verify_ssl)
        self._session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def _sleep_before_request(self, url: str) -> None:
        now = time.monotonic()
        with self._lock:
            wait_seconds = 0.0
            if self._state.cooldown_until > now:
                wait_seconds = max(wait_seconds, self._state.cooldown_until - now)
            elapsed = now - self._state.last_request_at
            interval = self.min_interval_seconds + random.uniform(0, self.jitter_seconds)
            if elapsed < interval:
                wait_seconds = max(wait_seconds, interval - elapsed)
        if wait_seconds > 0:
            logger.info("WooCommerce 全局限速等待 %.1f 秒，url=%s", wait_seconds, url)
            time.sleep(wait_seconds)
        with self._lock:
            self._state.last_request_at = time.monotonic()

    def _apply_retry_after(self, retry_after_str: str) -> float:
        """解析 Retry-After 并写入全局冷却，后续请求自动遵守"""
        try:
            wait_seconds = float(retry_after_str)
        except (ValueError, TypeError):
            return 0.0
        wait_seconds = min(wait_seconds, self.max_error_cooldown_seconds)
        with self._lock:
            target = time.monotonic() + wait_seconds
            if target > self._state.cooldown_until:
                self._state.cooldown_until = target
        return wait_seconds

    def _mark_success(self) -> None:
        with self._lock:
            self._state.consecutive_errors = 0
            self._state.cooldown_until = 0.0

    def _mark_error(self, is_transient: bool = False) -> float:
        """标记错误并计算冷却时间。

        - is_transient=True: 瞬时错误（偶发超时/连接断开），短退避不累计连续错误
        - is_transient=False: 持续错误（服务器返回 5xx），指数冷却
        """
        with self._lock:
            if is_transient:
                cooldown = self.error_cooldown_seconds * 0.3
            else:
                self._state.consecutive_errors += 1
                cooldown = min(
                    self.error_cooldown_seconds * (2 ** max(0, self._state.consecutive_errors - 1)),
                    self.max_error_cooldown_seconds,
                )
            cooldown += random.uniform(0, self.jitter_seconds)
            self._state.cooldown_until = time.monotonic() + cooldown
            consecutive_errors = self._state.consecutive_errors
        logger.warning(
            "WooCommerce 请求失败，连续失败=%s %s 进入冷却 %.1f 秒",
            consecutive_errors, "(瞬时)" if is_transient else "", cooldown,
        )
        return cooldown

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        timeout = kwargs.pop("timeout", self.timeout)
        request_max_retries = kwargs.pop("max_retries", self.max_retries)
        method = method.upper()
        # 非幂等请求（POST/PUT/DELETE）默认不重试，除非调用方显式传入 max_retries
        if method in ("POST", "PUT", "DELETE") and "max_retries" in kwargs.get("_orig_kwargs", {}):
            pass  # 显式传入的不覆盖
        elif method in ("POST", "PUT", "DELETE"):
            request_max_retries = 0

        last_error: Optional[BaseException] = None
        last_response: Optional[httpx.Response] = None
        for attempt in range(1, request_max_retries + 2):
            self._sleep_before_request(url)
            try:
                logger.info(
                    "WooCommerce 请求 attempt=%s/%s method=%s url=%s",
                    attempt, request_max_retries + 1, method, url,
                )
                resp = self._session.request(method, url, timeout=timeout, **kwargs)
                last_response = resp
                if resp.status_code not in RETRYABLE_STATUS_CODES:
                    if resp.status_code >= 400 and resp.status_code != 400:
                        logger.error(
                            "WooCommerce API 错误 status=%s body=%s",
                            resp.status_code, resp.text[:500],
                        )
                        resp.raise_for_status()
                    self._mark_success()
                    return resp

                logger.warning(
                    "WooCommerce 返回可重试状态 status=%s body=%s",
                    resp.status_code, resp.text[:500],
                )

                # 非幂等请求遇到 5xx/429 不重试，立即抛出，不污染全局冷却
                if method in ("POST", "PUT", "DELETE"):
                    resp.raise_for_status()
                    return resp  # unreachable, raise_for_status raises

                # 仅幂等请求（GET）才设置全局冷却和 Retry-After
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    server_wait = self._apply_retry_after(retry_after)
                    logger.warning("服务器要求 Retry-After=%s 秒，已纳入全局冷却", server_wait)

                self._mark_error()
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError) as exc:
                last_error = exc
                logger.warning(
                    "WooCommerce 连接/超时异常 attempt=%s error=%r", attempt, exc,
                )
                self._mark_error(is_transient=True)
            except httpx.HTTPError:
                # raise_for_status 抛出的，已在上面 mark_error，直接传播
                raise
            except OSError as exc:
                last_error = exc
                logger.warning(
                    "WooCommerce 网络异常 attempt=%s error=%r", attempt, exc,
                )
                self._mark_error(is_transient=True)
            if attempt <= request_max_retries:
                backoff = min(2 ** attempt, self.max_error_cooldown_seconds) + random.uniform(0, self.jitter_seconds)
                logger.info("WooCommerce 重试前等待 %.1f 秒", backoff)
                time.sleep(backoff)
        if last_response is not None:
            last_response.raise_for_status()
            return last_response
        raise ExternalAPIError("WooCommerce", f"{method} {url}", detail=str(last_error))


_global_woo_limiter = None


def _get_global_woo_limiter():
    global _global_woo_limiter
    if _global_woo_limiter is None:
        _global_woo_limiter = WooRequestLimiter()
    return _global_woo_limiter




def extract_brand_from_domain(wc_url: str) -> str:
    parsed = urlparse(wc_url if "://" in wc_url else f"https://{wc_url}")
    host = (parsed.netloc or parsed.path).lower().strip().split("@").pop().split(":")[0]
    host = re.sub(r"^www\.", "", host).strip("./ ")
    parts = [p for p in host.split(".") if p]
    if len(parts) <= 1:
        return re.sub(r"[^a-z0-9_-]+", "-", host).strip("-")
    return re.sub(r"[^a-z0-9._-]+", "-", ".".join(parts[:-1])).strip(".-_") or parts[0]


def apply_brand_to_payload(payload: Dict[str, Any], brand: str, brand_id: Optional[int] = None) -> Dict[str, Any]:
    if not brand:
        return payload
    if brand_id:
        payload["brands"] = [{"id": int(brand_id)}]
    meta_data = payload.get("meta_data") if isinstance(payload.get("meta_data"), list) else []
    if not any(isinstance(item, dict) and item.get("key") == "brand" for item in meta_data):
        meta_data.append({"key": "brand", "value": brand})
    payload["meta_data"] = meta_data
    return payload


class WooCommerceSyncer:
    def __init__(self, wc_url: str, consumer_key: str, consumer_secret: str,
                 upload_variants: bool = False, limiter: Optional[WooRequestLimiter] = None,
                 enable_images: bool = True, max_images_per_product: int = 5,
                 check_existing_before_create: bool = True,
                 use_isolated_limiter: bool = True,
                 wp_async_images: bool = False,
                 import_interval_ms: int = 200):
        self.wc_base_url = wc_url.rstrip("/")
        self.wc_api_url = f"{self.wc_base_url}/wp-json/wc/v3/products"
        self.wc_auth = BasicAuth(consumer_key, consumer_secret)
        self.upload_variants = upload_variants
        self.enable_images = enable_images
        self.max_images_per_product = max_images_per_product
        self.check_existing_before_create = check_existing_before_create
        self.wp_async_images = wp_async_images
        self.import_interval_ms = import_interval_ms
        self.brand = extract_brand_from_domain(self.wc_base_url)
        self.brand_id: Optional[int] = None
        # 每个站点优先使用独立限流器，避免单站点故障拖累全局导入
        if limiter:
            self.limiter = limiter
        elif use_isolated_limiter:
            self.limiter = WooRequestLimiter()
        else:
            self.limiter = _get_global_woo_limiter()

    def normalize_price(self, value: Any) -> str:
        try:
            price = Decimal(str(value).replace(",", "").strip())
            return f"{max(price, Decimal('0.00')):.2f}"
        except (InvalidOperation, ValueError):
            return "0.00"

    def normalize_stock(self, value: Any) -> int:
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return 0

    def generate_sku(self, handle: str, suffix: str = "") -> str:
        clean_handle = re.sub(r"[^a-zA-Z0-9]", "-", handle or "goods")
        clean_handle = re.sub(r"-+", "-", clean_handle).strip("-")[:12] or "goods"
        return f"{clean_handle}-{suffix}" if suffix else f"{clean_handle}-{''.join(random.choices('0123456789', k=6))}"

    def parse_shopify_json(self, json_str: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(json_str)
            return data.get("product", data)
        except json.JSONDecodeError:
            return None

    def map_shopify_to_wc(self, shopify_prod: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        title = shopify_prod.get("title")
        handle = shopify_prod.get("handle", "")
        desc = shopify_prod.get("body_html", "")
        vendor_original = shopify_prod.get("vendor", "")
        images_raw = shopify_prod.get("images", [])
        variants_raw = shopify_prod.get("variants", [])
        options_raw = shopify_prod.get("options", [])
        # 解析 tags：可能是逗号分隔字符串或列表
        raw_tags = shopify_prod.get("tags", "")
        if isinstance(raw_tags, str):
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        elif isinstance(raw_tags, list):
            tags = [str(t).strip() for t in raw_tags if str(t).strip()]
        else:
            tags = []
        if not title or not variants_raw:
            return None

        # vendor 用域名名称（去掉后缀），原 vendor 放入 meta_data
        vendor = self.brand
        self.get_or_create_brand_id()

        wc_images = []
        remote_images = []  # WP 端异步下载的原始 URL 列表
        if self.enable_images:
            for img in images_raw:
                src = img.get("src")
                if src and src.startswith(("http://", "https://")):
                    wc_images.append({"src": src.rstrip(",;"), "alt": img.get("alt", title)})
            if not wc_images:
                logger.info("已关闭图片上传或本商品无有效图片，商品:%s", title)
                wc_images = []
            elif self.max_images_per_product > 0 and len(wc_images) > self.max_images_per_product:
                logger.info(
                    "限制图片数量，本商品原有 %s 张图片，仅上传前 %s 张，商品:%s",
                    len(wc_images), self.max_images_per_product, title,
                )
                wc_images = wc_images[:self.max_images_per_product]
            if self.wp_async_images:
                remote_images = [img["src"].rstrip(",;") for img in wc_images]
                logger.info(
                    "WP 异步图片模式：%d 张图片将推迟到服务端下载，商品:%s",
                    len(remote_images), title,
                )
                wc_images = []

        if self.upload_variants:
            wc_attributes = []
            attr_names = []
            for opt in options_raw:
                opt_name = opt.get("name", "")
                opt_values = opt.get("values", [])
                if opt_name and opt_values:
                    wc_attributes.append({"name": opt_name, "visible": True, "variation": True, "options": opt_values})
                    attr_names.append(opt_name)
            all_variants = []
            for var in variants_raw:
                sku = self.generate_sku(handle, str(var.get("id", "")))
                variant_options = {f"option{idx+1}": var.get(f"option{idx+1}") or "" for idx, _ in enumerate(attr_names)}
                var_img = var.get("image_src", "")
                all_variants.append({
                    "sku": sku,
                    "regular_price": self.normalize_price(var.get("price")),
                    "stock_quantity": self.normalize_stock(var.get("inventory_quantity", 0)),
                    "manage_stock": True,
                    "taxable": var.get("taxable", True),
                    "requires_shipping": var.get("requires_shipping", True),
                    "image": {"src": var_img} if var_img else None,
                    **variant_options,
                })
            payload = {
                "name": title,
                "slug": handle,
                "type": "variable",
                "description": desc,
                "short_description": shopify_prod.get("metafields_global_description_tag", ""),
                "vendor": vendor,
                "images": wc_images,
                "attributes": wc_attributes,
                "variations": all_variants,
                "tags": [{"name": tag} for tag in tags if tag],
                "status": "publish",
                "manage_stock": False,
            }
            if remote_images:
                payload["remote_images"] = remote_images
            payload = apply_brand_to_payload(payload, self.brand, self.brand_id)
            return payload

        first_var = variants_raw[0]
        payload = {
            "name": title,
            "slug": handle,
            "type": "simple",
            "description": desc,
            "short_description": shopify_prod.get("metafields_global_description_tag", ""),
            "vendor": vendor,
            "images": wc_images,
            "regular_price": self.normalize_price(first_var.get("price")),
            "sku": self.generate_sku(handle, str(first_var.get("id", ""))),
            "stock_quantity": self.normalize_stock(first_var.get("inventory_quantity", 0)),
            "manage_stock": False,
            "taxable": first_var.get("taxable", True),
            "requires_shipping": first_var.get("requires_shipping", True),
            # "tags": [{"name": tag} for tag in tags if tag],
            "status": "publish",
        }
        if remote_images:
            payload["remote_images"] = remote_images
        payload = apply_brand_to_payload(payload, self.brand, self.brand_id)
        return payload

    def get_product_id_by_sku(self, sku: str) -> Optional[int]:
        """通过SKU查询WooCommerce商品ID"""
        if not sku:
            return None
        try:
            resp = self.limiter.request("GET", self.wc_api_url, auth=self.wc_auth,
                                        params={"sku": sku, "per_page": 1})
            res_list = resp.json()
            if isinstance(res_list, list) and res_list:
                return res_list[0]["id"]
            return None
        except Exception:
            return None

    def get_or_create_brand_id(self) -> Optional[int]:
        if self.brand_id or not self.brand:
            return self.brand_id
        brands_api_url = f"{self.wc_base_url}/wp-json/wc/v3/products/brands"
        try:
            resp = self.limiter.request("GET", brands_api_url, auth=self.wc_auth,
                                        params={"search": self.brand, "per_page": 100})
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else []
                for item in items:
                    if str(item.get("name", "")).lower() == self.brand.lower() or str(item.get("slug", "")).lower() == self.brand.lower():
                        self.brand_id = int(item["id"])
                        return self.brand_id
            resp = self.limiter.request("POST", brands_api_url, auth=self.wc_auth,
                                        json={"name": self.brand}, max_retries=0)
            if resp.status_code in (200, 201):
                self.brand_id = int(resp.json()["id"])
                return self.brand_id
        except Exception as exc:
            logger.warning("品牌接口不可用，降级写 meta_data：%s", exc)
        return None

    def handle_duplicate_sku_response(self, resp: httpx.Response, sku: str, prod_name: str) -> Optional[Dict[str, Any]]:
        """处理 product_invalid_sku 响应（504后重复创建 或 SKU已存在）"""
        try:
            err = resp.json()
        except ValueError:
            return None
        if err.get("code") != "product_invalid_sku":
            return None
        data = err.get("data") or {}
        resource_id = data.get("resource_id")
        if resource_id:
            try:
                get_resp = self.limiter.request("GET", f"{self.wc_api_url}/{resource_id}", auth=self.wc_auth)
                if get_resp.status_code == 200:
                    return get_resp.json()
            except Exception:
                pass
            return {"id": resource_id, "sku": sku, "name": prod_name, "_duplicate_sku_as_success": True}
        exist_id = self.get_product_id_by_sku(sku)
        if exist_id:
            return {"id": exist_id, "sku": sku, "name": prod_name, "_duplicate_sku_as_success": True}
        return None

    def upsert_product(self, payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
        """创建/更新商品，支持SKU查重和重复SKU处理。

        - SKU 已存在 → PUT 更新（不是跳过）
        - SKU 不存在 → POST 创建
        - POST 为非幂等操作，不做自动重试（504后后端可能已创建成功），改为异常后补查 SKU

        Returns:
            (result_dict_or_None, error_reason)
            - 成功时 error_reason 为空字符串
            - 失败时 result 为 None，error_reason 描述原因
        """
        prod_name = payload.get("name", "")
        if payload.get("type") == "variable":
            sku = (payload.get("variations", [{}])[0].get("sku") or "")
        else:
            sku = payload.get("sku") or ""

        # 创建前按SKU查重
        exist_id = self.get_product_id_by_sku(sku) if self.check_existing_before_create and sku else None

        try:
            if exist_id:
                # SKU 已存在 → PUT 更新
                update_url = f"{self.wc_api_url}/{exist_id}"
                resp = self.limiter.request("PUT", update_url, auth=self.wc_auth, json=payload)
                if resp.status_code == 200:
                    logger.info(
                        "[更新成功] 商品ID:%s 标识SKU:%s 名称:%s brand:%s",
                        exist_id, sku, prod_name, self.brand,
                    )
                    return resp.json(), ""
                duplicate_result = self.handle_duplicate_sku_response(resp, sku, prod_name)
                if duplicate_result:
                    return duplicate_result, ""
            else:
                # POST 是非幂等操作：504/超时后后端可能已经创建成功，不做自动重试
                resp = self.limiter.request(
                    "POST", self.wc_api_url,
                    auth=self.wc_auth, json=payload,
                    max_retries=0,
                )
                if resp.status_code in (200, 201):
                    new_data = resp.json()
                    logger.info(
                        "[创建成功] 商品ID:%s 标识SKU:%s 名称:%s brand:%s",
                        new_data.get("id"), sku, prod_name, self.brand,
                    )
                    return new_data, ""

                if resp.status_code == 401:
                    return None, "WooCommerce API 认证失败 (401)"

                duplicate_result = self.handle_duplicate_sku_response(resp, sku, prod_name)
                if duplicate_result:
                    return duplicate_result, ""

            logger.warning(
                "[同步失败] SKU:%s 状态码:%s 响应:%s",
                sku, resp.status_code, resp.text[:300],
            )
            if resp.status_code >= 500:
                return None, f"WooCommerce 服务端错误 (HTTP {resp.status_code})"
            return None, f"WooCommerce 返回 HTTP {resp.status_code}"

        except httpx.HTTPError as e:
            logger.warning("[网络异常] 同步SKU %s 失败: %s", sku, e)
            # POST 非幂等：任何异常都不直接重试 POST，先按 SKU 查询是否已创建
            # Cloudflare 502 分两类：①源站连接失败（未到达后端，安全）②PHP执行到一半崩溃（可能已写入）
            # 不加区分直接重试 POST 有重复创建风险，统一走补查兜底
            exist_id_after = self.get_product_id_by_sku(sku) if sku else None
            if exist_id_after:
                logger.warning(
                    "[异常后查到商品，视为成功] SKU:%s 商品ID:%s 名称:%s",
                    sku, exist_id_after, prod_name,
                )
                return {
                    "id": exist_id_after, "sku": sku,
                    "name": prod_name, "_found_after_error": True,
                }, ""
            err_msg = str(e)
            if "timeout" in err_msg.lower() or "timed out" in err_msg.lower():
                return None, f"连接超时: {err_msg[:100]}"
            return None, f"请求异常: {err_msg[:100]}"

        except ValueError as e:
            logger.error("[JSON解析异常] SKU %s: %s", sku, e)
            return None, f"JSON解析异常: {str(e)[:100]}"

        except RuntimeError as e:
            logger.error("[限速请求异常] 同步SKU %s 失败: %s", sku, e)
            # 504/超时后仍可能已经创建成功
            exist_id_after = self.get_product_id_by_sku(sku) if sku else None
            if exist_id_after:
                logger.warning(
                    "[限速异常后查到商品，视为成功] SKU:%s 商品ID:%s 名称:%s",
                    sku, exist_id_after, prod_name,
                )
                return {
                    "id": exist_id_after, "sku": sku,
                    "name": prod_name, "_found_after_error": True,
                }, ""
            return None, f"限速异常: {str(e)[:100]}"

    def batch_upsert_products(self, payloads: list[dict]) -> Tuple[list[dict], list[tuple[dict, str]]]:
        """批量创建/更新商品，使用 /products/batch 接口。

        一次请求提交多个商品，显著减少 HTTP 连接开销和 Cloudflare 握手频次。

        Returns:
            (successes, failures): successes 是成功创建的 product 数据列表；
            failures 是 (payload, reason) 列表，由调用方决定是否单独重试。
        """
        if not payloads:
            return [], []

        batch_url = f"{self.wc_api_url}/batch"
        create_list = []
        update_list = []

        for p in payloads:
            # 先查 SKU 是否已存在
            if payloads[0].get("type") == "variable":
                sku = (p.get("variations", [{}])[0].get("sku") or "")
            else:
                sku = p.get("sku") or ""

            exist_id = None
            if self.check_existing_before_create and sku:
                exist_id = self.get_product_id_by_sku(sku)

            if exist_id:
                update_list.append({"id": exist_id, **p})
            else:
                create_list.append(p)

        batch_payload = {}
        if create_list:
            batch_payload["create"] = create_list
        if update_list:
            batch_payload["update"] = update_list

        if not batch_payload:
            return [], [(p, "无可操作项") for p in payloads]

        logger.info(
            "[批量同步] 创建:%d 更新:%d -> %s",
            len(create_list), len(update_list), batch_url,
        )

        try:
            resp = self.limiter.request(
                "POST", batch_url,
                auth=self.wc_auth, json=batch_payload,
                max_retries=0,
            )
        except Exception as e:
            logger.warning("[批量同步] 请求异常: %s", e)
            # 全部回退为单独处理
            return [], [(p, f"批量请求异常: {e}") for p in payloads]

        if resp.status_code not in (200, 201):
            logger.warning("[批量同步] 失败 HTTP %s: %s", resp.status_code, resp.text[:300])
            if resp.status_code >= 500:
                # 502/504 → 等待指数退避后回退单条处理
                return [], [(p, f"批量请求失败 (HTTP {resp.status_code})") for p in payloads]
            return [], [(p, f"批量请求异常 (HTTP {resp.status_code})") for p in payloads]

        try:
            batch_result = resp.json()
        except Exception:
            return [], [(p, "批量响应解析失败") for p in payloads]

        successes = []
        failures = []

        for key in ("create", "update"):
            items = batch_result.get(key, [])
            for item in items:
                if isinstance(item, dict):
                    if item.get("id"):
                        prod_name = item.get("name", "")
                        item_sku = item.get("sku", "")
                        logger.info(
                            "[批量%s成功] 商品ID:%s SKU:%s 名称:%s",
                            key, item["id"], item_sku, prod_name,
                        )
                        successes.append(item)
                    else:
                        err = item.get("error", {}) if isinstance(item.get("error"), dict) else {}
                        err_msg = err.get("message", str(item.get("error", "未知错误")))
                        failures.append(({}, f"批量{key}失败: {err_msg[:200]}"))

        # 检查是否有 payload 在 batch response 中完全没出现（可能是接口静默跳过）
        total_responded = len(successes) + len(failures)
        if total_responded < len(payloads):
            responded_skus = set()
            for s in successes:
                responded_skus.add(s.get("sku", ""))

        return successes, failures

    def sync_single_shopify_item(self, shopify_json_str: str) -> Tuple[bool, str]:
        """同步单个 Shopify 产品到 WooCommerce。

        Returns:
            (ok, reason): ok=True 表示成功，ok=False 时 reason 描述失败原因
        """
        shopify_prod = self.parse_shopify_json(shopify_json_str)
        if not shopify_prod:
            reason = "JSON解析失败"
            logger.warning(f"Shopify JSON 解析失败: {shopify_json_str[:200]}")
            return False, reason

        product_title = shopify_prod.get("title", "?")
        wc_payload = self.map_shopify_to_wc(shopify_prod)
        if not wc_payload:
            reason = f"数据映射失败（缺少title或variants）: {product_title}"
            logger.warning(f"Shopify→WooCommerce 映射失败: {product_title}")
            return False, reason

        result, reason = self.upsert_product(wc_payload)
        ok = result is not None
        time.sleep(random.uniform(0.5, 1.2))
        return ok, reason


class WooImportService:
    def __init__(self):
        self.upload_variants = False

    @staticmethod
    def _get_imported_sites(row) -> list:
        """从 imported_result 中读取已成功导入的站点ID列表"""
        try:
            result = json.loads(row.imported_result or "{}")
            sites = result.get("imported_sites", [])
            return sites if isinstance(sites, list) else []
        except Exception:
            return []

    async def select_products_for_site(self, site: Site, import_count: int = None) -> List:
        """选择待导入的产品列表（仅 DB 查询 + 标记 assigned，不执行 HTTP 同步）。

        - 产品可分配给多个不同站点，但不重复分配给同一站点
        - 失败产品自动放回全局池
        """
        from app.utils.provider_resolver import ProviderResolver
        if import_count is None:
            import_count = int(await ProviderResolver.get_config("woo", "import_product_count", default="10"))

        # 查分配池：该站点已分配但尚未成功导入的产品
        rows = await ShopifyProduct.filter(
            imported_site_id=site.id,
            imported_status__in=["assigned", "failed"],
        ).all()

        # 把失败的产品放回全局池，避免每次都是同一批失败产品
        failed_rows = [r for r in rows if r.imported_status == "failed"]
        assigned_rows = [r for r in rows if r.imported_status == "assigned"]
        if failed_rows:
            for r in failed_rows:
                r.imported_site_id = None
                r.imported_status = ""
                await r.save()
            rows = assigned_rows

        if not rows:
            # 分配池为空 → 从 ready 产品中分配
            # 排除 imported_status="assigned"（已分配给其他站点），但保留 "success"/"failed"/"" 
            # 因为同一产品可导入到多个不同站点
            ready = await ShopifyProduct.filter(
                status="ready",
                imported_status__not="assigned",
            ).all()
            # 过滤已成功导入过本站点的产品
            available = [r for r in ready if site.id not in self._get_imported_sites(r)]
            if not available:
                return []
            import random as _random
            _random.shuffle(available)
            # 尽量保证导入数量不变：跳过已导入的，用可用产品补足
            rows = available[:import_count]
            for r in rows:
                r.imported_site_id = site.id
                r.imported_status = "assigned"
                await r.save()
        else:
            # 分配池有货 → 随机选取
            import random as _random
            _random.shuffle(rows)
            rows = rows[:import_count]

        return rows

    async def import_for_site(self, site: Site, product_ids: list[int] = None,
                              pre_selected_rows: List = None) -> Dict[str, Any]:
        """导入产品到 WooCommerce 站点。

        - product_ids=None, pre_selected_rows=None: 站点列表「导入」，自动选择产品
        - product_ids=指定列表: 产品列表「导入到站点」，直接导入指定产品
        - pre_selected_rows: 已通过 select_products_for_site 选好的产品列表（跳过选择阶段）
        """
        site_cfg = {
            "wc_url": (site.login_url or "").replace("/wp-admin", "").rstrip("/"),
            "consumer_key": site.woo_ck or "",
            "consumer_secret": site.woo_cs or "",
        }
        if not site_cfg["wc_url"] or not site_cfg["consumer_key"] or not site_cfg["consumer_secret"]:
            raise ProviderConfigError("woo", "woo_ck/woo_cs/wc_url", "WooCommerce 配置不完整，无法执行导入")

        # 产品选择阶段
        if pre_selected_rows is not None:
            rows = pre_selected_rows
        elif product_ids:
            rows = await ShopifyProduct.filter(id__in=product_ids).all()
            if not rows:
                return {"ok": False, "reason": "指定产品不存在"}
            # 标记为 assigned（如果尚未标记）
            for r in rows:
                if r.imported_site_id != site.id or r.imported_status != "assigned":
                    r.imported_site_id = site.id
                    r.imported_status = "assigned"
                    await r.save()
        else:
            rows = await self.select_products_for_site(site)
            if not rows:
                return {"ok": False, "reason": "没有可用的 ready 产品供分配"}

        # 读取导入行为配置
        from app.utils.provider_resolver import ProviderResolver
        enable_images = (await ProviderResolver.get_config("woo", "enable_images", default="true")).lower() == "true"
        max_images = int(await ProviderResolver.get_config("woo", "max_images_per_product", default="5"))
        upload_variants = (await ProviderResolver.get_config("woo", "upload_variants", default="false")).lower() == "true"
        check_existing = (await ProviderResolver.get_config("woo", "check_existing_before_create", default="true")).lower() == "true"
        wp_async_images = (await ProviderResolver.get_config("woo", "wp_async_images", default="false")).lower() == "true"
        import_interval_ms = int(await ProviderResolver.get_config("woo", "import_interval_ms", default="200"))

        logger.info(
            "导入配置: enable_images=%s, max_images=%s, upload_variants=%s, wp_async_images=%s, interval=%sms, site=%s",
            enable_images, max_images, upload_variants, wp_async_images, import_interval_ms, site.domain,
        )

        syncer = WooCommerceSyncer(
            wc_url=site_cfg["wc_url"],
            consumer_key=site_cfg["consumer_key"],
            consumer_secret=site_cfg["consumer_secret"],
            upload_variants=upload_variants,
            enable_images=enable_images,
            max_images_per_product=max_images,
            check_existing_before_create=check_existing,
            wp_async_images=wp_async_images,
            import_interval_ms=import_interval_ms,
        )

        loop = asyncio.get_event_loop()

        # 导入前先测试 WooCommerce API 连通性（在线程池中执行，避免阻塞事件循环）
        try:
            test_resp = await loop.run_in_executor(
                None,
                lambda: syncer.limiter.request(
                    "GET", syncer.wc_api_url,
                    auth=syncer.wc_auth,
                    params={"per_page": 1},
                    max_retries=0,
                ),
            )
            if test_resp.status_code == 401:
                return {"ok": False, "reason": "WooCommerce API 认证失败，请检查 Consumer Key/Secret"}
            elif test_resp.status_code >= 500:
                return {"ok": False, "reason": f"WooCommerce API 服务端错误 (HTTP {test_resp.status_code})"}
            elif test_resp.status_code == 404:
                return {"ok": False, "reason": "WooCommerce REST API 未找到，请确认已安装 WooCommerce 插件"}
        except Exception as e:
            return {"ok": False, "reason": f"无法连接 WooCommerce API: {e}"}

        success = 0
        skip = 0
        skip_details = []
        sync_id_list = []
        consecutive_502 = 0  # 连续 502 计数器（用于指数退避）

        for row in rows:
            # 提取 SKU
            product_title = row.title or ""
            sku = ""
            try:
                prod_data = json.loads(row.prod_info_json or "{}")
                prod = prod_data.get("product", prod_data)
                variants = prod.get("variants", [])
                sku = (variants[0].get("sku") or "") if variants else prod.get("handle", "")
            except Exception:
                pass

            # 连续 502 → 指数退避等待
            if consecutive_502 >= 2:
                backoff = min(30 * (2 ** (consecutive_502 - 2)), 120)
                logger.warning("[502退避] 连续%d次502，等待%ds", consecutive_502, backoff)
                time.sleep(backoff)

            # 单条同步（在线程池中执行，避免阻塞事件循环）
            ok, reason = await loop.run_in_executor(
                None, syncer.sync_single_shopify_item, row.prod_info_json,
            )

            if ok:
                success += 1
                sync_id_list.append(row.id)
                row.imported_status = "success"
                sites_history = self._get_imported_sites(row)
                if site.id not in sites_history:
                    sites_history.append(site.id)
                row.imported_result = json.dumps(
                    {"imported": True, "site_id": site.id, "site_domain": site.domain, "imported_sites": sites_history},
                    ensure_ascii=False,
                )
                consecutive_502 = 0
            else:
                skip += 1
                row.imported_status = "failed"
                row.imported_result = json.dumps(
                    {"imported": False, "site_id": site.id, "site_domain": site.domain, "reason": reason, "imported_sites": self._get_imported_sites(row)},
                    ensure_ascii=False,
                )
                skip_details.append({"id": row.id, "title": product_title, "sku": sku, "reason": reason})

                # 连续 502 计数
                if "502" in (reason or ""):
                    consecutive_502 += 1
                else:
                    consecutive_502 = 0

                # 认证失败 → 中止整个站点的导入
                if "401" in reason or "认证失败" in reason:
                    await row.save()
                    break
            await row.save()

            # 产品间间隔，缓解 PHP-FPM 压力（可通过 woo.import_interval_ms 配置）
            if syncer.import_interval_ms > 0:
                time.sleep(syncer.import_interval_ms / 1000.0)

        result = {
            "ok": True,
            "domain": site.domain,
            "success": success,
            "skip": skip,
            "sync_ids": sync_id_list,
            "skip_details": skip_details,
        }

        site.pipeline_status = "woo_import:success" if success > 0 else "woo_import:failed"
        site.woo_import_status = f"成功{success}" if success > 0 else "导入失败"
        from app.utils.config_reader import get_provider_info_async as get_provider_info
        provider_info = await get_provider_info("woo")
        log_data = {"source": "woo_import", "result": result, "provider": provider_info}
        site.pipeline_log = (site.pipeline_log or "") + "\n" + json.dumps(log_data, ensure_ascii=False)
        await site.save()

        return result
