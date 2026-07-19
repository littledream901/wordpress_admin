"""
应用初始化模块
├── App Factory    : 中间件注册、异常处理注册、路由注册
├── Data Definitions : 菜单声明式定义
├── Schema Migration : 数据库建表 + ALTER TABLE 补丁
├── Seed Data        : 超级用户、菜单、配置、Provider、API、角色
└── Infrastructure   : 僵尸任务清理、分布式锁、启动入口
"""

from datetime import datetime, timedelta
import os
import time
import uuid

from fastapi import FastAPI
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import (
    HTTPException,
    RequestValidationError,
    ResponseValidationError,
)
from tortoise.exceptions import DoesNotExist, IntegrityError
from tortoise.expressions import Q

from app.api import api_router
from app.controllers.api import api_controller
from app.controllers.user import UserCreate, user_controller
from app.log import logger
from app.models.admin import Api, Menu, Role
from app.models.config import Config
from app.models.config_provider import ConfigProvider, ProviderConfigItem
from app.schemas.menus import MenuType
from app.settings.config import settings

from app.core.exceptions import (
    ExternalAPIError,
    ProviderConfigError,
    ResourceBusyError,
)
from app.core.exception_handlers import (
    DoesNotExistHandle,
    HttpExcHandle,
    IntegrityHandle,
    ProviderConfigErrorHandle,
    RequestValidationHandle,
    ResourceBusyHandle,
    ResponseValidationHandle,
    ServiceErrorHandle,
)
from .middlewares import (
    AccessLogMiddleware,
    BackGroundTaskMiddleware,
    HttpAuditLogMiddleware,
    TraceIDMiddleware,
)
from .rate_limit import RateLimitMiddleware


# ═══════════════════════════════════════════════════════════════════════════=
#  Section 1: App Factory
# ═══════════════════════════════════════════════════════════════════════════=

def make_middlewares():
    """构建中间件列表（按顺序执行）"""
    return [
        Middleware(TraceIDMiddleware),
        Middleware(AccessLogMiddleware),
        Middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
            allow_methods=settings.CORS_ALLOW_METHODS,
            allow_headers=settings.CORS_ALLOW_HEADERS,
        ),
        Middleware(RateLimitMiddleware),
        Middleware(BackGroundTaskMiddleware),
        Middleware(
            HttpAuditLogMiddleware,
            methods=["GET", "POST", "PUT", "DELETE"],
            exclude_paths=settings.AUDIT_EXCLUDE_PATHS or [
                "/api/v1/base/access_token",
                "/api/v1/import",
                "/api/v1/site-pipeline/feed/download",
                "/api/v1/user/avatar/upload",
                "/static",
                "/docs",
                "/openapi.json",
            ],
        ),
    ]


def register_exceptions(app: FastAPI):
    """注册全局异常处理器"""
    app.add_exception_handler(DoesNotExist, DoesNotExistHandle)
    app.add_exception_handler(HTTPException, HttpExcHandle)
    app.add_exception_handler(IntegrityError, IntegrityHandle)
    app.add_exception_handler(RequestValidationError, RequestValidationHandle)
    app.add_exception_handler(ResponseValidationError, ResponseValidationHandle)
    app.add_exception_handler(ExternalAPIError, ServiceErrorHandle)
    app.add_exception_handler(ResourceBusyError, ResourceBusyHandle)
    app.add_exception_handler(ProviderConfigError, ProviderConfigErrorHandle)


def register_routers(app: FastAPI, prefix: str = "/api"):
    """注册 API 路由"""
    app.include_router(api_router, prefix=prefix)


# ════════════════════════════════════════════════════════════════════════════
#  Section 2: Data Definitions
# ════════════════════════════════════════════════════════════════════════════

# 菜单声明式定义
# 格式: (name, path, parent_path, menu_type, order, icon, is_hidden, component, redirect)
# parent_path 为空字符串或 "/" 表示根级菜单
MENU_DEFINITIONS = [
    # ── 站点流水线 ──
    ("站点流水线",     "/site-pipeline",      "",              MenuType.CATALOG, 10, "mdi:web",                                   0, "Layout", "/site-pipeline/site-list"),
    ("站点管理",       "site-list",           "/site-pipeline", MenuType.MENU,    1,  "mdi:server-network",                       0, "/site-pipeline/site-list", None),
    ("Hub分发",        "hub-dispatch",        "/site-pipeline", MenuType.MENU,    2,  "mdi:cloud-upload-outline",                 0, "/site-pipeline/hub-dispatch", None),
    ("Hub任务列表",    "hub-jobs",            "/site-pipeline", MenuType.MENU,    3,  "mdi:clipboard-list-outline",               0, "/site-pipeline/hub-jobs", None),
    ("Feed管理",       "feed-manager",        "/site-pipeline", MenuType.MENU,    5,  "mdi:file-replace-outline",                 0, "/site-pipeline/feed-manager", None),
    ("ADS管理",        "ads-manager",         "/site-pipeline", MenuType.MENU,    6,  "mdi:monitor-eye",                           0, "/site-pipeline/ads-manager", None),
    # ── Gmail 管理 ──
    ("Gmail管理",      "/gmail",              "",              MenuType.CATALOG, 20, "mdi:gmail",                                  0, "Layout", "/gmail/account-list"),
    ("Gmail账号",      "account-list",        "/gmail",        MenuType.MENU,    1,  "basil:gmail-solid",                         0, "/gmail/account-list", None),
    # ── Shopify 采集 ──
    ("Shopify采集",    "/shopify",            "",              MenuType.CATALOG, 30, "mdi:shopping-search",                        0, "Layout", "/shopify/source-list"),
    ("待采集列表",     "source-list",         "/shopify",      MenuType.MENU,    1,  "mdi:link-variant",                          0, "/shopify/source-list", None),
    ("产品列表",       "product-list",        "/shopify",      MenuType.MENU,    2,  "mdi:package-variant-closed",                0, "/shopify/product-list", None),
    # ── 配置管理 ──
    ("配置管理",       "/config",             "",              MenuType.CATALOG, 40, "carbon:settings",                            0, "Layout", "/config/manage"),
    ("配置中心",       "manage",              "/config",       MenuType.MENU,    1,  "carbon:settings-adjust",                    0, "/config/manage", None),
    ("资源绑定",       "bindings",            "/config",       MenuType.MENU,    2,  "carbon:ibm-cloud-pak-manta-automated-data-lineage", 0, "/config/bindings", None),
    ("账号管理",       "accounts",            "/config",       MenuType.MENU,    3,  "carbon:user-identification",                0, "/config/accounts", None),
    ("回收站",         "recycle",             "/config",       MenuType.MENU,    4,  "mdi:delete-restore",                         0, "/config/recycle", None),
    # ── 任务中心 ──
    ("任务中心",       "/operation-jobs",     "",              MenuType.CATALOG, 50, "carbon:task",                                0, "Layout", "/operation-jobs/job-list"),
    ("任务列表",       "job-list",            "/operation-jobs", MenuType.MENU,  1,  "carbon:task-view",                          0, "/operation-jobs/job-list", None),
    ("导入记录",       "import-logs",         "/operation-jobs", MenuType.MENU,  2,  "carbon:document-import",                    0, "/operation-jobs/import-logs", None),
    # ── 系统管理 ──
    ("系统管理",       "/system",             "",              MenuType.CATALOG, 98, "carbon:gui-management",                      0, "Layout", "/system/user"),
    ("用户管理",       "user",                "/system",       MenuType.MENU,    1,  "material-symbols:person-outline-rounded",   0, "/system/user", None),
    ("角色管理",       "role",                "/system",       MenuType.MENU,    2,  "carbon:user-role",                          0, "/system/role", None),
    ("菜单管理",       "menu",                "/system",       MenuType.MENU,    3,  "material-symbols:list-alt-outline",         0, "/system/menu", None),
    ("API管理",        "api",                 "/system",       MenuType.MENU,    4,  "ant-design:api-outlined",                   0, "/system/api", None),
    ("部门管理",       "dept",                "/system",       MenuType.MENU,    5,  "mingcute:department-line",                 0, "/system/dept", None),
    ("审计日志",       "auditlog",            "/system",       MenuType.MENU,    6,  "ph:clipboard-text-bold",                    0, "/system/auditlog", None),
]


# ════════════════════════════════════════════════════════════════════════════
#  Section 3: Schema Migration
# ════════════════════════════════════════════════════════════════════════════

async def init_db():
    """初始化数据库表结构。

    部署初期使用 safe=False 从模型定义全量建表。
    后续增量字段时改为 safe=True 并在末尾添加 ALTER TABLE 补丁。
    """
    from tortoise import Tortoise, connections

    # 确保 Tortoise 已初始化
    try:
        await Tortoise.init(config=settings.TORTOISE_ORM)
    except Exception:
        pass

    # 安全建表：仅创建不存在的表，已有表跳过
    await Tortoise.generate_schemas(safe=True)

    conn = connections.get("default")

    # ── SQLite 性能优化 ──
    if settings.DB_ENGINE == "sqlite":
        await conn.execute_query("PRAGMA journal_mode=WAL")
        await conn.execute_query("PRAGMA synchronous=NORMAL")
        await conn.execute_query("PRAGMA cache_size=-8000")  # 8MB cache
        logger.info("[init_db] SQLite WAL 模式已启用")

    # ── 后续增量字段补丁（部署后按需添加）──
    # 步骤：safe=False → safe=True，然后逐条添加 ALTER TABLE
    # 2025-07-19 全量补全：通过模型 vs 补丁交叉对比，统一补齐所有缺失列
    patches = [
        # -- site_pipeline_site --
        "ALTER TABLE site_pipeline_site ADD COLUMN woo_product_count INTEGER DEFAULT 0",
        "ALTER TABLE site_pipeline_site ADD COLUMN platform VARCHAR(32) DEFAULT 'wordpress'",
        "ALTER TABLE site_pipeline_site ADD COLUMN shopify_store_url VARCHAR(500) DEFAULT ''",
        "ALTER TABLE site_pipeline_site ADD COLUMN shopify_token VARCHAR(255) DEFAULT ''",
        "ALTER TABLE site_pipeline_site ADD COLUMN pipeline_log TEXT DEFAULT ''",
        "ALTER TABLE site_pipeline_site ADD COLUMN hub_account_id VARCHAR(255) DEFAULT ''",
        "ALTER TABLE site_pipeline_site ADD COLUMN hub_last_action VARCHAR(64) DEFAULT ''",
        "ALTER TABLE site_pipeline_site ADD COLUMN woo_import_status VARCHAR(64) DEFAULT ''",
        "ALTER TABLE site_pipeline_site ADD COLUMN gmc_status VARCHAR(64) DEFAULT ''",
        "ALTER TABLE site_pipeline_site ADD COLUMN gmc_data TEXT DEFAULT ''",
        # -- user --
        "ALTER TABLE user ADD COLUMN is_superuser BOOLEAN DEFAULT 0",
        "ALTER TABLE user ADD COLUMN is_active BOOLEAN DEFAULT 1",
        "ALTER TABLE user ADD COLUMN alias VARCHAR(30)",
        "ALTER TABLE user ADD COLUMN avatar VARCHAR(512) DEFAULT ''",
        "ALTER TABLE user ADD COLUMN last_login DATETIME",
        "ALTER TABLE user ADD COLUMN dept_id INTEGER",
        # -- operation_job --
        "ALTER TABLE operation_job ADD COLUMN step VARCHAR(64) DEFAULT ''",
        "ALTER TABLE operation_job ADD COLUMN total_steps INTEGER DEFAULT 1",
        "ALTER TABLE operation_job ADD COLUMN worker_name VARCHAR(128) DEFAULT ''",
        "ALTER TABLE operation_job ADD COLUMN last_heartbeat DATETIME",
        "ALTER TABLE operation_job ADD COLUMN batch_id VARCHAR(64) DEFAULT ''",
        "ALTER TABLE operation_job ADD COLUMN retry_count INTEGER DEFAULT 0",
        "ALTER TABLE operation_job ADD COLUMN max_retry INTEGER DEFAULT 3",
        "ALTER TABLE operation_job ADD COLUMN started_at DATETIME",
        "ALTER TABLE operation_job ADD COLUMN finished_at DATETIME",
        # -- site_pipeline_hubstudio_job --
        "ALTER TABLE site_pipeline_hubstudio_job ADD COLUMN provider_id INTEGER DEFAULT 0",
        "ALTER TABLE site_pipeline_hubstudio_job ADD COLUMN worker_name VARCHAR(128) DEFAULT ''",
        "ALTER TABLE site_pipeline_hubstudio_job ADD COLUMN retry_count INTEGER DEFAULT 0",
        "ALTER TABLE site_pipeline_hubstudio_job ADD COLUMN started_at DATETIME",
        "ALTER TABLE site_pipeline_hubstudio_job ADD COLUMN finished_at DATETIME",
        # -- site_pipeline_hubstudio_agent_heartbeat --
        "ALTER TABLE site_pipeline_hubstudio_agent_heartbeat ADD COLUMN version VARCHAR(32) DEFAULT ''",
        "ALTER TABLE site_pipeline_hubstudio_agent_heartbeat ADD COLUMN host_info VARCHAR(255) DEFAULT ''",
        "ALTER TABLE site_pipeline_hubstudio_agent_heartbeat ADD COLUMN last_task_id INTEGER DEFAULT 0",
        "ALTER TABLE site_pipeline_hubstudio_agent_heartbeat ADD COLUMN last_task_status VARCHAR(32) DEFAULT ''",
        "ALTER TABLE site_pipeline_hubstudio_agent_heartbeat ADD COLUMN total_tasks INTEGER DEFAULT 0",
        # -- config --
        "ALTER TABLE config ADD COLUMN value TEXT DEFAULT ''",
        "ALTER TABLE config ADD COLUMN is_secret BOOLEAN DEFAULT 0",
        "ALTER TABLE config ADD COLUMN is_enabled BOOLEAN DEFAULT 1",
        # -- account --
        "ALTER TABLE account ADD COLUMN two_fa VARCHAR(500) DEFAULT ''",
        "ALTER TABLE account ADD COLUMN provider_id INTEGER",
        # -- config_provider --
        "ALTER TABLE config_provider ADD COLUMN tags VARCHAR(500) DEFAULT ''",
        # -- resource_provider_binding --
        "ALTER TABLE resource_provider_binding ADD COLUMN remark VARCHAR(500) DEFAULT ''",
        # -- site_pipeline_gmail_account --
        "ALTER TABLE site_pipeline_gmail_account ADD COLUMN assigned_site_domain VARCHAR(255) DEFAULT ''",
    ]
    for sql in patches:
        try:
            await conn.execute_query(sql)
        except Exception as e:
            if "duplicate column" not in str(e).lower():
                logger.warning(f"[init_db] 补丁失败: {e}")


# ════════════════════════════════════════════════════════════════════════════
#  Section 4: Seed Data
# ════════════════════════════════════════════════════════════════════════════

# ── 4.1 超级用户 ──

async def init_superuser():
    """首次启动创建默认超级管理员"""
    if await user_controller.model.exists():
        return
    await user_controller.create_user(
        UserCreate(
            username="admin",
            email="admin@admin.com",
            password=settings.DEFAULT_PASSWORD,
            is_active=True,
            is_superuser=True,
        )
    )


# ── 4.2 菜单 ──

async def init_menus():
    """根据 MENU_DEFINITIONS 声明式同步菜单：创建/更新新增菜单，隐藏废弃菜单"""

    await _deduplicate_menus()

    all_menus = await Menu.all()
    menu_lookup = {}       # (path, parent_id) -> Menu
    path_to_id = {}        # path -> id（用于父级查找）
    declared_paths = {d[1] for d in MENU_DEFINITIONS}

    for m in all_menus:
        menu_lookup[(m.path, m.parent_id)] = m

    root_items = [d for d in MENU_DEFINITIONS if d[2] in (None, "", "/")]
    child_items = [d for d in MENU_DEFINITIONS if d[2] not in (None, "", "/")]

    # 第 1 轮：根级菜单
    for (name, path, _, menu_type, order, icon, is_hidden, component, redirect) in root_items:
        existing = menu_lookup.get((path, 0))
        if existing:
            path_to_id[path] = existing.id
            await _sync_menu_fields(existing, name, menu_type, icon, order, is_hidden, component, redirect)
        else:
            menu = await Menu.create(
                name=name, path=path, parent_id=0, menu_type=menu_type,
                icon=icon, order=order, is_hidden=bool(is_hidden),
                component=component, keepalive=False, redirect=redirect,
            )
            menu_lookup[(path, 0)] = menu
            path_to_id[path] = menu.id
            logger.info(f"[init_menus] 新增菜单: {name} ({path})")

    # 第 2 轮：子级菜单（迭代直到全部处理）
    remaining = list(child_items)
    while remaining:
        processed = []
        for (name, path, parent_path, menu_type, order, icon, is_hidden, component, redirect) in remaining:
            if parent_path not in path_to_id:
                continue
            parent_id = path_to_id[parent_path]
            existing = menu_lookup.get((path, parent_id))
            if existing:
                path_to_id[path] = existing.id
                await _sync_menu_fields(existing, name, menu_type, icon, order, is_hidden, component, redirect)
            else:
                menu = await Menu.create(
                    name=name, path=path, parent_id=parent_id, menu_type=menu_type,
                    icon=icon, order=order, is_hidden=bool(is_hidden),
                    component=component, keepalive=False, redirect=redirect,
                )
                menu_lookup[(path, parent_id)] = menu
                path_to_id[path] = menu.id
                logger.info(f"[init_menus] 新增菜单: {name} ({path}, parent={parent_path})")
            processed.append((name, path, parent_path, menu_type, order,
                              icon, is_hidden, component, redirect))
        remaining = [r for r in remaining if r not in processed]
        if not processed:
            for (_, path, parent_path, *_) in remaining:
                logger.warning(f"[init_menus] 父菜单未定义: {parent_path}，跳过 {path}")
            break

    # 第 3 轮：隐藏废弃菜单
    for m in all_menus:
        if m.path not in declared_paths and not m.is_hidden:
            m.is_hidden = True
            await m.save(update_fields=["is_hidden"])
            logger.info(f"[init_menus] 废弃菜单已隐藏: {m.name} ({m.path})")


async def _deduplicate_menus():
    """清理 (path, parent_id) 重复的菜单，保留最早创建的那条"""
    from collections import defaultdict

    all_menus = await Menu.all().order_by("id")
    groups = defaultdict(list)
    for m in all_menus:
        groups[(m.path, m.parent_id)].append(m)

    for (path, parent_id), dup_list in groups.items():
        if len(dup_list) <= 1:
            continue
        keeper = dup_list[0]
        removed_ids = [m.id for m in dup_list[1:]]
        # 子菜单重定向到保留菜单
        await Menu.filter(parent_id__in=removed_ids).update(parent_id=keeper.id)
        # 清理角色关联后删除
        roles = await Role.filter(menus__id__in=removed_ids).all()
        for role in roles:
            await role.menus.remove(*removed_ids)
        await Menu.filter(id__in=removed_ids).delete()
        logger.warning(
            f"[init_menus] 清理重复菜单 path={path} parent_id={parent_id}: "
            f"保留 id={keeper.id}, 删除 {removed_ids}"
        )


async def _sync_menu_fields(menu, name, menu_type, icon, order, is_hidden, component, redirect):
    """按需更新菜单字段"""
    updated = False
    for field, new_val in [
        ("name", name), ("menu_type", menu_type), ("icon", icon),
        ("order", order), ("is_hidden", bool(is_hidden)),
        ("component", component), ("redirect", redirect),
    ]:
        if field == "is_hidden":
            old = bool(getattr(menu, field))
            if old != new_val:
                setattr(menu, field, new_val)
                updated = True
        elif getattr(menu, field) != new_val:
            setattr(menu, field, new_val)
            updated = True
    if updated:
        await menu.save()


# ── 4.3 全局配置（旧 Config 模型）──

async def init_configs():
    """初始化全局配置项（批量查询 + 批量写入缺失项）"""
    defaults = _config_defaults()
    existing_names = {c.name for c in await Config.all()}
    to_create = [
        Config(name=name, value=value, description=desc, category=cat,
               sort_order=order, is_secret=is_secret)
        for name, value, desc, cat, order, is_secret in defaults
        if name not in existing_names
    ]
    if to_create:
        await Config.bulk_create(to_create)
        logger.info(f"[init_configs] 批量新增 {len(to_create)} 个配置项")


def _config_defaults():
    """全局 Config 默认值定义"""
    return [
        # Cloudflare
        ("CF_API_TOKEN", "", "Cloudflare API Token", "cloudflare", 1, True),
        ("CF_ACCOUNT_ID", "", "Cloudflare Account ID", "cloudflare", 2, False),
        ("CF_PROXIED", "false", "是否启用 Cloudflare 代理", "cloudflare", 3, False),
        ("CF_TTL", "1", "DNS TTL 值（1=Auto）", "cloudflare", 5, False),
        ("CF_TIMEOUT", "30", "API 请求超时(秒)", "cloudflare", 6, False),
        # Dynadot
        ("DYNADOT_API_KEY", "", "Dynadot API Key", "dynadot", 1, True),
        ("DYNADOT_API_URL", "https://api.dynadot.com/api3.xml", "Dynadot API 地址", "dynadot", 2, False),
        ("DYNADOT_TIMEOUT", "30", "Dynadot API 超时(秒)", "dynadot", 3, False),
        # 1Panel
        ("OP_URL", "", "1Panel 面板地址", "onepanel", 1, False),
        ("OP_API_KEY", "", "1Panel API Key", "onepanel", 2, True),
        ("OP_WEBSITE_GROUP_ID", "1", "默认网站分组 ID", "onepanel", 3, False),
        ("OP_WP_APP_ID", "", "WordPress 应用 ID", "onepanel", 4, False),
        ("OP_WP_APP_DETAIL_ID", "", "WordPress 应用详情 ID", "onepanel", 5, False),
        ("OP_WP_APP_KEY", "wordpress", "WordPress 应用标识 Key", "onepanel", 6, False),
        ("OP_WP_APP_TYPE", "website", "WordPress 应用类型", "onepanel", 7, False),
        ("OP_WP_VERSION", "latest", "WordPress 版本", "onepanel", 8, False),
        ("OP_MAX_RETRIES", "3", "API 最大重试次数", "onepanel", 9, False),
        ("OP_RETRY_INTERVAL", "2", "重试间隔(秒)", "onepanel", 10, False),
        ("OP_TIMEOUT", "30", "API 超时(秒)", "onepanel", 11, False),
        ("OP_AUTO_CLEAN_CONFLICT", "false", "自动清理冲突站点", "onepanel", 12, False),
        ("OP_DELETE_SLEEP", "5", "删除站点后等待(秒)", "onepanel", 13, False),
        ("OP_OLD_SOURCE_DOMAIN", "", "建站后替换的旧域名", "onepanel", 14, False),
        ("WP_CONTAINER_MEMORY_LIMIT", "384", "WordPress容器内存限制(MB)", "onepanel", 15, False),
        ("WP_CONTAINER_MEMORY_UNIT", "MB", "WordPress容器内存单位", "onepanel", 16, False),
        # HubStudio
        ("HUBSTUDIO_BASE_URL", "http://127.0.0.1:6873", "HubStudio API 基础地址", "hubstudio", 1, False),
        ("HUBSTUDIO_APP_ID", "", "HubStudio App ID", "hubstudio", 2, False),
        ("HUBSTUDIO_APP_SECRET", "", "HubStudio App Secret", "hubstudio", 3, True),
        ("HUBSTUDIO_GROUP_CODE", "", "HubStudio 分组代码", "hubstudio", 4, False),
        ("HUBSTUDIO_TIMEOUT", "60", "HubStudio API 超时(秒)", "hubstudio", 5, False),
        ("HUBSTUDIO_CONNECTOR_DIR", r"D:\Program Files\Hubstudio", "HubStudio Connector 目录", "hubstudio", 6, False),
        ("HUBSTUDIO_EXE_NAME", "hubstudio_connector.exe", "Connector 可执行文件名", "hubstudio", 7, False),
        ("HUBSTUDIO_HTTP_PORT", "6873", "Connector HTTP 端口", "hubstudio", 8, False),
        ("HUBSTUDIO_DEFAULT_PROXY_TYPE_NAME", "不使用代理", "默认代理类型", "hubstudio", 9, False),
        ("HUBSTUDIO_DEFAULT_UI_LANGUAGE", "en", "默认浏览器语言", "hubstudio", 10, False),
        ("HUBSTUDIO_REAL_KERNEL_VERSION", "137", "真实内核版本号", "hubstudio", 11, False),
        ("HUBSTUDIO_ADMIN_SITE_NAME", "自定义平台", "管理平台名称", "hubstudio", 13, False),
        ("HUBSTUDIO_ADMIN_SITE_ALIAS", "WordPress后台", "管理平台别名", "hubstudio", 14, False),
        ("HUBSTUDIO_ADMIN_ACCOUNT_NAME", "admin", "默认管理员账号", "hubstudio", 15, False),
        ("HUBSTUDIO_ADMIN_ACCOUNT_PASSWORD", "", "默认管理员密码", "hubstudio", 16, True),
        # WooCommerce
        ("WOO_API_TIMEOUT", "30", "WooCommerce API 超时(秒)", "woo", 1, False),
        ("WOO_RATE_LIMIT_RPM", "30", "WooCommerce 每分钟请求限制", "woo", 2, False),
        ("WOO_RATE_LIMIT_RETRY", "3", "WooCommerce 限流重试次数", "woo", 3, False),
        # Shopify
        ("SHOPIFY_API_TIMEOUT", "30", "Shopify 采集超时(秒)", "shopify", 1, False),
        ("SHOPIFY_MAX_PRODUCTS_PER_SOURCE", "250", "每个采集源最大商品数", "shopify", 2, False),
    ]


# ── 4.4 Provider 配置 ──

async def init_providers():
    """初始化默认 Provider 实例 + 配置项，并清理废弃配置"""

    defaults = _provider_defaults()

    # ── 第 1 轮：确保所有 Provider 存在 ──
    existing_providers = {
        (p.provider_type, p.provider_name): p
        for p in await ConfigProvider.all()
    }
    providers_to_create = []
    for ptype, name, desc, priority, _ in defaults:
        key = (ptype, name)
        if key not in existing_providers:
            provider = ConfigProvider(
                provider_type=ptype, provider_name=name,
                description=desc, is_default=True, priority=priority,
                status="active",
            )
            existing_providers[key] = provider
            providers_to_create.append(provider)

    if providers_to_create:
        await ConfigProvider.bulk_create(providers_to_create)
        # bulk_create 不填充 id，重新查询
        existing_providers = {
            (p.provider_type, p.provider_name): p
            for p in await ConfigProvider.all()
        }
        logger.info(f"[init_providers] 批量新增 {len(providers_to_create)} 个 Provider")

    # ── 第 2 轮：批量创建缺失的配置项 ──
    all_existing_items = {
        (ci.provider_id, ci.config_key)
        for ci in await ProviderConfigItem.all()
    }
    items_to_create = []
    for ptype, name, _, _, items in defaults:
        provider = existing_providers[(ptype, name)]
        for i, (key, value, item_desc, config_type, is_secret, is_required) in enumerate(items):
            if (provider.id, key) not in all_existing_items:
                items_to_create.append(ProviderConfigItem(
                    provider_id=provider.id, config_key=key,
                    config_value=value, config_type=config_type,
                    is_secret=is_secret, is_required=is_required,
                    description=item_desc, sort=i,
                ))
    if items_to_create:
        await ProviderConfigItem.bulk_create(items_to_create)
        logger.info(f"[init_providers] 批量新增 {len(items_to_create)} 个配置项")

    # ── 清理已废弃的配置项 ──
    await _cleanup_deprecated_provider_items()


def _provider_defaults():
    """Provider 默认实例 + 配置项定义

    每个 entry: (provider_type, provider_name, description, priority, [
        (config_key, default_value, description, config_type, is_secret, is_required)
    ])
    """
    return [
        # ── Cloudflare ──
        ("cloudflare", "Cloudflare 主账号", "默认 Cloudflare API 配置", 100, [
            ("api_token",     "", "Cloudflare API Token", "token", True, True),
            ("account_id",    "", "Cloudflare Account ID", "string", False, True),
            ("proxied",       "true", "是否橙云代理", "bool", False, True),
            ("ttl",           "1", "DNS TTL 值 1=Auto", "int", False, True),
            ("timeout",       "30", "API 请求超时秒数", "int", False, False),
        ]),
        # ── Dynadot ──
        ("dynadot", "Dynadot 主账号", "默认 Dynadot API 配置", 100, [
            ("api_key",  "", "Dynadot API Key", "token", True, True),
            ("api_url",  "https://api.dynadot.com/api3.json", "Dynadot API 地址", "url", False, True),
            ("timeout",  "30", "API 超时秒数", "int", False, False),
        ]),
        # ── 1Panel ──
        ("onepanel", "生产1Panel节点A", "默认 1Panel 面板配置", 100, [
            ("url",                      "", "1Panel 面板地址", "url", False, True),
            ("api_key",                  "", "1Panel API Key", "token", True, True),
            ("website_group_id",         "1", "默认网站分组 ID", "int", False, True),
            ("panel_base",               "/opt/1panel", "1Panel 根目录", "path", False, True),
            ("wp_app_root",              "/opt/1panel/apps/wordpress", "WordPress 应用根目录", "path", False, True),
            ("wp_app_key",               "wordpress", "WordPress 应用 key", "string", False, True),
            ("wp_app_type",              "docker", "WordPress 应用类型", "string", False, True),
            ("wp_app_id",                "", "WordPress 应用商店 appId", "int", False, False),
            ("wp_app_detail_id",         "", "WordPress 应用商店 appDetailId", "int", False, False),
            ("wp_version",               "7.0.0", "WordPress 版本号", "string", False, True),
            ("wp_admin_user",            "admin", "WordPress 默认管理员用户名", "string", False, False),
            ("wp_admin_email_prefix",    "admin", "WordPress 管理员邮箱前缀", "string", False, False),
            ("backup_account_id",        "", "模板站备份账号 ID", "int", False, True),
            ("template_backup_path",     "", "模板站应用备份路径", "path", False, True),
            ("db_backup_path",           "", "模板站数据库备份路径", "path", False, True),
            ("old_source_domain",        "", "建站后替换的目标旧域名", "string", False, False),
            ("restore_mode",             "safe", "模板站恢复模式 safe/overwrite", "string", False, False),
            ("max_retries",              "3", "API 最大重试次数", "int", False, False),
            ("retry_interval",           "2", "API 重试间隔秒数", "int", False, False),
            ("timeout",                  "30", "API 请求超时秒数", "int", False, False),
            ("auto_clean_conflict_site", "false", "遇到已存在站点是否自动清理", "bool", False, False),
            ("delete_sleep",             "5", "删除站点后等待秒数", "int", False, False),
            ("enable_ssl",               "true", "是否申请 SSL 证书", "bool", False, False),
            ("force_https",              "true", "是否强制 HTTPS 跳转", "bool", False, False),
            ("ssl_ready_timeout",        "180", "SSL 证书就绪等待超时秒数", "int", False, False),
            ("wp_container_memory_limit", "384", "WordPress 容器内存限制 MB", "int", False, False),
            ("wp_container_memory_unit",  "MB", "WordPress 容器内存单位", "string", False, False),
            ("op_verify_ssl", "true", "1Panel API TLS 证书验证", "bool", False, False),
            ("wp_verify_ssl", "true", "WordPress 站点 TLS 证书验证", "bool", False, False),
            ("max_concurrent", "3", "最大同时建站数", "int", False, False),
        ]),
        # ── HubStudio ──
        ("hubstudio", "本地HubStudio节点A", "默认 HubStudio 配置", 100, [
            ("base_url",                  "http://127.0.0.1:6873", "HubStudio API 地址", "url", False, True),
            ("app_id",                    "", "HubStudio App ID", "string", True, True),
            ("app_secret",                "", "HubStudio App Secret", "token", True, True),
            ("group_code",                "", "HubStudio 分组代码", "string", False, True),
            ("timeout",                   "60", "API 超时秒数", "int", False, False),
            ("connector_dir",             "", "HubStudio Connector 安装目录", "path", False, True),
            ("exe_name",                  "hubstudio_connector.exe", "Connector EXE 名称", "string", False, True),
            ("http_port",                 "6873", "Connector 监听端口", "int", False, True),
            ("real_kernel_version",       "137", "浏览器内核版本", "int", False, False),
            ("default_proxy_type_name",   "不使用代理", "默认代理类型", "string", False, False),
            ("default_ui_language",       "en", "默认 UI 语言", "string", False, False),
            ("admin_site_name",           "自定义平台", "WordPress 后台站点名称", "string", False, False),
            ("admin_site_alias",          "WordPress后台", "WordPress 后台别名", "string", False, False),
            ("admin_account_name",        "admin", "默认后台管理员账号", "string", False, False),
            ("admin_account_password",    "", "默认后台管理员密码", "password", True, False),
            ("use_fixed_proxy",           "true", "是否启用固定代理", "bool", False, False),
            ("proxy_type_name",           "HTTP", "代理类型 HTTP/SOCKS5", "string", False, False),
            ("as_dynamic_type",           "1", "动态代理类型 1=动态", "int", False, False),
            ("proxy_host",                "server.iphtml.biz", "代理主机地址", "string", False, False),
            ("proxy_port",                "15000", "代理端口", "int", False, False),
            ("proxy_account",             "uid-27498-zone-hubstudio", "代理账号", "string", False, False),
            ("proxy_password",            "", "代理密码", "password", True, False),
            ("proxy_country_code",        "US", "代理国家码", "string", False, False),
            ("proxy_city",                "New York", "代理城市", "string", False, False),
            ("proxy_province",            "CA", "代理省份", "string", False, False),
            ("ip_get_rule_type",          "1", "IP 获取规则类型", "int", False, False),
        ]),
        # ── Shopify ──
        ("shopify", "Shopify采集默认配置", "默认 Shopify 采集配置", 100, [
            ("request_timeout", "30", "API 请求超时秒数", "int", False, False),
        ]),
        # ── WooCommerce ──
        ("woo", "WooCommerce 默认", "默认 WooCommerce 产品导入配置", 100, [
            ("request_timeout",            "120", "API 请求超时秒数", "int", False, False),
            ("retry_limit",                "2", "API 失败重试次数", "int", False, False),
            ("min_interval_seconds",       "2.5", "请求最小间隔秒数", "float", False, False),
            ("error_cooldown_seconds",     "30", "错误冷却秒数", "int", False, False),
            ("max_error_cooldown_seconds", "120", "最大错误冷却秒数", "int", False, False),
            ("import_product_count",       "10", "每次导入产品数量", "int", False, False),
            ("enable_images",              "true", "是否上传产品图片到 Woo", "bool", False, False),
            ("max_images_per_product",     "5", "每个产品最大图片数", "int", False, False),
            ("upload_variants",            "false", "是否上传变体产品", "bool", False, False),
            ("check_existing_before_create","true", "创建前按 SKU 查重", "bool", False, False),
        ]),
    ]


async def _cleanup_deprecated_provider_items():
    """清理数据库中已不再定义的废弃 Provider 配置项"""
    cleanup = {
        "woo":        ["random_import", "rate_limit_rpm", "rate_limit_retry"],
        "shopify":    ["page_sleep", "default_max_products", "user_agent"],
        "hubstudio":  ["business_group_name"],
        "pipeline":   ["random_assign_default_count", "shopify_default_max_products",
                       "woo_import_sample_count", "woo_request_timeout",
                       "retry_limit", "timeout_limit", "wp_container_memory_limit",
                       "wp_container_memory_unit", "op_verify_ssl", "wp_verify_ssl",
                       "max_concurrent", "feed_expire_days"],
        "onepanel":   ["auto_detect_wp_app", "restore_root_files", "woo_script",
                       "ctx_script", "woo_fetch_retries", "woo_fetch_interval", "ctk_token"],
    }
    for ptype, keys in cleanup.items():
        provider = await ConfigProvider.filter(provider_type=ptype, is_default=True).first()
        if provider:
            deleted = await ProviderConfigItem.filter(provider_id=provider.id, config_key__in=keys).delete()
            if deleted:
                logger.info(f"[init_providers] 清理 {ptype} Provider 废弃配置: {keys}")


# ── 4.5 API 同步 ──

async def init_apis():
    """每次启动刷新 API 记录，同步 summary 等变更"""
    await api_controller.refresh_api()


# ── 4.6 角色 ──

async def init_roles():
    """初始化角色并关联菜单/API"""
    if await Role.exists():
        await _sync_existing_roles()
    else:
        await _create_default_roles()


async def _create_default_roles():
    """首次创建默认角色（管理员 + 普通用户）"""
    admin_role = await Role.create(name="管理员", desc="管理员角色")
    user_role = await Role.create(name="普通用户", desc="普通用户角色")

    all_apis = await Api.all()
    all_menus = await Menu.all()

    await admin_role.apis.add(*all_apis)
    await admin_role.menus.add(*all_menus)
    await user_role.menus.add(*all_menus)
    await _grant_menu_apis(user_role, all_menus, all_apis)


async def _sync_existing_roles():
    """已有角色时，增量同步新增菜单 + 对应的 API（仅对已有父菜单的角色）"""
    all_menus = await Menu.all()
    all_menu_ids = {m.id for m in all_menus}
    all_apis = await Api.all()

    for role in await Role.all():
        role_menu_ids = {m.id for m in await role.menus.all()}
        missing_ids = all_menu_ids - role_menu_ids
        if not missing_ids:
            continue

        # 只添加该角色已有父菜单的新增菜单，防止越权授予
        missing_menus = []
        for m in all_menus:
            if m.id in missing_ids:
                # 根菜单（parent_id=0）且角色名是 "admin" 才自动添加
                if m.parent_id == 0:
                    if role.name.lower() == "admin":
                        missing_menus.append(m)
                # 子菜单：仅当角色已有其父菜单时才添加
                elif m.parent_id in role_menu_ids:
                    missing_menus.append(m)

        if missing_menus:
            await role.menus.add(*missing_menus)
            await _grant_menu_apis(role, missing_menus, all_apis)
            logger.info(f"[init_roles] 角色 {role.name} 新增菜单: {[m.name for m in missing_menus]}")


async def _grant_menu_apis(role, menus, all_apis=None):
    """将菜单对应的 API 自动授予角色（按 tags + 路径前缀匹配）"""
    if all_apis is None:
        all_apis = await Api.all()

    # 构建 menu id → parent 映射，用于子菜单查找根模块前缀
    all_menus = {m.id: m for m in await Menu.all()}

    matched_apis = []
    for menu in menus:
        # 收集菜单及其父链的路径前缀
        prefixes = _collect_menu_prefixes(menu, all_menus)
        for api in all_apis:
            if api in matched_apis:
                continue
            # 匹配规则1: API path 第三段命中任一前缀
            api_parts = api.path.strip("/").split("/")
            if len(api_parts) >= 3 and api_parts[0] == "api" and api_parts[1] == "v1":
                if api_parts[2] in prefixes:
                    matched_apis.append(api)
                    continue
            # 匹配规则2: API tags 去掉特殊字符后命中任一前缀
            clean_tag = _clean_segment(api.tags)
            for p in prefixes:
                if clean_tag and p and (clean_tag == p or clean_tag in p or p in clean_tag):
                    matched_apis.append(api)
                    break

    if matched_apis:
        existing_api_ids = {a.id for a in await role.apis.all()}
        new_apis = [a for a in matched_apis if a.id not in existing_api_ids]
        if new_apis:
            await role.apis.add(*new_apis)
            logger.info(f"[init_roles] 角色 {role.name} 新增 API: {len(new_apis)} 个")


def _clean_segment(s: str) -> str:
    """清理字符串：去斜杠、去连字符下划线、转小写"""
    return s.strip("/").replace("-", "").replace("_", "").lower()


def _collect_menu_prefixes(menu, all_menus_map: dict) -> set[str]:
    """收集菜单及其所有祖先路径的前缀段"""
    prefixes = set()
    current = menu
    while current:
        path = current.path.strip("/")
        # 取路径的每一段
        for seg in path.split("/"):
            clean = _clean_segment(seg)
            if clean:
                prefixes.add(clean)
        if current.parent_id and current.parent_id in all_menus_map:
            current = all_menus_map[current.parent_id]
        else:
            break
    return prefixes


# ════════════════════════════════════════════════════════════════════════════
#  Section 5: Infrastructure
# ════════════════════════════════════════════════════════════════════════════

_INSTANCE_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


# ── 5.1 僵尸任务清理 ──

async def recover_stale_jobs():
    """启动时清理僵尸任务（本实例重启 + 心跳超时）"""
    try:
        from app.models.operation_job import OperationJob
        stale_threshold = datetime.now() - timedelta(minutes=2)

        # 本实例遗留任务
        own_count = await OperationJob.filter(
            status__in=["running", "pending"],
            worker_name=_INSTANCE_ID,
        ).update(
            status="failed", error_message="服务重启，任务中断",
            finished_at=datetime.now(),
        )
        # 心跳超时的其他实例任务
        orphan_count = await OperationJob.filter(
            status__in=["running", "pending"],
        ).filter(
            Q(last_heartbeat__isnull=True) | Q(last_heartbeat__lt=stale_threshold)
        ).exclude(worker_name=_INSTANCE_ID).update(
            status="failed", error_message="心跳超时，Worker 可能已崩溃",
            finished_at=datetime.now(),
        )
        if own_count or orphan_count:
            logger.info(f"僵尸任务清理：本实例 {own_count} 个 + 心跳超时 {orphan_count} 个")
    except Exception as e:
        logger.warning(f"僵尸任务清理跳过: {e}")


# ── 5.2 分布式锁 ──

async def _ensure_lock_table():
    """确保分布式锁表存在"""
    from tortoise import connections
    conn = connections.get("default")
    await conn.execute_script("""
        CREATE TABLE IF NOT EXISTS system_init_lock (
            lock_key VARCHAR(64) PRIMARY KEY,
            instance_id VARCHAR(128) NOT NULL,
            acquired_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)


async def _try_acquire_init_lock(lock_key: str, timeout_seconds: int = 300) -> bool:
    """尝试获取分布式锁。过期锁自动清理。"""
    await _ensure_lock_table()
    from tortoise import connections
    conn = connections.get("default")
    now = datetime.now()
    expires = now + timedelta(seconds=timeout_seconds)

    # MySQL/PostgreSQL 用 %s 占位符，SQLite 用 ?
    placeholder = "?" if settings.DB_ENGINE == "sqlite" else "%s"

    # 清理过期锁
    await conn.execute_query(
        f"DELETE FROM system_init_lock WHERE lock_key = {placeholder} AND expires_at < {placeholder}",
        [lock_key, now.isoformat()]
    )
    try:
        await conn.execute_query(
            f"INSERT INTO system_init_lock (lock_key, instance_id, acquired_at, expires_at) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})",
            [lock_key, _INSTANCE_ID, now.isoformat(), expires.isoformat()]
        )
        logger.info(f"[InitLock] 获取锁成功: {lock_key}, instance={_INSTANCE_ID}")
        return True
    except Exception:
        logger.info(f"[InitLock] 锁被其他实例持有: {lock_key}，跳过")
        return False


async def _release_init_lock(lock_key: str):
    """释放本实例持有的分布式锁"""
    try:
        from tortoise import connections
        conn = connections.get("default")
        await conn.execute_query(
            "DELETE FROM system_init_lock WHERE lock_key = ? AND instance_id = ?",
            [lock_key, _INSTANCE_ID]
        )
    except Exception:
        pass


# ── 5.3 启动入口 ──

async def init_essential():
    """应用启动最小初始化：DB 迁移 + 清理僵尸任务 + 增量同步

    菜单/角色/Provider 同步受分布式锁保护，多 Worker 仅一个执行。
    """
    t0 = time.perf_counter()
    steps = []

    t = time.perf_counter()
    await init_db()
    steps.append(("DB 迁移", time.perf_counter() - t))

    t = time.perf_counter()
    await recover_stale_jobs()
    steps.append(("僵尸任务清理", time.perf_counter() - t))

    t = time.perf_counter()
    if await _try_acquire_init_lock("init_menus_roles", timeout_seconds=300):
        try:
            await init_menus()
            await init_roles()
        finally:
            await _release_init_lock("init_menus_roles")
    steps.append(("菜单/角色同步", time.perf_counter() - t))

    t = time.perf_counter()
    if await _try_acquire_init_lock("init_providers", timeout_seconds=300):
        try:
            await init_providers()
        finally:
            await _release_init_lock("init_providers")
    steps.append(("Provider 同步", time.perf_counter() - t))

    total = time.perf_counter() - t0
    detail = " | ".join(f"{name}: {elapsed:.2f}s" for name, elapsed in steps)
    logger.info(f"[Init] 启动初始化完成 ({total:.2f}s) - {detail}")


async def init_data():
    """完整数据初始化：init_essential + 种子数据（超级用户、全局配置、API）

    init_essential 已完成菜单/角色/Provider 增量同步，此处仅补充首次启动种子数据。
    """
    await init_essential()
    await init_superuser()
    await init_configs()
    await init_apis()


def init_default_data():
    """同步包装器，供 Docker entrypoint / 脚本调用"""
    import asyncio
    asyncio.run(init_data())
