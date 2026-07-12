from typing import Optional
from pydantic import BaseModel


class ShopifySourceCreate(BaseModel):
    source_url: str
    source_type: str = 'collection'
    status: str = 'pending'
    max_products: int = 0
    remark: str = ''


class ShopifySourceUpdate(BaseModel):
    id: int
    source_url: Optional[str] = ''
    source_type: Optional[str] = 'collection'
    status: Optional[str] = ''
    max_products: Optional[int] = 0
    remark: Optional[str] = ''


class ShopifyProductUpdate(BaseModel):
    id: int
    status: Optional[str] = ''
    imported_site_id: Optional[int] = None
    imported_status: Optional[str] = ''
    imported_result: Optional[str] = ''
