from contextlib import asynccontextmanager
from pathlib import Path
import asyncio

try:
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from starlette.middleware.base import BaseHTTPMiddleware
    from tortoise import Tortoise

    from app.core.exceptions import SettingNotFound
    from app.core.init_app import (
        init_essential,
        init_superuser,
        make_middlewares,
        register_exceptions,
        register_routers,
    )
    from app.log import logger

    try:
        from app.settings.config import settings
    except ImportError:
        raise SettingNotFound("Can not import settings")
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


if _HAS_FASTAPI:

    def _validate_settings():
        """启动时校验关键配置，缺失则阻止启动"""
        if not settings.SECRET_KEY:
            raise SettingNotFound(
                "SECRET_KEY 未设置，请在 .env 中配置。\n"
                "  生成命令: openssl rand -hex 32"
            )
        if not settings.DEFAULT_PASSWORD:
            logger.warning("DEFAULT_PASSWORD 未设置，新用户创建将使用空密码")
        if not settings.DEBUG:
            if settings.CORS_ORIGINS == ["*"] or settings.CORS_ORIGINS == ["http://localhost"]:
                logger.warning(
                    "CORS_ORIGINS 为默认值（[\"*\"] 或 [\"http://localhost\"]），"
                    "生产环境建议指定具体域名。"
                    "  示例: CORS_ORIGINS=[\"https://your-domain.com\"]"
                )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """应用启动：DB 迁移 + 定时清理 + 僵尸任务清理。

        完整初始化请运行: python scripts/init_system.py
        """
        await init_essential()
        await init_superuser()

        # 后台任务：每小时清理过期的 Feed 文件
        async def _cleanup_loop():
            while True:
                await asyncio.sleep(3600)
                try:
                    from app.models.feed_file import FeedFile
                    import os
                    from datetime import datetime
                    expired = await FeedFile.filter(
                        status="replaced",
                        expires_at__isnull=False,
                        expires_at__lt=datetime.now(),
                    ).all()
                    for feed in expired:
                        for fpath in (feed.processed_file,):
                            if fpath and os.path.exists(fpath):
                                os.remove(fpath)
                        await feed.delete()
                    if expired:
                        logger.info(f"[feed] 定时清理: 已删除 {len(expired)} 个过期文件")
                except Exception:
                    pass  # 静默忽略，避免阻塞主流程

        asyncio.create_task(_cleanup_loop())

        yield
        await Tortoise.close_connections()

    def create_app() -> FastAPI:
        _validate_settings()

        app = FastAPI(
            title=settings.APP_TITLE,
            description=settings.APP_DESCRIPTION,
            version=settings.VERSION,
            debug=settings.DEBUG,
            # 生产环境关闭 API 文档
            openapi_url="/openapi.json" if settings.DEBUG else None,
            docs_url="/docs" if settings.DEBUG else None,
            redoc_url="/redoc" if settings.DEBUG else None,
            middleware=make_middlewares(),
            lifespan=lifespan,
        )
        register_exceptions(app)
        register_routers(app, prefix="/api")

        # 静态文件服务（头像上传）
        static_dir = Path("static")
        static_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        # 响应头注入 X-Trace-ID
        @app.middleware("http")
        async def _add_trace_header(request, call_next):
            response = await call_next(request)
            tid = getattr(request.state, "trace_id", None)
            if tid:
                response.headers["X-Trace-ID"] = tid
            return response

        return app

    app = create_app()
