from datetime import datetime

from aerich import Command
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
            exclude_paths=[
                "/api/v1/base/access_token",
                "/api/v1/import",
                "/api/v1/site-pipeline/feed/download",  # FileResponse 流式下载，不能被审计中间件消费 body
                "/api/v1/user/avatar/upload",  # multipart 文件上传，避免 body 被提前消费
                "/static",  # 静态文件（头像等），避免二进制响应体写入审计日志 JSON 字段导致 500
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
    # 系统管理 (catalog)
    ("系统管理",       "/system",             "",           MenuType.CATALOG, 1,  "carbon:gui-management",                        0, "Layout", "/system/user"),
    ("用户管理",       "user",                "/system",    MenuType.MENU,    1,  "material-symbols:person-outline-rounded",       0, "/system/user", None),
    ("角色管理",       "role",                "/system",    MenuType.MENU,    2,  "carbon:user-role",                              0, "/system/role", None),
    ("菜单管理",       "menu",                "/system",    MenuType.MENU,    3,  "material-symbols:list-alt-outline",             0, "/system/menu", None),
    ("API管理",        "api",                 "/system",    MenuType.MENU,    4,  "ant-design:api-outlined",                       0, "/system/api", None),
    ("部门管理",       "dept",                "/system",    MenuType.MENU,    5,  "mingcute:department-line",                     0, "/system/dept", None),
    ("审计日志",       "auditlog",            "/system",    MenuType.MENU,    6,  "ph:clipboard-text-bold",                        0, "/system/auditlog", None),

    # 站点流水线 (catalog)
    ("站点流水线",     "/site-pipeline",      "",           MenuType.CATALOG, 10, "mdi:web",                                        0, "Layout", "/site-pipeline/site-list"),
    ("站点管理",       "site-list",           "/site-pipeline", MenuType.MENU, 1,  "mdi:server-network",                            0, "/site-pipeline/site-list", None),
    ("Hub任务列表",    "hub-jobs",            "/site-pipeline", MenuType.MENU, 2,  "mdi:clipboard-list-outline",                    0, "/site-pipeline/hub-jobs", None),
    ("Feed管理",       "feed-manager",        "/site-pipeline", MenuType.MENU, 5,  "mdi:file-replace-outline",                      0, "/site-pipeline/feed-manager", None),

    # Gmail管理
    ("Gmail管理",      "/gmail",              "",           MenuType.CATALOG, 20, "mdi:gmail",                                       0, "Layout", "/gmail/account-list"),
    ("Gmail账号",      "account-list",        "/gmail",     MenuType.MENU,    1,  "mdi:account-box-mail",                           0, "/gmail/account-list", None),

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
    """自动同步菜单：每次启动根据 MENU_DEFINITIONS 声明式创建/更新"""
    # 先清理可能存在的重复数据
    await _deduplicate_menus()

    parent_cache = {}  # parent_path -> Menu.id

    for (name, path, parent_path, menu_type, order,
         icon, is_hidden, component, redirect) in MENU_DEFINITIONS:
        # 确定 parent_id
        if parent_path in (None, "", "/"):
            parent_id = 0
        else:
            if parent_path not in parent_cache:
                p = await Menu.filter(path=parent_path, parent_id=0).first()
                if p:
                    parent_cache[parent_path] = p.id
                else:
                    logger.warning(f"[init_menus] 父菜单未找到: {parent_path}，跳过 {name}")
                    continue
            parent_id = parent_cache[parent_path]

        # 使用 filter().first() 替代 get_or_create，避免 MultipleObjectsReturned
        existing = await Menu.filter(path=path, parent_id=parent_id).first()
        if existing:
            if parent_id == 0:
                parent_cache[path] = existing.id
            continue

        menu = await Menu.create(
            name=name,
            path=path,
            parent_id=parent_id,
            menu_type=menu_type,
            icon=icon,
            order=order,
            is_hidden=bool(is_hidden),
            component=component,
            keepalive=False,
            redirect=redirect,
        )
        logger.info(f"[init_menus] 新增菜单: {name} ({path}, parent={parent_id})")

        if parent_id == 0:
            parent_cache[path] = menu.id


async def init_configs():
    """初始化默认配置项（仅 name 不存在时才插入）"""
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
    for name, value, desc, cat, order, is_secret in defaults:
        if not await Config.filter(name=name).exists():
            await Config.create(
                name=name, value=value, description=desc, category=cat,
                sort_order=order, is_secret=is_secret
            )


async def init_providers():
    """初始化默认 Provider + 配置项（按规范：config_key / config_type / is_secret / is_required / default_value）

    每个配置项括号中注明使用位置（相对项目根目录的 文件:行号 与功能说明）。
    """
    # 每个 item: (provider_type, provider_name, description, priority, [(config_key, default_value, description, config_type, is_secret, is_required)])
    defaults = [
        # ── Cloudflare ──
        ("cloudflare", "Cloudflare 主账号", "默认 Cloudflare API 配置", 100, [
            ("api_token",     "", "Cloudflare API Token（services/cloudflare_service.py:19 / cloudflare_redirect_service.py:24 / api/v1/site_pipeline.py:741 构建请求头）", "token", True, True),
            ("account_id",    "", "Cloudflare Account ID（services/cloudflare_service.py:22 / api/v1/site_pipeline.py:742）", "string", False, True),
            ("proxied",       "true", "是否橙云代理（services/cloudflare_service.py:23 DNS记录proxied字段）", "bool", False, True),
            ("ttl",           "1", "DNS TTL 值 1=Auto（services/cloudflare_service.py:24）", "int", False, True),
            ("timeout",       "30", "API 请求超时秒数（services/cloudflare_service.py:25 / cloudflare_redirect_service.py:27）", "int", False, False),
        ]),
        # ── Dynadot ──
        ("dynadot", "Dynadot 主账号", "默认 Dynadot API 配置", 100, [
            ("api_key",  "", "Dynadot API Key（services/providers/dynadot_service.py:26）", "token", True, True),
            ("api_url",  "https://api.dynadot.com/api3.json", "Dynadot API 地址（services/providers/dynadot_service.py:27）", "url", False, True),
            ("timeout",  "30", "API 超时秒数（services/providers/dynadot_service.py:28）", "int", False, False),
        ]),
        # ── 1Panel ──
        ("onepanel", "生产1Panel节点A", "默认 1Panel 面板配置", 100, [
            ("url",                      "", "1Panel 面板地址（services/onepanel_service.py:158 OnePanelAPI.__init__）", "url", False, True),
            ("api_key",                  "", "1Panel API Key（services/onepanel_service.py:165）", "token", True, True),
            ("website_group_id",         "1", "默认网站分组 ID（services/onepanel_service.py:334 OnePanelSiteManager.__init__）", "int", False, True),
            ("panel_base",               "/opt/1panel", "1Panel 根目录（services/onepanel_service.py:229/346/677/774 多处引用）", "path", False, True),
            ("wp_app_root",              "/opt/1panel/apps/wordpress", "WordPress 应用根目录（services/onepanel_service.py:347/773）", "path", False, True),
            ("wp_app_key",               "wordpress", "WordPress 应用 key（services/onepanel_service.py:338/772）", "string", False, True),
            ("wp_app_type",              "docker", "WordPress 应用类型（services/onepanel_service.py:339）", "string", False, True),
            ("wp_app_id",                "", "WordPress 应用商店 appId（services/onepanel_service.py:340）", "int", False, False),
            ("wp_app_detail_id",         "", "WordPress 应用商店 appDetailId（services/onepanel_service.py:341）", "int", False, False),
            ("wp_version",               "7.0.0", "WordPress 版本号（services/onepanel_service.py:342）", "string", False, True),
            ("wp_admin_user",            "admin", "WordPress 默认管理员用户名（services/onepanel_service.py:344/549）", "string", False, False),
            ("wp_admin_email_prefix",    "admin", "WordPress 管理员邮箱前缀（services/onepanel_service.py:345/551 admin@{domain}）", "string", False, False),
            ("backup_account_id",        "", "模板站备份账号 ID（services/onepanel_service.py:675 OnePanelDBRestorer）", "int", False, True),
            ("template_backup_path",     "", "模板站应用备份路径（services/onepanel_service.py:771 OnePanelWordPressRestorer）", "path", False, True),
            ("db_backup_path",           "", "模板站数据库备份路径（services/onepanel_service.py:674 OnePanelDBRestorer）", "path", False, True),
            ("old_source_domain",        "", "建站后替换的目标旧域名（services/onepanel_service.py:782 / api/v1/site_pipeline.py:624）", "string", False, False),
            ("restore_mode",             "safe", "模板站恢复模式 safe/overwrite（services/onepanel_service.py:775）", "string", False, False),
            ("max_retries",              "3", "API 最大重试次数（services/onepanel_service.py:166 OnePanelAPI）", "int", False, False),
            ("retry_interval",           "2", "API 重试间隔秒数（services/onepanel_service.py:167）", "int", False, False),
            ("timeout",                  "30", "API 请求超时秒数（services/onepanel_service.py:168）", "int", False, False),
            ("auto_clean_conflict_site", "false", "遇到已存在站点是否自动清理（services/onepanel_service.py:335）", "bool", False, False),
            ("delete_sleep",             "5", "删除站点后等待秒数（services/onepanel_service.py:337）", "int", False, False),
            ("enable_ssl",               "true", "是否申请 SSL 证书（services/onepanel_service.py:586 OnePanelSSLManager）", "bool", False, False),
            ("force_https",              "true", "是否强制 HTTPS 跳转（services/onepanel_service.py:587）", "bool", False, False),
            ("ssl_ready_timeout",        "180", "SSL 证书就绪等待超时秒数（services/onepanel_service.py:588）", "int", False, False),
        ]),
        # ── HubStudio ──
        ("hubstudio", "本地HubStudio节点A", "默认 HubStudio 配置", 100, [
            ("base_url",                  "http://127.0.0.1:6873", "HubStudio API 地址（services/hubstudio_service.py 环境变量映射）", "url", False, True),
            ("app_id",                    "", "HubStudio App ID（services/hubstudio_service.py env）", "string", True, True),
            ("app_secret",                "", "HubStudio App Secret（services/hubstudio_service.py env）", "token", True, True),
            ("group_code",                "", "HubStudio 分组代码（services/hubstudio_service.py env）", "string", False, True),
            ("timeout",                   "60", "API 超时秒数（services/hubstudio_service.py env）", "int", False, False),
            ("connector_dir",             "", "HubStudio Connector 安装目录（services/hubstudio_service.py env）", "path", False, True),
            ("exe_name",                  "hubstudio_connector.exe", "Connector EXE 名称（services/hubstudio_service.py env）", "string", False, True),
            ("http_port",                 "6873", "Connector 监听端口（services/hubstudio_service.py env）", "int", False, True),
            ("real_kernel_version",       "137", "浏览器内核版本（services/hubstudio_service.py env）", "int", False, False),
            ("default_proxy_type_name",   "不使用代理", "默认代理类型（services/hubstudio_executor.py:673 执行器初始化）", "string", False, False),
            ("default_ui_language",       "en", "默认 UI 语言（services/hubstudio_service.py env）", "string", False, False),
            ("admin_site_name",           "自定义平台", "WordPress 后台站点名称（services/hubstudio_service.py env）", "string", False, False),
            ("admin_site_alias",          "WordPress后台", "WordPress 后台别名（services/hubstudio_service.py env）", "string", False, False),
            ("admin_account_name",        "admin", "默认后台管理员账号（services/hubstudio_service.py env）", "string", False, False),
            ("admin_account_password",    "", "默认后台管理员密码（services/hubstudio_service.py env）", "password", True, False),
            # ── 代理配置（services/hubstudio_executor.py:656-701 build_fixed_proxy_config / update_env 时生效）──
            ("use_fixed_proxy",           "true", "是否启用固定代理（services/hubstudio_executor.py:265/699）", "bool", False, False),
            ("proxy_type_name",           "HTTP", "代理类型 HTTP/SOCKS5/不使用代理（services/hubstudio_executor.py:568/682）", "string", False, False),
            ("as_dynamic_type",           "1", "动态代理类型 1=动态（services/hubstudio_executor.py:569/690）", "int", False, False),
            ("proxy_host",                "server.iphtml.biz", "代理主机地址（services/hubstudio_executor.py:571/683）", "string", False, False),
            ("proxy_port",                "15000", "代理端口（services/hubstudio_executor.py:572/684）", "int", False, False),
            ("proxy_account",             "uid-27498-zone-hubstudio", "代理账号（services/hubstudio_executor.py:574/685）", "string", False, False),
            ("proxy_password",            "", "代理密码（services/hubstudio_executor.py:575/686）", "password", True, False),
            ("proxy_country_code",        "US", "代理国家码（services/hubstudio_executor.py:577/687）", "string", False, False),
            ("proxy_city",                "New York", "代理城市（services/hubstudio_executor.py:580/688）", "string", False, False),
            ("proxy_province",            "CA", "代理省份（services/hubstudio_executor.py:579/689）", "string", False, False),
            ("ip_get_rule_type",          "1", "IP 获取规则类型（services/hubstudio_executor.py:581/691）", "int", False, False),
        ]),
        # ── Shopify ──
        ("shopify", "Shopify采集默认配置", "默认 Shopify 采集配置", 100, [
            ("request_timeout", "30", "API 请求超时秒数（services/shopify_collect_service.py:33）", "int", False, False),
        ]),
        # ── WooCommerce ──
        ("woo", "WooCommerce 默认", "默认 WooCommerce 产品导入配置", 100, [
            ("request_timeout",            "120", "API 请求超时秒数（services/woo_import_service.py:48 sync_get_config_map）", "int", False, False),
            ("retry_limit",                "2", "API 失败重试次数（services/woo_import_service.py:50）", "int", False, False),
            ("min_interval_seconds",       "2.5", "请求最小间隔秒数（services/woo_import_service.py:51）", "float", False, False),
            ("error_cooldown_seconds",     "30", "错误冷却秒数（services/woo_import_service.py:52）", "int", False, False),
            ("max_error_cooldown_seconds", "120", "最大错误冷却秒数（services/woo_import_service.py:53）", "int", False, False),
            ("import_product_count",       "10", "每次导入产品数量（services/woo_import_service.py:389 get_config）", "int", False, False),
            ("enable_images",              "true", "是否上传产品图片到 Woo（services/woo_import_service.py:430）", "bool", False, False),
            ("max_images_per_product",     "5", "每个产品最大图片数（services/woo_import_service.py:431）", "int", False, False),
            ("upload_variants",            "false", "是否上传变体产品 variable（services/woo_import_service.py:432）", "bool", False, False),
            ("check_existing_before_create","true", "创建前按 SKU 查重（services/woo_import_service.py:433）", "bool", False, False),
        ]),
        # ── Pipeline ──（建站流水线全局参数）
        ("pipeline", "默认流水线配置", "默认流水线全局参数", 100, [
            ("wp_container_memory_limit", "384", "WordPress 容器内存限制 MB（services/onepanel_service.py:557）", "int", False, False),
            ("wp_container_memory_unit",  "MB", "WordPress 容器内存单位（services/onepanel_service.py:558）", "string", False, False),
            ("op_verify_ssl", "true", "1Panel API TLS 证书验证（自签名设为 false）", "bool", False, False),
            ("wp_verify_ssl", "true", "WordPress 站点 TLS 证书验证（内网/自签名设为 false）", "bool", False, False),
            ("max_concurrent", "3", "最大同时建站数", "int", False, False),
        ]),
    ]

    for ptype, name, desc, priority, items in defaults:
        provider = await ConfigProvider.filter(provider_type=ptype, provider_name=name).first()
        if not provider:
            provider = await ConfigProvider.create(
                provider_type=ptype, provider_name=name,
                description=desc, is_default=True, priority=priority,
                status="active",
            )
        for i, (key, value, item_desc, config_type, is_secret, is_required) in enumerate(items):
            if not await ProviderConfigItem.filter(provider_id=provider.id, config_key=key).exists():
                await ProviderConfigItem.create(
                    provider_id=provider.id, config_key=key,
                    config_value=value, config_type=config_type,
                    is_secret=is_secret, is_required=is_required,
                    description=item_desc, sort=i,
                )

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
    apis = await api_controller.model.exists()
    if not apis:
        await api_controller.refresh_api()


async def init_db():
    """初始化数据库表结构并执行迁移。

    流程：init_db(safe=True) → aerich init → migrate → upgrade。
    任何步骤失败都会直接抛出异常，不再自动删除 migrations/ 目录。
    生产环境中迁移失败应人工介入排查，而非静默重置。
    """
    command = Command(tortoise_config=settings.TORTOISE_ORM)

    # 1. 安全建表（仅创建不存在的表，不删除已有数据）
    try:
        await command.init_db(safe=True)
    except FileExistsError:
        pass

    # 2. 初始化 aerich 配置（如已初始化则跳过）
    await command.init()

    # 3. 生成迁移
    await command.migrate()

    # 4. 执行迁移
    await command.upgrade(run_in_transaction=True)


async def init_roles():
    roles = await Role.exists()
    if not roles:
        admin_role = await Role.create(
            name="管理员",
            desc="管理员角色",
        )
        user_role = await Role.create(
            name="普通用户",
            desc="普通用户角色",
        )

        # 分配所有API给管理员角色
        all_apis = await Api.all()
        await admin_role.apis.add(*all_apis)
        # 分配所有菜单给管理员和普通用户
        all_menus = await Menu.all()
        await admin_role.menus.add(*all_menus)
        await user_role.menus.add(*all_menus)

        # 为普通用户分配基本API
        basic_apis = await Api.filter(Q(method__in=["GET"]) | Q(tags="基础模块"))
        await user_role.apis.add(*basic_apis)


async def recover_stale_jobs():
    """启动时清理僵尸任务：将未完成的 running/pending 标记为失败"""
    try:
        from app.models.operation_job import OperationJob
        count = await OperationJob.filter(status__in=["running", "pending"]).update(
            status="failed",
            error_message="服务重启，任务中断",
            finished_at=datetime.now(),
        )
        if count:
            logger.info(f"启动清理：已将 {count} 个未完成任务标记为失败")
    except Exception as e:
        logger.warning(f"僵尸任务清理跳过（可能尚未建表）: {e}")


async def init_essential():
    """应用启动最小初始化：仅 DB 迁移 + 僵尸任务清理。
    
    完整的数据初始化（超级用户、菜单、配置、Provider、角色）请使用:
        python scripts/init_system.py
    """
    await init_db()
    await recover_stale_jobs()


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
