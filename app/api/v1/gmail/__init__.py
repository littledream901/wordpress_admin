from fastapi import APIRouter
from .gmail import router

gmail_router = APIRouter()
gmail_router.include_router(router, tags=['Gmail管理'])

__all__ = ['gmail_router']
