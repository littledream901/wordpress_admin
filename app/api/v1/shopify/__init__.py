from fastapi import APIRouter
from .shopify import router

shopify_router = APIRouter()
shopify_router.include_router(router, tags=['Shopify采集'])

__all__ = ['shopify_router']
