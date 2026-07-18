from fastapi import APIRouter
from .site_pipeline import router
from .onepanel_monitor import router as monitor_router
from .feed import router as feed_router, feed_download_router
from .ads import router as ads_router

site_pipeline_router = APIRouter()
site_pipeline_router.include_router(router, tags=['站点流水线'])
site_pipeline_router.include_router(monitor_router, tags=['站点流水线'])
site_pipeline_router.include_router(feed_router, prefix='/feed', tags=['Feed管理'])
site_pipeline_router.include_router(ads_router, tags=['ADS管理'])

__all__ = ['site_pipeline_router', 'feed_download_router']
