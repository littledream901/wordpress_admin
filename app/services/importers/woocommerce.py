"""WooCommerce 产品导入器（WordPress 平台）— 委托到现有 WooImportService。"""

import logging

from app.services.woo_import_service import WooImportService
from . import BaseProductImporter

_log = logging.getLogger(__name__)


class WooCommerceProductImporter(BaseProductImporter):
    """WooCommerce REST API 产品导入器。"""

    def __init__(self):
        self._service = WooImportService()

    async def import_products(self, site, shopify_products: list) -> dict:
        """委托到 WooImportService.import_for_site。"""
        return await self._service.import_for_site(site, pre_selected_rows=shopify_products)


woocommerce_importer = WooCommerceProductImporter()
