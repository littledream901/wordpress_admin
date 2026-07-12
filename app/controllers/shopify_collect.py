from app.core.crud import CRUDBase
from app.models.shopify_collect import ShopifyProduct, ShopifySource
from app.schemas.shopify_collect import ShopifyProductUpdate, ShopifySourceCreate, ShopifySourceUpdate


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
