from fastapi import APIRouter

from app.core.dependency import DependPermission

from .apis import apis_router
from .auditlog import auditlog_router
from .base import base_router
from .config import config_router, provider_router
from .accounts import accounts_router
from .depts import depts_router
from .menus import menus_router
from .roles import roles_router
from .users import users_router
from .site_pipeline import site_pipeline_router, feed_download_router
from .gmail import gmail_router
from .shopify import shopify_router
from .operation_jobs import operation_job_router
from .imports import import_router, template_router
from .recycle_bin import router as recycle_bin_router

v1_router = APIRouter()

v1_router.include_router(base_router, prefix="/base")
v1_router.include_router(users_router, prefix="/user", dependencies=[DependPermission])
v1_router.include_router(roles_router, prefix="/role", dependencies=[DependPermission])
v1_router.include_router(menus_router, prefix="/menu", dependencies=[DependPermission])
v1_router.include_router(apis_router, prefix="/api", dependencies=[DependPermission])
v1_router.include_router(depts_router, prefix="/dept", dependencies=[DependPermission])
v1_router.include_router(auditlog_router, prefix="/auditlog", dependencies=[DependPermission])
v1_router.include_router(config_router, prefix="/config", dependencies=[DependPermission])
v1_router.include_router(accounts_router, prefix="/account", dependencies=[DependPermission])
v1_router.include_router(provider_router, prefix="/config-provider", dependencies=[DependPermission])

# Feed 下载路由 — 无需认证（供 Google 远程抓取）
v1_router.include_router(feed_download_router, prefix="/site-pipeline/feed")

v1_router.include_router(site_pipeline_router, prefix="/site-pipeline", dependencies=[DependPermission])

v1_router.include_router(gmail_router, prefix="/gmail", dependencies=[DependPermission])

v1_router.include_router(shopify_router, prefix="/shopify", dependencies=[DependPermission])

v1_router.include_router(operation_job_router, prefix="/operation-jobs", dependencies=[DependPermission])

v1_router.include_router(template_router, prefix="/import")  # 模板下载无需认证，须在 import_router 之前注册
v1_router.include_router(import_router, prefix="/import", dependencies=[DependPermission])

v1_router.include_router(recycle_bin_router, prefix="/recycle-bin", dependencies=[DependPermission])
