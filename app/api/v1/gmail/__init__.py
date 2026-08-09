from fastapi import APIRouter
from .gmail import router
from .registration import router as registration_router

gmail_router = APIRouter()
# 注册子路由必须先挂载，避免与 gmail 根路由的路径匹配冲突
gmail_router.include_router(registration_router, prefix='/registration', tags=['Gmail注册'])
gmail_router.include_router(router, tags=['Gmail管理'])

__all__ = ['gmail_router']
