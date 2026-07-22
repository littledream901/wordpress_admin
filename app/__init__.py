from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import time

try:
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from starlette.middleware.base import BaseHTTPMiddleware
    from tortoise import Tortoise

    from app.core.exceptions import SettingNotFound
    from app.core.init_app import (
        init_configs,
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

        # 生产环境高风险配置告警
        if not settings.DEBUG:
            for w in settings.validate_production_settings():
                logger.warning(f"[配置] {w}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """应用启动：横幅 → ORM → 建表/种子 → 定时任务 → 总结"""

        # ── 启动横幅 ──
        conn_cfg = settings.TORTOISE_ORM["connections"]["default"]
        engine = conn_cfg.get("engine", "").split(".")[-1]  # tortoise.backends.mysql → mysql
        db_name = conn_cfg.get("credentials", {}).get("database", "")
        db_info = f"{engine}://{db_name}"[:60]
        env_tag = "开发模式" if settings.DEBUG else "生产模式"
        logger.info(f"── {settings.APP_TITLE} v{settings.VERSION} ──")
        logger.info(f"   {env_tag}  |  {db_info}")

        t0 = time.perf_counter()

        await Tortoise.init(config=settings.TORTOISE_ORM)

        # ── ORM 隔离初始化（记录主事件循环，用于跨线程污染检测）──
        try:
            from app.utils.orm_guard import _capture_main_loop
            _capture_main_loop()
        except Exception:
            pass  # 非关键路径，静默跳过

        # 预热连接池：必须在 init_essential() 之前执行
        # 把 minsize 个连接全部并行建好，避免首波请求排队等连接
        # 单次 MySQL 连接耗时 ~4.5s，不预热则首波请求全部阻塞
        try:
            from tortoise import connections
            conn = connections.get("default")
            minsize = settings.TORTOISE_ORM["connections"]["default"].get("minsize", 5)
            await asyncio.gather(*[conn.execute_query("SELECT 1") for _ in range(minsize)])
            logger.info("[Startup] 连接池已预热 (%d 连接)", minsize)
        except Exception:
            pass

        await init_essential()
        await init_superuser()
        await init_configs()

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
                        logger.info(f"[Feed] 定时清理: 已删除 {len(expired)} 个过期文件")
                except Exception:
                    pass  # 静默忽略，避免阻塞主流程

        asyncio.create_task(_cleanup_loop())

        # 后台任务：GMC 定时巡检
        async def _gmc_cron_loop():
            from app.cron.gmc_check import run_gmc_cron_loop
            await run_gmc_cron_loop()

        asyncio.create_task(_gmc_cron_loop())

        total = time.perf_counter() - t0
        logger.info(f"[Startup] 启动完成 ({total:.1f}s)")

        yield
        logger.info("[Shutdown] 应用关闭")
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
