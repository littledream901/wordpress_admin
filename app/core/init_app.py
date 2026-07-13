from datetime import datetime, timedelta
import os
import time
import uuid

from fastapi import FastAPI
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from tortoise.expressions import Q

from app.api import api_router
from app.controllers.api import api_controller
from app.controllers.user import UserCreate, user_controller
from app.models.config import Config
from app.models.config_provider import ConfigProvider, ProviderConfigItem
from app.core.exceptions import (
    DoesNotExist,
    DoesNotExistHandle,
    HTTPException,
    HttpExcHandle,
    IntegrityError,
    IntegrityHandle,
    RequestValidationError,
    RequestValidationHandle,
    ResponseValidationError,
    ResponseValidationHandle,
    ExternalAPIError,
    ServiceErrorHandle,
    ResourceBusyError,
    ResourceBusyHandle,
    ProviderConfigError,
    ProviderConfigErrorHandle,
)
from app.log import logger
from app.models.admin import Api, Menu, Role
from app.schemas.menus import MenuType
from app.settings.config import settings

from .middlewares import (
    AccessLogMiddleware,
    BackGroundTaskMiddleware,
    HttpAuditLogMiddleware,
    TraceIDMiddleware,
)
from .rate_limit import RateLimitMiddleware


def make_middlewares():
    middleware = [
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
                "/api/v1/site-pipeline/feed/download",  # FileResponse 流式下载
                "/api/v1/user/avatar/upload",  # multipart 文件上传
                "/static",  # 静态文件
                "/docs",
                "/openapi.json",
            ],
        ),
    ]
    return middleware


def register_exceptions(app: FastAPI):
    app.add_exception_handler(DoesNotExist, DoesNotExistHandle)
    app.add_exception_handler(HTTPException, HttpExcHandle)
    app.add_exception_handler(IntegrityError, IntegrityHandle)
    app.add_exception_handler(RequestValidationError, RequestValidationHandle)
    app.add_exception_handler(ResponseValidationError, ResponseValidationHandle)
    app.add_exception_handler(ExternalAPIError, ServiceErrorHandle)
    app.add_exception_handler(ResourceBusyError, ResourceBusyHandle)
    app.add_exception_handler(ProviderConfigError, ProviderConfigErrorHandle)


def register_routers(app: FastAPI, prefix: str = "/api"):
    app.include_router(api_router, prefix=prefix)


async def init_superuser():
    user = await user_controller.model.exists()
    if not user:
        await user_controller.create_user(
            UserCreate(
                username="admin",
                email="admin@admin.com",
                password=settings.DEFAULT_PASSWORD,
                is_active=True,
                is_superuser=True,
            )
        )


# ── 菜单声明式定义 ──
# 格式: (name, path, parent_path, menu_type, order, icon, is_hidden, component, redirect)
# parent_path 为空字符串或 "/" 表示根级菜单
MENU_DEFINITIONS = [
    # 站点流水线 (catalog)
    ("站点流水线",     "/site-pipeline",      "",           MenuType.CATALOG, 10, "mdi:web",                                        0, "Layout", "/site-pipeline/site-list"),
    ("站点管理",       "site-list",           "/site-pipeline", MenuType.MENU, 1,  "mdi:server-network",                            0, "/site-pipeline/site-list", None),
    ("Hub分发",        "hub-dispatch",        "/site-pipeline", MenuType.MENU, 2,  "mdi:cloud-upload-outline",                      0, "/site-pipeline/hub-dispatch", None),
    ("Hub任务列表",    "hub-jobs",            "/site-pipeline", MenuType.MENU, 3,  "mdi:clipboard-list-outline",                    0, "/site-pipeline/hub-jobs", None),
    ("Feed管理",       "feed-manager",        "/site-pipeline", MenuType.MENU, 5,  "mdi:file-replace-outline",                      0, "/site-pipeline/feed-manager", None),

    # Gmail管理
    ("Gmail管理",      "/gmail",              "",           MenuType.CATALOG, 20, "mdi:gmail",                                       0, "Layout", "/gmail/account-list"),
    ("Gmail账号",      "account-list",        "/gmail",     MenuType.MENU,    1,  "basil:gmail-solid",                           0, "/gmail/account-list", None),

    # Shopify采集
    ("Shopify采集",    "/shopify",            "",           MenuType.CATALOG, 30, "mdi:shopping-search",                             0, "Layout", "/shopify/source-list"),
    ("待采集列表",     "source-list",         "/shopify",   MenuType.MENU,    1,  "mdi:link-variant",                               0, "/shopify/source-list", None),
    ("产品列表",       "product-list",        "/shopify",   MenuType.MENU,    2,  "mdi:package-variant-closed",                     0, "/shopify/product-list", None),

    # 配置管理
    ("配置管理",       "/config",             "",           MenuType.CATALOG, 40, "carbon:settings",                                 0, "Layout", "/config/manage"),
    ("配置中心",       "manage",              "/config",    MenuType.MENU,    1,  "carbon:settings-adjust",                         0, "/config/manage", None),
    ("资源绑定",       "bindings",            "/config",    MenuType.MENU,    2,  "carbon:ibm-cloud-pak-manta-automated-data-lineage", 0, "/config/bindings", None),
    ("账号管理",       "accounts",            "/config",    MenuType.MENU,    3,  "carbon:user-identification",                     0, "/config/accounts", None),

    # 任务中心
    ("任务中心",       "/operation-jobs",     "",           MenuType.CATALOG, 50, "carbon:task",                                     0, "Layout", "/operation-jobs/job-list"),
    ("任务列表",       "job-list",            "/operation-jobs", MenuType.MENU, 1, "carbon:task-view",                              0, "/operation-jobs/job-list", None),
    ("导入记录",       "import-logs",         "/operation-jobs", MenuType.MENU, 2, "carbon:document-import",                        0, "/operation-jobs/import-logs", None),

    # 系统管理 (catalog)
    ("系统管理",       "/system",             "",           MenuType.CATALOG, 98,  "carbon:gui-management",                        0, "Layout", "/system/user"),
    ("用户管理",       "user",                "/system",    MenuType.MENU,    1,  "material-symbols:person-outline-rounded",       0, "/system/user", None),
    ("角色管理",       "role",                "/system",    MenuType.MENU,    2,  "carbon:user-role",                              0, "/system/role", None),
    ("菜单管理",       "menu",                "/system",    MenuType.MENU,    3,  "material-symbols:list-alt-outline",             0, "/system/menu", None),
    ("API管理",        "api",                 "/system",    MenuType.MENU,    4,  "ant-design:api-outlined",                       0, "/system/api", None),
    ("部门管理",       "dept",                "/system",    MenuType.MENU,    5,  "mingcute:department-line",                     0, "/system/dept", None),
    ("审计日志",       "auditlog",            "/system",    MenuType.MENU,    6,  "ph:clipboard-text-bold",                        0, "/system/auditlog", None),

    # 错误页面（由数据库驱动，不再硬编码于前端 basicRoutes）
    ("错误页面",       "/error-page",         "",           MenuType.CATALOG, 99, "mdi:alert-circle-outline",                        0, "Layout", "/error-page/404"),
    ("401错误",        "401",                 "/error-page", MenuType.MENU,    1,  "material-symbols:authenticator",                  1, "/error-page/401", None),
    ("403错误",        "403",                 "/error-page", MenuType.MENU,    2,  "solar:forbidden-circle-line-duotone",              1, "/error-page/403", None),
    ("404错误",        "404",                 "/error-page", MenuType.MENU,    3,  "tabler:error-404",                                 1, "/error-page/404", None),
    ("500错误",        "500",                 "/error-page", MenuType.MENU,    4,  "clarity:rack-server-outline-alerted",              1, "/error-page/500", None),


]


async def _deduplicate_menus():
    """清理数据库中 (path, parent_id) 重复的菜单，保留最早创建的那条"""
    from collections import defaultdict

    all_menus = await Menu.all().order_by("id")
    # 按 (path, parent_id) 分组
    groups = defaultdict(list)
    for m in all_menus:
        groups[(m.path, m.parent_id)].append(m)

    for (path, parent_id), dup_list in groups.items():
        if len(dup_list) <= 1:
            continue
        # 按 ID 升序，保留最早的那条
        keeper = dup_list[0]
        removed_ids = [m.id for m in dup_list[1:]]
        # 将子菜单的 parent_id 指向保留的菜单
        await Menu.filter(parent_id__in=removed_ids).update(parent_id=keeper.id)
        # 清理角色关联后删除
        from app.models.admin import Role
        roles = await Role.filter(menus__id__in=removed_ids).all()
        for role in roles:
            await role.menus.remove(*removed_ids)
        await Menu.filter(id__in=removed_ids).delete()
        logger.warning(
            f"[init_menus] 清理重复菜单 path={path} parent_id={parent_id}: "
            f"保留 id={keeper.id}, 删除 {removed_ids}"
        )


async def init_menus():
    """自动同步菜单：每次启动根据 MENU_DEFINITIONS 声明式创建/更新，清理废弃菜单"""

    # 先清理可能存在的重复数据
    await _deduplicate_menus()

    # 预加载所有菜单到内存，避免逐个查询
    all_menus = await Menu.all()
    menu_lookup = {}  # (path, parent_id) -> Menu
    path_to_id = {}   # path -> id (最新一层，用于父级查找)
    discarded_ids = set()  # 待隐藏的废弃菜单 id

    # 构建声明式路径集合
    declared_paths = {d[1] for d in MENU_DEFINITIONS}
    declared_lookup = {d[1]: d for d in MENU_DEFINITIONS}

    for m in all_menus:
        key = (m.path, m.parent_id)
        menu_lookup[key] = m
        if key not in menu_lookup or m.id != menu_lookup[key].id:
            menu_lookup[key] = m
        # 标记非声明式菜单为废弃
        if m.path not in declared_paths and not m.is_hidden:
            discarded_ids.add(m.id)

    # 按 parent_path 分层处理
    root_items = [d for d in MENU_DEFINITIONS if d[2] in (None, "", "/")]
    child_items = [d for d in MENU_DEFINITIONS if d[2] not in (None, "", "/")]

    # 第 1 轮：创建/更新根级菜单
    for (name, path, parent_path, menu_type, order,
         icon, is_hidden, component, redirect) in root_items:
        key = (path, 0)
        existing = menu_lookup.get(key)
        if existing:
            path_to_id[path] = existing.id
            await _sync_menu_fields(existing, name, menu_type, icon, order,
                                    is_hidden, component, redirect)
        else:
            menu = await Menu.create(
                name=name, path=path, parent_id=0, menu_type=menu_type,
                icon=icon, order=order, is_hidden=bool(is_hidden),
                component=component, keepalive=False, redirect=redirect,
            )
            menu_lookup[(path, 0)] = menu
            path_to_id[path] = menu.id
            logger.info(f"[init_menus] 新增菜单: {name} ({path})")

    # 第 2 轮：创建/更新子级菜单（支持多级，循环直到全部处理）
    remaining = list(child_items)
    while remaining:
        processed = []
        for (name, path, parent_path, menu_type, order,
             icon, is_hidden, component, redirect) in remaining:
            if parent_path not in path_to_id:
                continue
            parent_id = path_to_id[parent_path]
            key = (path, parent_id)
            existing = menu_lookup.get(key)
            if existing:
                path_to_id[path] = existing.id
                await _sync_menu_fields(existing, name, menu_type, icon, order,
                                        is_hidden, component, redirect)
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
            for (name, path, parent_path, *_) in remaining:
                logger.warning(f"[init_menus] 父菜单未定义: {parent_path}，跳过 {name}")
            break

    # 第 3 轮：清理废弃菜单（DB 中存在但声明中不存在的标记为隐藏）
    for m in all_menus:
        if m.path not in declared_paths and not m.is_hidden:
            m.is_hidden = True
            await m.save(update_fields=["is_hidden"])
            logger.info(f"[init_menus] 废弃菜单已隐藏: {m.name} ({m.path})")


async def _sync_menu_fields(menu, name, menu_type, icon, order, is_hidden, component, redirect):
    """同步菜单字段：检测变更后更新（全字段）"""
    updated = False
    if menu.name != name:
        menu.name = name; updated = True
    if menu.menu_type != menu_type:
        menu.menu_type = menu_type; updated = True
    if menu.icon != icon:
        menu.icon = icon; updated = True
    if menu.order != order:
        menu.order = order; updated = True
    if menu.is_hidden != bool(is_hidden):
        menu.is_hidden = bool(is_hidden); updated = True
    if menu.component != component:
        menu.component = component; updated = True
    if menu.redirect != redirect:
        menu.redirect = redirect; updated = True
    if updated:
        await menu.save()


async def init_configs():
    """初始化默认配置项：批量查询 + 批量写入"""
    # (name, value, description, category, sort_order, is_secret)
    defaults = [
        # === Cloudflare ===
        ("CF_API_TOKEN", "", "Cloudflare API Token", "cloudflare", 1, True),
        ("CF_ACCOUNT_ID", "", "Cloudflare Account ID", "cloudflare", 2, False),
        ("CF_PROXIED", "false", "是否启用 Cloudflare 代理（true/false）", "cloudflare", 3, False),
        ("CF_TTL", "1", "DNS TTL 值（1=Auto）", "cloudflare", 5, False),
        ("CF_TIMEOUT", "30", "API 请求超时(秒)", "cloudflare", 6, False),
        # === Dynadot ===
        ("DYNADOT_API_KEY", "", "Dynadot API Key", "dynadot", 1, True),
        ("DYNADOT_API_URL", "https://api.dynadot.com/api3.xml", "Dynadot API 地址", "dynadot", 2, False),
        ("DYNADOT_TIMEOUT", "30", "Dynadot API 超时(秒)", "dynadot", 3, False),
        # === 1Panel ===
        ("OP_URL", "", "1Panel 面板地址 (如 http://1.2.3.4:12345)", "onepanel", 1, False),
        ("OP_API_KEY", "", "1Panel API Key", "onepanel", 2, True),
        ("OP_WEBSITE_GROUP_ID", "1", "默认网站分组 ID", "onepanel", 3, False),
        ("OP_WP_APP_ID", "", "WordPress 应用 ID（应用商店）", "onepanel", 4, False),
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
        # === HubStudio ===
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
        # === WooCommerce ===
        ("WOO_API_TIMEOUT", "30", "WooCommerce API 超时(秒)", "woo", 1, False),
        ("WOO_RATE_LIMIT_RPM", "30", "WooCommerce 每分钟请求限制", "woo", 2, False),
        ("WOO_RATE_LIMIT_RETRY", "3", "WooCommerce 限流重试次数", "woo", 3, False),
        # === Shopify ===
        ("SHOPIFY_API_TIMEOUT", "30", "Shopify 采集超时(秒)", "shopify", 1, False),
        ("SHOPIFY_MAX_PRODUCTS_PER_SOURCE", "250", "每个采集源最大商品数", "shopify", 2, False),
    ]
    # 批量查询现有配置，一次性写入缺失项
    existing_names = {c.name for c in await Config.all()}
    to_create = []
    for name, value, desc, cat, order, is_secret in defaults:
        if name not in existing_names:
            to_create.append(Config(
                name=name, value=value, description=desc, category=cat,
                sort_order=order, is_secret=is_secret,
            ))
    if to_create:
        await Config.bulk_create(to_create)
        logger.info(f"[init_configs] 批量新增 {len(to_create)} 个配置项")


async def init_providers():
    """初始化默认 Provider + 配置项（按规范：config_key / config_type / is_secret / is_required / default_value）"""

    # 每个 item: (provider_type, provider_name, description, priority, [(config_key, default_value, description, config_type, is_secret, is_required)])
    defaults = [
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
            # ── 代理配置──
            ("use_fixed_proxy",           "true", "是否启用固定代理", "bool", False, False),
            ("proxy_type_name",           "HTTP", "代理类型 HTTP/SOCKS5/不使用代理", "string", False, False),
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
            ("upload_variants",            "false", "是否上传变体产品 variable", "bool", False, False),
            ("check_existing_before_create","true", "创建前按 SKU 查重", "bool", False, False),
        ]),
        # ── Pipeline ──（建站流水线全局参数）
        ("pipeline", "默认流水线配置", "默认流水线全局参数", 100, [
            ("wp_container_memory_limit", "384", "WordPress 容器内存限制 MB", "int", False, False),
            ("wp_container_memory_unit",  "MB", "WordPress 容器内存单位", "string", False, False),
            ("op_verify_ssl", "true", "1Panel API TLS 证书验证（自签名设为 false）", "bool", False, False),
            ("wp_verify_ssl", "true", "WordPress 站点 TLS 证书验证（内网/自签名设为 false）", "bool", False, False),
            ("max_concurrent", "3", "最大同时建站数", "int", False, False),
        ]),
    ]

    # 批量查询现有 Provider
    existing_providers = {
        (p.provider_type, p.provider_name): p
        for p in await ConfigProvider.all()
    }
    providers_to_create = []

    # 第 1 轮：确保所有 Provider 存在
    for ptype, name, desc, priority, items in defaults:
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
        # bulk_create 不会填充 id，需要重新查询
        existing_providers = {
            (p.provider_type, p.provider_name): p
            for p in await ConfigProvider.all()
        }
        logger.info(f"[init_providers] 批量新增 {len(providers_to_create)} 个 Provider")

    # 第 2 轮：批量创建缺失的配置项
    all_existing_items = {
        (ci.provider_id, ci.config_key)
        for ci in await ProviderConfigItem.all()
    }
    items_to_create = []
    for ptype, name, desc, priority, items in defaults:
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

    # ── 清理已废弃的 Provider 配置项（从数据库中删除，前端不再展示）──
    cleanup = {
        "woo":        ["random_import", "rate_limit_rpm", "rate_limit_retry"],
        "shopify":    ["page_sleep", "default_max_products", "user_agent"],
        "hubstudio":  ["business_group_name"],
        "pipeline":   ["random_assign_default_count", "shopify_default_max_products",
                       "woo_import_sample_count", "woo_request_timeout",
                       "retry_limit", "timeout_limit"],
        "onepanel":   ["auto_detect_wp_app", "restore_root_files", "woo_script",
                       "ctx_script", "woo_fetch_retries", "woo_fetch_interval", "ctk_token"],
    }
    for ptype, keys in cleanup.items():
        provider = await ConfigProvider.filter(provider_type=ptype, is_default=True).first()
        if provider:
            deleted = await ProviderConfigItem.filter(provider_id=provider.id, config_key__in=keys).delete()
            if deleted:
                logger.info(f"已清理 {ptype} Provider 废弃配置: {keys}")


async def init_apis():
    """每次启动刷新 API 记录，同步 summary 等变更"""
    await api_controller.refresh_api()


async def init_db():
    """初始化数据库表结构。

    使用 Tortoise.generate_schemas(safe=True) 自动建新表，
    追加手动 SQL 处理 Tortoise 无法覆盖的变更（ALTER TABLE / 中间表等）。
    """
    from tortoise import Tortoise, connections

    # 0. 确保 Tortoise 已初始化（lifespan 中应用尚未处理请求，需主动 init）
    try:
        await Tortoise.init(config=settings.TORTOISE_ORM)
    except Exception:
        pass  # 已初始化则跳过

    # 1. 安全建表：仅创建不存在的表，不破坏已有数据
    await Tortoise.generate_schemas(safe=True)

    # 2. 手动补充迁移
    conn = connections.get("default")
    patches = [
        # Site 模型：数据权限字段
        "ALTER TABLE site_pipeline_site ADD COLUMN create_by INTEGER",
        "ALTER TABLE site_pipeline_site ADD COLUMN dept_id INTEGER",
        # Site 模型：WooCommerce 远端产品数量缓存
        "ALTER TABLE site_pipeline_site ADD COLUMN woo_product_count INTEGER DEFAULT 0",
        # RoleDataScope 表（Tortoise 有时无法通过 safe 模式创建含 FK + UNIQUE 的表）
        """CREATE TABLE IF NOT EXISTS role_data_scope (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_id INTEGER NOT NULL REFERENCES role(id),
            resource VARCHAR(64) NOT NULL,
            data_scope INTEGER NOT NULL DEFAULT 3,
            UNIQUE(role_id, resource)
        )""",
        # RoleDataScope ↔ Dept M2M 中间表
        """CREATE TABLE IF NOT EXISTS role_data_scope_custom_depts (
            roledatascope_id INTEGER NOT NULL REFERENCES role_data_scope(id),
            dept_id INTEGER NOT NULL REFERENCES dept(id)
        )""",
        # OperationJob：worker 归属 + 心跳
        "ALTER TABLE operation_job ADD COLUMN last_heartbeat TEXT",
    ]

    for sql in patches:
        try:
            await conn.execute_query(sql)
            logger.info(f"[init_db] {sql[:60].replace(chr(10), ' ')}...")
        except Exception as e:
            err = str(e).lower()
            if "duplicate column" in err or "already exists" in err:
                logger.debug(f"[init_db] 跳过（已存在）")
            else:
                logger.warning(f"[init_db] 失败: {e}")


async def init_roles():
    roles = await Role.exists()
    if not roles:
        admin_role = await Role.create(name="管理员", desc="管理员角色")
        user_role = await Role.create(name="普通用户", desc="普通用户角色")

        # 分配所有 API 给管理员
        all_apis = await Api.all()
        await admin_role.apis.add(*all_apis)

        # 分配所有菜单给管理员和普通用户
        all_menus = await Menu.all()
        await admin_role.menus.add(*all_menus)
        await user_role.menus.add(*all_menus)

        # 为普通用户自动关联菜单对应的 API
        await _sync_menu_apis_for_role(user_role, all_menus, all_apis)
    else:
        # 已存在角色时，同步新增菜单 + 对应 API
        all_menus = await Menu.all()
        all_menu_ids = {m.id for m in all_menus}
        all_apis = await Api.all()
        all_roles = await Role.all()
        for role in all_roles:
            role_menu_ids = {m.id for m in await role.menus.all()}
            missing_ids = all_menu_ids - role_menu_ids
            if missing_ids:
                missing_menus = [m for m in all_menus if m.id in missing_ids]
                await role.menus.add(*missing_menus)
                await _sync_menu_apis_for_role(role, missing_menus, all_apis)
                logger.info(f"[init_roles] 角色 {role.name} 新增菜单: {[m.name for m in missing_menus]}")


async def _sync_menu_apis_for_role(role, menus, all_apis=None):
    """将菜单对应的 API 自动授予角色（按路径前缀匹配）"""
    if all_apis is None:
        all_apis = await Api.all()

    # 提取每个菜单的路径前缀（如 /site-pipeline）
    menu_prefixes = set()
    for menu in menus:
        parts = menu.path.strip("/").split("/")
        menu_prefixes.add(parts[0])

    # 匹配 API：/api/v1/{prefix}/xxx 对应菜单 /{prefix}
    matched_apis = []
    for api in all_apis:
        api_parts = api.path.strip("/").split("/")
        # API 路径格式: /api/v1/{module}/...
        if len(api_parts) >= 3 and api_parts[0] == "api" and api_parts[1] == "v1":
            api_module = api_parts[2]
            if api_module in menu_prefixes:
                matched_apis.append(api)

    if matched_apis:
        existing_api_ids = {a.id for a in await role.apis.all()}
        new_apis = [a for a in matched_apis if a.id not in existing_api_ids]
        if new_apis:
            await role.apis.add(*new_apis)
            logger.info(f"[init_roles] 角色 {role.name} 新增 API: {len(new_apis)} 个 ({[a.path for a in new_apis[:3]]}...)")


async def recover_stale_jobs():
    """启动时清理僵尸任务：仅清理本实例或心跳超时的未完成任务（防误杀）"""
    try:
        from app.models.operation_job import OperationJob
        stale_threshold = datetime.now() - timedelta(minutes=2)

        # 1. 清理本实例的任务（worker 重启，任务必然中断）
        own_count = await OperationJob.filter(
            status__in=["running", "pending"],
            worker_name=_INSTANCE_ID,
        ).update(
            status="failed",
            error_message="服务重启，任务中断",
            finished_at=datetime.now(),
        )

        # 2. 清理心跳超时的僵尸任务（其他实例已失联）
        orphan_count = await OperationJob.filter(
            status__in=["running", "pending"],
        ).filter(
            Q(last_heartbeat__isnull=True) | Q(last_heartbeat__lt=stale_threshold)
        ).exclude(worker_name=_INSTANCE_ID).update(
            status="failed",
            error_message="心跳超时，Worker 可能已崩溃",
            finished_at=datetime.now(),
        )

        if own_count or orphan_count:
            logger.info(
                f"僵尸任务清理：本实例 {own_count} 个 + 心跳超时 {orphan_count} 个"
            )
    except Exception as e:
        logger.warning(f"僵尸任务清理跳过（可能尚未建表）: {e}")


# ── 分布式锁（防多 Worker 竞态） ──
_INSTANCE_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


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
    """尝试获取分布式锁，返回是否获取成功。过期锁自动清理。"""
    await _ensure_lock_table()
    from tortoise import connections
    conn = connections.get("default")
    now = datetime.now()
    expires = now + timedelta(seconds=timeout_seconds)

    # 清理过期锁
    await conn.execute_query(
        "DELETE FROM system_init_lock WHERE lock_key = ? AND expires_at < ?",
        [lock_key, now.isoformat()]
    )
    # 尝试插入
    try:
        await conn.execute_query(
            "INSERT INTO system_init_lock (lock_key, instance_id, acquired_at, expires_at) VALUES (?, ?, ?, ?)",
            [lock_key, _INSTANCE_ID, now.isoformat(), expires.isoformat()]
        )
        logger.info(f"[InitLock] 获取初始化锁成功: {lock_key}, instance={_INSTANCE_ID}")
        return True
    except Exception:
        logger.info(f"[InitLock] 初始化锁被其他实例持有: {lock_key}，跳过")
        return False


async def _release_init_lock(lock_key: str):
    """释放分布式锁（仅释放本实例持有的锁）"""
    try:
        from tortoise import connections
        conn = connections.get("default")
        await conn.execute_query(
            "DELETE FROM system_init_lock WHERE lock_key = ? AND instance_id = ?",
            [lock_key, _INSTANCE_ID]
        )
    except Exception:
        pass


async def init_essential():
    """应用启动最小初始化：DB 迁移 + 僵尸任务清理 + 菜单/角色增量同步。

    完整的数据初始化（超级用户、菜单、配置、Provider、角色）请使用:
        python scripts/init_system.py
    """
    t0 = time.perf_counter()
    steps = []

    t = time.perf_counter()
    await init_db()
    steps.append(("DB 迁移", time.perf_counter() - t))

    t = time.perf_counter()
    await recover_stale_jobs()
    steps.append(("僵尸任务清理", time.perf_counter() - t))

    # 增量同步菜单和角色分配（分布式锁保护，多 Worker 仅一个执行）
    t = time.perf_counter()
    if await _try_acquire_init_lock("init_menus_roles", timeout_seconds=300):
        try:
            await init_menus()
            await init_roles()
        finally:
            await _release_init_lock("init_menus_roles")
    steps.append(("菜单/角色同步", time.perf_counter() - t))

    total = time.perf_counter() - t0
    detail = " | ".join(f"{name}: {elapsed:.2f}s" for name, elapsed in steps)
    logger.info(f"[Init] 启动初始化完成 ({total:.2f}s) - {detail}")


async def init_data():
    """完整数据初始化（包含 init_essential + 种子数据）。
    
    注意：此函数会执行完整的系统初始化流程，
    生产环境建议使用 init_essential() 作为 lifespan，
    然后通过 scripts/init_system.py 单独执行数据初始化。
    """
    await init_essential()
    await init_superuser()
    await init_menus()
    await init_configs()
    await init_providers()
    await init_apis()
    await init_roles()


def init_default_data():
    """同步包装器，供 Docker entrypoint / 脚本调用"""
    import asyncio
    asyncio.run(init_data())
