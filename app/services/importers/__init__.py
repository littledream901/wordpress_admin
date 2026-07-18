"""产品导入器 — 按平台类型分发。

支持平台:
  - wordpress   → WooCommerceProductImporter (REST API 导入到 WooCommerce)
  - shopify     → ShopifyProductImporter (Admin API 导入到 Shopify Store)
"""

import logging
from abc import ABC, abstractmethod

_log = logging.getLogger(__name__)


class BaseProductImporter(ABC):
    """产品导入器抽象基类。"""

    @abstractmethod
    async def import_products(self, site, shopify_products: list) -> dict:
        """将 Shopify 采集产品导入到目标平台。

        Args:
            site: Site 模型实例
            shopify_products: ShopifyProduct 模型实例列表（含 product_json）

        Returns:
            dict: {"ok": True/False, "imported": int, "failed": int, "errors": [...]}
        """
        ...

    async def batch_import(self, site, shopify_products: list) -> dict:
        """批量导入，默认复用 import_products。子类可覆盖添加前置校验。"""
        return await self.import_products(site, shopify_products)


def get_importer(platform: str) -> BaseProductImporter:
    """根据平台类型返回对应的产品导入器实例。"""
    platform = (platform or '').strip().lower()
    if platform == 'shopify':
        from app.services.importers.shopify import shopify_importer
        return shopify_importer
    # 默认 wordpress
    from app.services.importers.woocommerce import woocommerce_importer
    return woocommerce_importer
