from fastapi import APIRouter

from .outlook import router

outlook_router = APIRouter()
outlook_router.include_router(router, tags=['Outlook管理'])

__all__ = ['outlook_router']
