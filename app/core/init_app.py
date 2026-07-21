"""
应用初始化模块
├── App Factory    : 中间件注册、异常处理注册、路由注册
├── Data Definitions : 菜单声明式定义
├── Schema Migration : 数据库建表
├── Seed Data        : 超级用户、菜单、配置、Provider、API、角色
└── Infrastructure   : 僵尸任务清理、分布式锁、启动入口
"""

import asyncio
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
from tortoise import Tortoise, connections
from tortoise.exceptions import DoesNotExist, IntegrityError
from tortoise.expressions import Q

from app.api import api_router
from app.controllers.api import api_controller
from app.log import logger
from app.models.admin import Api, Menu, Role
from app.models.config import Config
from app.models.config_provider import ConfigProvider, ProviderConfigItem
from app.schemas.menus import MenuType
from app.settings.config import settings
from app.utils.provider_defaults import _PROVIDER_DEFAULTS

from app.core.exceptions import (
    ExternalAPIError,
    ProviderConfigError,
    ResourceBusyError,
)
from tortoise.exceptions import MultipleObjectsReturned
from app.core.exception_handlers import (
    DoesNotExistHandle,
    HttpExcHandle,
    IntegrityHandle,
    MultipleObjectsReturnedHandle,
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


# ════════════════════════════════════════════════════════════════════════════
#  Section 1: App Factory
# ════════════════════════════════════════════════════════════════════════════

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
                "/api/v1/base/refresh_token",
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
    app.add_exception_handler(MultipleObjectsReturned, MultipleObjectsReturnedHandle)


def register_routers(app: FastAPI, prefix: str = "/api"):
    """注册 API 路由"""
    app.include_router(api_router, prefix=prefix)


# ════════════════════════════════════════════════════════════════════════════
#  Section 2: Data Definitions
# ════════════════════════════════════════════════════════════════════════════

# 菜单声明式定义
# 字段: name, path, parent_path, menu_type, order, icon, is_hidden, component, redirect
# parent_path 为空字符串表示根级菜单
MENU_DEFINITIONS = [
    # ── 站点流水线 ──
    {"name": "站点流水线",     "path": "/site-pipeline",      "parent_path": "",              "menu_type": MenuType.CATALOG, "order": 10, "icon": "mdi:web",                                   "is_hidden": False, "component": "Layout", "redirect": "/site-pipeline/site-list"},
    {"name": "站点管理",       "path": "site-list",           "parent_path": "/site-pipeline", "menu_type": MenuType.MENU,    "order": 1,  "icon": "mdi:server-network",                       "is_hidden": False, "component": "/site-pipeline/site-list", "redirect": None},
    {"name": "Hub分发",        "path": "hub-dispatch",        "parent_path": "/site-pipeline", "menu_type": MenuType.MENU,    "order": 2,  "icon": "mdi:cloud-upload-outline",                 "is_hidden": False, "component": "/site-pipeline/hub-dispatch", "redirect": None},
    {"name": "Hub任务列表",    "path": "hub-jobs",            "parent_path": "/site-pipeline", "menu_type": MenuType.MENU,    "order": 3,  "icon": "mdi:clipboard-list-outline",               "is_hidden": False, "component": "/site-pipeline/hub-jobs", "redirect": None},
    {"name": "Feed管理",       "path": "feed-manager",        "parent_path": "/site-pipeline", "menu_type": MenuType.MENU,    "order": 5,  "icon": "mdi:file-replace-outline",                 "is_hidden": False, "component": "/site-pipeline/feed-manager", "redirect": None},
    {"name": "ADS管理",        "path": "ads-manager",         "parent_path": "/site-pipeline", "menu_type": MenuType.MENU,    "order": 6,  "icon": "mdi:monitor-eye",                           "is_hidden": False, "component": "/site-pipeline/ads-manager", "redirect": None},
    # ── Gmail 管理 ──
    {"name": "Gmail管理",      "path": "/gmail",              "parent_path": "",              "menu_type": MenuType.CATALOG, "order": 20, "icon": "mdi:gmail",                                  "is_hidden": False, "component": "Layout", "redirect": "/gmail/account-list"},
    {"name": "Gmail账号",      "path": "account-list",        "parent_path": "/gmail",        "menu_type": MenuType.MENU,    "order": 1,  "icon": "basil:gmail-solid",                         "is_hidden": False, "component": "/gmail/account-list", "redirect": None},
    # ── Shopify 采集 ──
    {"name": "Shopify采集",    "path": "/shopify",            "parent_path": "",              "menu_type": MenuType.CATALOG, "order": 30, "icon": "mdi:shopping-search",                        "is_hidden": False, "component": "Layout", "redirect": "/shopify/source-list"},
    {"name": "待采集列表",     "path": "source-list",         "parent_path": "/shopify",      "menu_type": MenuType.MENU,    "order": 1,  "icon": "mdi:link-variant",                          "is_hidden": False, "component": "/shopify/source-list", "redirect": None},
    {"name": "产品列表",       "path": "product-list",        "parent_path": "/shopify",      "menu_type": MenuType.MENU,    "order": 2,  "icon": "mdi:package-variant-closed",                "is_hidden": False, "component": "/shopify/product-list", "redirect": None},
    # ── 配置管理 ──
    {"name": "配置管理",       "path": "/config",             "parent_path": "",              "menu_type": MenuType.CATALOG, "order": 40, "icon": "carbon:settings",                            "is_hidden": False, "component": "Layout", "redirect": "/config/manage"},
    {"name": "配置中心",       "path": "manage",              "parent_path": "/config",       "menu_type": MenuType.MENU,    "order": 1,  "icon": "carbon:settings-adjust",                    "is_hidden": False, "component": "/config/manage", "redirect": None},
    {"name": "资源绑定",       "path": "bindings",            "parent_path": "/config",       "menu_type": MenuType.MENU,    "order": 2,  "icon": "carbon:ibm-cloud-pak-manta-automated-data-lineage", "is_hidden": False, "component": "/config/bindings", "redirect": None},
    {"name": "账号管理",       "path": "accounts",            "parent_path": "/config",       "menu_type": MenuType.MENU,    "order": 3,  "icon": "carbon:user-identification",                "is_hidden": False, "component": "/config/accounts", "redirect": None},
    {"name": "回收站",         "path": "recycle",             "parent_path": "/config",       "menu_type": MenuType.MENU,    "order": 4,  "icon": "mdi:delete-restore",                         "is_hidden": False, "component": "/config/recycle", "redirect": None},
    # ── 任务中心 ──
    {"name": "任务中心",       "path": "/operation-jobs",     "parent_path": "",              "menu_type": MenuType.CATALOG, "order": 50, "icon": "carbon:task",                                "is_hidden": False, "component": "Layout", "redirect": "/operation-jobs/job-list"},
    {"name": "任务列表",       "path": "job-list",            "parent_path": "/operation-jobs", "menu_type": MenuType.MENU,  "order": 1,  "icon": "carbon:task-view",                          "is_hidden": False, "component": "/operation-jobs/job-list", "redirect": None},
    {"name": "导入记录",       "path": "import-logs",         "parent_path": "/operation-jobs", "menu_type": MenuType.MENU,  "order": 2,  "icon": "carbon:document-import",                    "is_hidden": False, "component": "/operation-jobs/import-logs", "redirect": None},
    # ── 系统管理 ──
    {"name": "系统管理",       "path": "/system",             "parent_path": "",              "menu_type": MenuType.CATALOG, "order": 98, "icon": "carbon:gui-management",                      "is_hidden": False, "component": "Layout", "redirect": "/system/user"},
    {"name": "用户管理",       "path": "user",                "parent_path": "/system",       "menu_type": MenuType.MENU,    "order": 1,  "icon": "material-symbols:person-outline-rounded",   "is_hidden": False, "component": "/system/user", "redirect": None},
    {"name": "角色管理",       "path": "role",                "parent_path": "/system",       "menu_type": MenuType.MENU,    "order": 2,  "icon": "carbon:user-role",                          "is_hidden": False, "component": "/system/role", "redirect": None},
    {"name": "菜单管理",       "path": "menu",                "parent_path": "/system",       "menu_type": MenuType.MENU,    "order": 3,  "icon": "material-symbols:list-alt-outline",         "is_hidden": False, "component": "/system/menu", "redirect": None},
    {"name": "API管理",        "path": "api",                 "parent_path": "/system",       "menu_type": MenuType.MENU,    "order": 4,  "icon": "ant-design:api-outlined",                   "is_hidden": False, "component": "/system/api", "redirect": None},
    {"name": "部门管理",       "path": "dept",                "parent_path": "/system",       "menu_type": MenuType.MENU,    "order": 5,  "icon": "mingcute:department-line",                 "is_hidden": False, "component": "/system/dept", "redirect": None},
    {"name": "审计日志",       "path": "auditlog",            "parent_path": "/system",       "menu_type": MenuType.MENU,    "order": 6,  "icon": "ph:clipboard-text-bold",                    "is_hidden": False, "component": "/system/auditlog", "redirect": None},
]


# ════════════════════════════════════════════════════════════════════════════
#  Section 3: Schema
# ════════════════════════════════════════════════════════════════════════════

async def init_db():
    """确保数据库 Schema 与 ORM 模型一致（幂等）。

    - 空库：调用 Tortoise.generate_schemas 一次性建表。
    - 存量库：通过 INFORMATION_SCHEMA 检测增量列/索引，补齐历史演进缺口。
      （Aerich 可覆盖的迁移优先用 Aerich，此处作为无 Aerich 环境的兜底。）
    """
    conn = connections.get("default")

    tables_ready = False
    try:
        result = await conn.execute_query("SHOW TABLES LIKE 'user'")
        if result[1]:
            tables_ready = True
    except Exception:
        pass

    if not tables_ready:
        await Tortoise.generate_schemas(safe=True)
        logger.info("[DB] 首次建表完成（含 M2M 中间表）")
        return

    logger.debug("[DB] 业务表已存在，跳过建表")

    # ── Schema 演进：历史模型新增的列（声明式，仅补齐缺失项）──
    _needed_columns: list[dict] = [
        {"table": "menu", "col": "parent_id", "sql": "ALTER TABLE `menu` ADD COLUMN `parent_id` INT NOT NULL DEFAULT 0 COMMENT '父菜单ID'"},
        {"table": "menu", "col": "remark",    "sql": "ALTER TABLE `menu` ADD COLUMN `remark` JSON NULL COMMENT '保留字段'"},
        {"table": "site_pipeline_gmail_account", "col": "assigned_site_id", "sql": "ALTER TABLE `site_pipeline_gmail_account` ADD COLUMN `assigned_site_id` INT NULL COMMENT '分配站点ID'"},
        {"table": "site_pipeline_gmail_account", "col": "assigned_site_domain", "sql": "ALTER TABLE `site_pipeline_gmail_account` ADD COLUMN `assigned_site_domain` VARCHAR(255) DEFAULT '' COMMENT '分配站点域名'"},
        {"table": "api", "col": "method",     "sql": "ALTER TABLE `api` ADD COLUMN `method` VARCHAR(10) NOT NULL DEFAULT 'GET' COMMENT '请求方法'"},
        {"table": "api", "col": "is_button",  "sql": "ALTER TABLE `api` ADD COLUMN `is_button` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否为按钮权限'"},
        {"table": "site_pipeline_hubstudio_job", "col": "payload_json",  "sql": "ALTER TABLE `site_pipeline_hubstudio_job` ADD COLUMN `payload_json` TEXT NULL COMMENT '任务负载'"},
        {"table": "site_pipeline_hubstudio_job", "col": "result_json",   "sql": "ALTER TABLE `site_pipeline_hubstudio_job` ADD COLUMN `result_json` TEXT NULL COMMENT '任务结果'"},
        {"table": "site_pipeline_hubstudio_job", "col": "error_message", "sql": "ALTER TABLE `site_pipeline_hubstudio_job` ADD COLUMN `error_message` TEXT NULL COMMENT '错误信息'"},
        {"table": "site_pipeline_hubstudio_job", "col": "worker_name",   "sql": "ALTER TABLE `site_pipeline_hubstudio_job` ADD COLUMN `worker_name` VARCHAR(128) DEFAULT '' COMMENT '执行节点名称'"},
        {"table": "site_pipeline_hubstudio_job", "col": "retry_count",   "sql": "ALTER TABLE `site_pipeline_hubstudio_job` ADD COLUMN `retry_count` INT NOT NULL DEFAULT 0 COMMENT '重试次数'"},
        {"table": "site_pipeline_hubstudio_job", "col": "started_at",    "sql": "ALTER TABLE `site_pipeline_hubstudio_job` ADD COLUMN `started_at` DATETIME NULL COMMENT '开始执行时间'"},
        {"table": "site_pipeline_hubstudio_job", "col": "finished_at",   "sql": "ALTER TABLE `site_pipeline_hubstudio_job` ADD COLUMN `finished_at` DATETIME NULL COMMENT '完成时间'"},
        {"table": "role", "col": "code", "sql": "ALTER TABLE `role` ADD COLUMN `code` VARCHAR(64) NULL COMMENT '角色编码（admin/user/hub_agent，用于逻辑判断）'"},
    ]

    # ── Schema 演进：历史模型新增的索引 ──
    _needed_indexes: list[dict] = [
        {"table": "menu", "idx": "idx_menu_parent_id", "sql": "ALTER TABLE `menu` ADD INDEX `idx_menu_parent_id` (`parent_id`)"},
        {"table": "site_pipeline_site", "idx": "idx_is_deleted", "sql": "ALTER TABLE `site_pipeline_site` ADD INDEX `idx_is_deleted` (`is_deleted`)"},
        {"table": "account", "idx": "idx_is_deleted", "sql": "ALTER TABLE `account` ADD INDEX `idx_is_deleted` (`is_deleted`)"},
        {"table": "ads_env", "idx": "idx_is_deleted", "sql": "ALTER TABLE `ads_env` ADD INDEX `idx_is_deleted` (`is_deleted`)"},
        {"table": "site_pipeline_gmail_account", "idx": "idx_is_deleted", "sql": "ALTER TABLE `site_pipeline_gmail_account` ADD INDEX `idx_is_deleted` (`is_deleted`)"},
        {"table": "site_pipeline_gmail_account", "idx": "idx_assigned_site_id", "sql": "ALTER TABLE `site_pipeline_gmail_account` ADD INDEX `idx_assigned_site_id` (`assigned_site_id`)"},
        {"table": "config_provider", "idx": "idx_is_deleted", "sql": "ALTER TABLE `config_provider` ADD INDEX `idx_is_deleted` (`is_deleted`)"},
        {"table": "api", "idx": "idx_api_method", "sql": "ALTER TABLE `api` ADD INDEX `idx_api_method` (`method`)"},
    ]

    # ── 检测 Schema 差异：已存在的列 ──
    existing_cols: set[tuple] = set()
    col_pairs = ", ".join(f"('{c['table']}', '{c['col']}')" for c in _needed_columns)
    try:
        rows = await conn.execute_query(
            f"SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = DATABASE() AND (TABLE_NAME, COLUMN_NAME) IN ({col_pairs})"
        )
        for row in rows[1]:
            existing_cols.add((row["TABLE_NAME"], row["COLUMN_NAME"]))
    except Exception as e:
        logger.warning(f"[DB] 查询已存在列失败: {e}")

    # ── 检测 Schema 差异：已存在的索引 ──
    existing_idxs: set[tuple] = set()
    idx_pairs = ", ".join(f"('{c['table']}', '{c['idx']}')" for c in _needed_indexes)
    try:
        rows = await conn.execute_query(
            f"SELECT TABLE_NAME, INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS "
            f"WHERE TABLE_SCHEMA = DATABASE() AND (TABLE_NAME, INDEX_NAME) IN ({idx_pairs})"
        )
        for row in rows[1]:
            existing_idxs.add((row["TABLE_NAME"], row["INDEX_NAME"]))
    except Exception as e:
        logger.warning(f"[DB] 查询已存在索引失败: {e}")

    # ── 执行 Schema 演进：仅补齐缺失的列 ──
    for c in _needed_columns:
        if (c["table"], c["col"]) not in existing_cols:
            try:
                await conn.execute_query(c["sql"])
                logger.info(f"[DB] Schema 演进: 新增列 {c['table']}.{c['col']}")
            except Exception as e:
                logger.warning(f"[DB] Schema 演进失败 {c['table']}.{c['col']}: {e}")

    for c in _needed_indexes:
        if (c["table"], c["idx"]) not in existing_idxs:
            try:
                await conn.execute_query(c["sql"])
                logger.info(f"[DB] Schema 演进: 新增索引 {c['table']}.{c['idx']}")
            except Exception as e:
                logger.warning(f"[DB] Schema 演进失败 {c['table']}.{c['idx']}: {e}")


# ════════════════════════════════════════════════════════════════════════════
#  Section 4: Seed Data
# ════════════════════════════════════════════════════════════════════════════

# ── 4.1 超级用户 ──

async def init_superuser():
    """确保默认管理员账号及 Agent 专用账号存在且关键字段正确。

    不覆盖用户已修改的密码、邮箱等配置，仅修复：
    - 首次创建：创建 admin / hubstudio_agent 账号
    - RESET_ADMIN_PASSWORD=true：重置 admin 密码
    - is_superuser / is_active 缺失时修复
    - hubstudio_agent 确保非超管、非菜单用户
    """
    from app.models.admin import User
    from app.utils.password import get_password_hash

    # ── admin 管理员账号 ──
    user, created = await User.get_or_create(
        username="admin",
        defaults={
            "email": "admin@admin.com",
            "password": get_password_hash(settings.DEFAULT_PASSWORD),
            "is_active": True,
            "is_superuser": True,
        }
    )

    if created:
        logger.info("[init_superuser] 创建默认管理员 admin")
    else:
        # 已存在用户：仅修复关键字段，不覆盖用户配置
        changed = False

        if settings.RESET_ADMIN_PASSWORD:
            user.password = get_password_hash(settings.DEFAULT_PASSWORD)
            changed = True

        if not user.is_superuser:
            user.is_superuser = True
            changed = True

        if not user.is_active:
            user.is_active = True
            changed = True

        if changed:
            update_fields = []
            if settings.RESET_ADMIN_PASSWORD:
                update_fields.append("password")
            if not user.is_superuser:
                update_fields.append("is_superuser")
            if not user.is_active:
                update_fields.append("is_active")
            await user.save(update_fields=update_fields)
            logger.info("[Admin] 管理员关键字段已修复")
        else:
            logger.debug("[Admin] 管理员账号已就绪")

    # ── hubstudio_agent 专用账号（非超管，仅通过 API 操作）──
    agent_user, agent_created = await User.get_or_create(
        username="hubstudio_agent",
        defaults={
            "email": "hubstudio_agent@local",
            "password": get_password_hash(settings.DEFAULT_PASSWORD),
            "is_active": True,
            "is_superuser": False,
        }
    )

    if agent_created:
        logger.info("[init_superuser] 创建 HubStudio Agent 专用账号 hubstudio_agent")
    else:
        # 已存在：修复关键字段
        agent_changed = False
        if getattr(agent_user, "is_superuser", False):
            agent_user.is_superuser = False
            agent_changed = True
        if not getattr(agent_user, "is_active", True):
            agent_user.is_active = True
            agent_changed = True
        if agent_changed:
            await agent_user.save()
            logger.info("[init_superuser] HubStudio Agent 账号字段已修复")

    # 确保角色绑定（兼容首次启动时 init_roles 先于 init_superuser 执行的场景）
    await _ensure_admin_role_binding()
    await _ensure_agent_role_binding()


# ── 4.2 菜单 ──

async def init_menus():
    """根据 MENU_DEFINITIONS 声明式同步菜单：创建/更新新增菜单，隐藏废弃菜单"""
    t0 = time.perf_counter()

    all_menus = await Menu.all()
    menu_lookup = {}       # (path, parent_id) -> Menu
    path_to_id = {}        # path -> id（用于父级查找）
    declared_paths = {d["path"] for d in MENU_DEFINITIONS}

    for m in all_menus:
        menu_lookup[(m.path, m.parent_id)] = m

    root_items = [d for d in MENU_DEFINITIONS if d["parent_path"] == ""]
    child_items = [d for d in MENU_DEFINITIONS if d["parent_path"] != ""]

    # 第 1 轮：根级菜单
    for item in root_items:
        existing = menu_lookup.get((item["path"], 0))
        if existing:
            path_to_id[item["path"]] = existing.id
            await _sync_menu_fields(existing, item)
        else:
            menu = await _upsert_menu(item, parent_id=0)
            menu_lookup[(item["path"], 0)] = menu
            path_to_id[item["path"]] = menu.id

    # 第 2 轮：子级菜单
    remaining = list(child_items)
    while remaining:
        processed = []
        for item in remaining:
            parent_path = item["parent_path"]
            if parent_path not in path_to_id:
                continue
            parent_id = path_to_id[parent_path]
            existing = menu_lookup.get((item["path"], parent_id))
            if existing:
                path_to_id[item["path"]] = existing.id
                await _sync_menu_fields(existing, item)
            else:
                menu = await _upsert_menu(item, parent_id=parent_id)
                menu_lookup[(item["path"], parent_id)] = menu
                path_to_id[item["path"]] = menu.id
            processed.append(item)
        remaining = [r for r in remaining if r not in processed]
        if not processed:
            for item in remaining:
                logger.warning(f"[init_menus] 父菜单未定义: {item['parent_path']}，跳过 {item['path']}")
            break

    # 第 3 轮：隐藏废弃菜单
    for m in all_menus:
        if m.path not in declared_paths and not m.is_hidden:
            m.is_hidden = True
            await m.save(update_fields=["is_hidden"])
            logger.info(f"[init_menus] 废弃菜单已隐藏: {m.name} ({m.path})")

    logger.debug(f"[Init] 菜单同步完成 ({time.perf_counter() - t0:.2f}s)")


async def _upsert_menu(item: dict, parent_id: int) -> Menu:
    """创建菜单（调用处已确保不存在，直接 create）"""
    menu = await Menu.create(
        name=item["name"], path=item["path"], parent_id=parent_id,
        menu_type=item["menu_type"], icon=item["icon"], order=item["order"],
        is_hidden=bool(item.get("is_hidden", False)),
        component=item["component"], keepalive=False,
        redirect=item.get("redirect"),
    )
    logger.info(f"[init_menus] 新增菜单: {item['name']} ({item['path']}, parent_id={parent_id})")
    return menu


async def _sync_menu_fields(menu, item: dict):
    """按需更新菜单字段（从 dict 定义同步到已有菜单记录）"""
    updated = False
    for field in ("name", "menu_type", "icon", "order", "component", "redirect", "is_hidden"):
        if field == "is_hidden":
            new_val = bool(item.get("is_hidden", False))
            old = bool(getattr(menu, field, False))
            if old != new_val:
                setattr(menu, field, new_val)
                updated = True
        else:
            new_val = item.get(field)
            if getattr(menu, field) != new_val:
                setattr(menu, field, new_val)
                updated = True
    if updated:
        await menu.save()


# ── 4.3 全局配置（旧 Config 模型）──

async def init_configs():
    """初始化全局配置项（upsert：不存在则创建，存在则同步元数据，不覆盖用户值）"""
    defaults = _config_defaults()
    existing_map = {c.name: c for c in await Config.all()}

    to_create = []
    for name, value, desc, cat, order, is_secret in defaults:
        existing = existing_map.get(name)
        if existing:
            # 已有配置：只更新元数据，不覆盖用户已配置的值
            meta_changed = False
            if existing.description != desc:
                existing.description = desc
                meta_changed = True
            if existing.category != cat:
                existing.category = cat
                meta_changed = True
            if existing.sort_order != order:
                existing.sort_order = order
                meta_changed = True
            if existing.is_secret != is_secret:
                existing.is_secret = is_secret
                meta_changed = True
            if meta_changed:
                await existing.save()
        else:
            to_create.append(Config(
                name=name, value=value, description=desc, category=cat,
                sort_order=order, is_secret=is_secret,
            ))

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
    """按自然键 upsert Provider 实例 + 配置项，并清理废弃配置

    优化：后续重启时大部分记录已存在且无变动，跳过 DB 写入；
    首轮缺失记录使用 bulk_create 批量创建。
    """
    t0 = time.perf_counter()
    defaults = _PROVIDER_DEFAULTS

    # ── 第 1 轮：按 (provider_type, provider_name) 批量 upsert Provider ──
    existing_providers_map = {
        (p.provider_type, p.provider_name): p
        for p in await ConfigProvider.all()
    }

    new_providers = []
    providers_to_save = []
    for ptype, name, desc, priority, _ in defaults:
        provider = existing_providers_map.get((ptype, name))
        if provider:
            if provider.description != desc or provider.priority != priority or not provider.is_default:
                provider.description = desc
                provider.priority = priority
                provider.is_default = True
                providers_to_save.append(provider)
        else:
            new_providers.append(ConfigProvider(
                provider_type=ptype, provider_name=name,
                description=desc, is_default=True, priority=priority,
                status="active",
            ))

    if new_providers:
        await ConfigProvider.bulk_create(new_providers)
        # 刷新映射，确保第 2 轮能找到新创建的 provider
        for p in await ConfigProvider.all():
            existing_providers_map[(p.provider_type, p.provider_name)] = p
        for p in new_providers:
            logger.info(f"[init_providers] 新增 Provider: {p.provider_type}/{p.provider_name}")

    if providers_to_save:
        await asyncio.gather(*[p.save() for p in providers_to_save])

    t1 = time.perf_counter()

    # ── 第 2 轮：按 (provider_id, config_key) 批量 upsert Item ──
    existing_items_map = {
        (ci.provider_id, ci.config_key): ci
        for ci in await ProviderConfigItem.all()
    }

    new_items = []
    items_to_save = []
    for ptype, name, _, _, items in defaults:
        provider = existing_providers_map[(ptype, name)]
        for i, (key, value, item_desc, config_type, is_secret, is_required) in enumerate(items):
            existing_item = existing_items_map.get((provider.id, key))
            if existing_item:
                if (existing_item.config_type != config_type
                        or existing_item.is_secret != is_secret
                        or existing_item.is_required != is_required
                        or existing_item.description != item_desc
                        or existing_item.sort != i):
                    existing_item.config_type = config_type
                    existing_item.is_secret = is_secret
                    existing_item.is_required = is_required
                    existing_item.description = item_desc
                    existing_item.sort = i
                    items_to_save.append(existing_item)
            else:
                new_items.append(ProviderConfigItem(
                    provider_id=provider.id, config_key=key,
                    config_value=str(value or ''), config_type=config_type,
                    is_secret=is_secret, is_required=is_required,
                    description=item_desc, sort=i,
                ))

    if new_items:
        await ProviderConfigItem.bulk_create(new_items)
    if items_to_save:
        await asyncio.gather(*[it.save() for it in items_to_save])

    t2 = time.perf_counter()

    # ── 清理已废弃的配置项 ──
    await _cleanup_deprecated_provider_items()

    t3 = time.perf_counter()
    logger.info(
        f"[Init] Provider 同步完成 | Providers: {(t1 - t0):.2f}s"
        f" | Items: {(t2 - t1):.2f}s | Cleanup: {(t3 - t2):.2f}s"
        f" | 新增 Provider: {len(new_providers)} | 新增 Item: {len(new_items)}"
        f" | 更新 Provider: {len(providers_to_save)} | 更新 Item: {len(items_to_save)}"
    )


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
    """初始化角色并关联菜单/API（按 code 识别，幂等），含 Agent 专用角色绑定"""
    admin_role = await Role.filter(code="admin").first()
    user_role = await Role.filter(code="user").first()
    agent_role = await Role.filter(code="hub_agent").first()

    if not admin_role or not user_role or not agent_role:
        await _create_default_roles()
    else:
        await _sync_existing_roles()
        # 增量同步 hub_agent 的 API 权限（不受菜单变更影响）
        if agent_role:
            await _grant_hub_agent_apis(agent_role, await Api.all())

    # 确保 admin 用户绑定 admin 角色
    await _ensure_admin_role_binding()

    # 确保 hubstudio_agent 用户绑定 hub_agent 角色
    await _ensure_agent_role_binding()


async def _create_default_roles():
    """首次创建默认角色（管理员 + 普通用户 + HubStudio Agent），幂等：get_or_create"""
    admin_role, _ = await Role.get_or_create(
        code="admin",
        defaults={"name": "管理员", "desc": "管理员角色"}
    )
    user_role, _ = await Role.get_or_create(
        code="user",
        defaults={"name": "普通用户", "desc": "普通用户角色"}
    )
    agent_role, _ = await Role.get_or_create(
        code="hub_agent",
        defaults={"name": "HubStudio Agent", "desc": "HubStudio Agent 自动任务专用角色，仅 API 无菜单"}
    )

    all_apis = await Api.all()
    all_menus = await Menu.all()

    # admin：全部 API + 全部菜单
    existing_admin_apis = {a.id for a in await admin_role.apis.all()}
    new_admin_apis = [a for a in all_apis if a.id not in existing_admin_apis]
    if new_admin_apis:
        await admin_role.apis.add(*new_admin_apis)

    existing_admin_menus = {m.id for m in await admin_role.menus.all()}
    new_admin_menus = [m for m in all_menus if m.id not in existing_admin_menus]
    if new_admin_menus:
        await admin_role.menus.add(*new_admin_menus)

    # user：全部菜单
    existing_user_menus = {m.id for m in await user_role.menus.all()}
    new_user_menus = [m for m in all_menus if m.id not in existing_user_menus]
    if new_user_menus:
        await user_role.menus.add(*new_user_menus)

    await _grant_menu_apis(user_role, all_menus, all_apis)

    # hub_agent：仅 HubStudio Agent 相关 API，无菜单
    await _grant_hub_agent_apis(agent_role, all_apis)


async def _sync_existing_roles():
    """已有角色时，增量同步新增菜单 + 对应的 API（按 code 区分权限策略）"""
    all_menus = await Menu.all()
    all_menu_ids = {m.id for m in all_menus}
    all_apis = await Api.all()

    for role in await Role.all():
        role_menu_ids = {m.id for m in await role.menus.all()}
        missing_ids = all_menu_ids - role_menu_ids
        if not missing_ids:
            continue

        # 按 code 区分策略：admin 拥有全部，user 仅增量
        is_admin = role.code == "admin"

        missing_menus = []
        for m in all_menus:
            if m.id not in missing_ids:
                continue
            if m.parent_id == 0:
                if is_admin:
                    missing_menus.append(m)
            elif m.parent_id in role_menu_ids:
                missing_menus.append(m)

        if missing_menus:
            await role.menus.add(*missing_menus)
            await _grant_menu_apis(role, missing_menus, all_apis)
            logger.info(f"[init_roles] 角色 {role.name}({role.code}) 新增菜单: {[m.name for m in missing_menus]}")


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
            # 匹配规则1: API path 第三段命中任一前缀（两边都 clean，兼容含 -/_ 的路径）
            api_parts = api.path.strip("/").split("/")
            if len(api_parts) >= 3 and api_parts[0] == "api" and api_parts[1] == "v1":
                if _clean_segment(api_parts[2]) in prefixes:
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


# ── HubStudio Agent 专用权限 ──

# HubStudio Agent 必需的 API 路径键（精确匹配）
_HUB_AGENT_API_PATHS = {
    ("POST", "/api/v1/site-pipeline/hub-job/claim"),
    ("POST", "/api/v1/site-pipeline/hub-job/heartbeat"),
    ("GET",  "/api/v1/site-pipeline/hub-job/agent-config"),
    ("GET",  "/api/v1/base/userinfo"),
}

# report 路径包含 {job_id} 动态参数，不能用精确匹配，用后缀识别
_HUB_REPORT_SUFFIX = "/site-pipeline/hub-job/"
_HUB_REPORT_ENDS  = "/report"


async def _grant_hub_agent_apis(agent_role, all_apis: list):
    """仅授予 HubStudio Agent 必需的 API 权限（无菜单）"""
    existing_ids = {a.id for a in await agent_role.apis.all()}
    to_add = []
    for api in all_apis:
        if api.id in existing_ids:
            continue
        key = (api.method, api.path)
        if key in _HUB_AGENT_API_PATHS:
            to_add.append(api)
        elif api.method == "POST" and _HUB_REPORT_SUFFIX in api.path and api.path.endswith(_HUB_REPORT_ENDS):
            to_add.append(api)

    if to_add:
        await agent_role.apis.add(*to_add)
        logger.info(
            f"[init_roles] hub_agent 角色已授予 {len(to_add)} 个 API: "
            f"{[(a.method, a.path) for a in to_add]}"
        )
    else:
        logger.debug("[init_roles] hub_agent 角色 API 已就绪")


async def _ensure_admin_role_binding():
    """确保 admin 用户绑定了 admin 角色（幂等）"""
    from app.models.admin import User

    admin_user = await User.filter(username="admin").first()
    admin_role = await Role.filter(code="admin").first()
    if not admin_user or not admin_role:
        return

    existing = {r.code for r in await admin_user.roles.all()}
    if "admin" not in existing:
        await admin_user.roles.add(admin_role)
        logger.info("[init_roles] admin 已绑定 admin 角色")


async def _ensure_agent_role_binding():
    """确保 hubstudio_agent 用户绑定了 hub_agent 角色（幂等）"""
    from app.models.admin import User

    agent_user = await User.filter(username="hubstudio_agent").first()
    agent_role = await Role.filter(code="hub_agent").first()
    if not agent_user or not agent_role:
        return

    existing = {r.code for r in await agent_user.roles.all()}
    if "hub_agent" not in existing:
        await agent_user.roles.add(agent_role)
        logger.info("[init_roles] hubstudio_agent 已绑定 hub_agent 角色")


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
            logger.info(f"[Jobs] 僵尸任务清理: 本实例 {own_count} 个 + 心跳超时 {orphan_count} 个")
        else:
            logger.debug("[Jobs] 无僵尸任务")
    except Exception as e:
        logger.warning(f"僵尸任务清理跳过: {e}")


# ── 5.2 分布式锁 ──

async def _ensure_lock_table():
    """确保分布式锁表存在（先查再建，避免 MySQL IF NOT EXISTS 仍打 warning）"""
    conn = connections.get("default")
    try:
        result = await conn.execute_query("SHOW TABLES LIKE 'system_init_lock'")
        if result[1]:
            return  # 表已存在，跳过
    except Exception:
        pass
    await conn.execute_script("""
        CREATE TABLE IF NOT EXISTS system_init_lock (
            lock_key VARCHAR(64) PRIMARY KEY,
            instance_id VARCHAR(128) NOT NULL,
            acquired_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


async def _try_acquire_init_lock(lock_key: str, timeout_seconds: int = 300) -> bool:
    """尝试获取分布式锁。过期锁自动清理。"""
    await _ensure_lock_table()
    conn = connections.get("default")
    now = datetime.now()
    expires = now + timedelta(seconds=timeout_seconds)

    # 清理过期锁
    await conn.execute_query(
        "DELETE FROM system_init_lock WHERE lock_key = %s AND expires_at < %s",
        [lock_key, now.isoformat()]
    )
    try:
        await conn.execute_query(
            "INSERT INTO system_init_lock (lock_key, instance_id, acquired_at, expires_at) VALUES (%s, %s, %s, %s)",
            [lock_key, _INSTANCE_ID, now.isoformat(), expires.isoformat()]
        )
        logger.debug(f"[InitLock] 获取锁: {lock_key}, instance={_INSTANCE_ID}")
        return True
    except Exception:
        logger.debug(f"[InitLock] 锁被其他实例持有: {lock_key}，跳过")
        return False


async def _release_init_lock(lock_key: str):
    """释放本实例持有的分布式锁"""
    try:
        conn = connections.get("default")
        await conn.execute_query(
            "DELETE FROM system_init_lock WHERE lock_key = %s AND instance_id = %s",
            [lock_key, _INSTANCE_ID]
        )
    except Exception:
        pass


# ── 5.2 持久化初始化标记 ──

_INIT_COMPLETED_KEY = "system_init_version"


async def _is_init_completed() -> bool:
    """检查当前版本是否已完成初始化（基于 Config 表持久化标记）"""
    try:
        stored = await Config.get_value(_INIT_COMPLETED_KEY, default="")
        return stored == settings.VERSION
    except Exception:
        return False


async def _mark_init_completed():
    """标记当前版本初始化完成"""
    try:
        cfg, _ = await Config.get_or_create(
            name=_INIT_COMPLETED_KEY,
            defaults={
                "value": settings.VERSION,
                "description": "系统初始化完成版本标记（版本变更时自动重新同步菜单/角色/API）",
                "category": "general",
                "sort_order": 0,
                "is_secret": False,
            }
        )
        if cfg.value != settings.VERSION:
            cfg.value = settings.VERSION
            await cfg.save(update_fields=["value"])
            logger.info(f"[Init] 版本标记已更新: {cfg.value} → {settings.VERSION}")
    except Exception as e:
        logger.warning(f"[Init] 无法标记初始化完成: {e}")


# ── 5.3 启动入口 ──

async def init_essential():
    """应用启动轻量初始化：DB 检查 + 僵尸任务清理 + 幂等种子同步

    不包含主键修复、用户去重等高风险操作。
    菜单/角色/Provider 同步基于版本号持久化标记：同版本只执行一次，
    版本号变更（新部署、新增菜单/API）时自动重新同步。
    """
    t0 = time.perf_counter()
    steps = []

    t = time.perf_counter()
    await init_db()
    steps.append(("DB 检查", time.perf_counter() - t))

    t = time.perf_counter()
    await recover_stale_jobs()
    steps.append(("僵尸任务清理", time.perf_counter() - t))

    # 版本号持久化标记：同版本已完成初始化则跳过同步，避免 worker 重启导致权限丢失
    if await _is_init_completed():
        logger.info("[Init] 当前版本 {} 已完成初始化，跳过种子同步", settings.VERSION)

        # Provider 缓存仍需加载（每次启动都需要）
        from app.utils.provider_resolver import _load_configs_to_cache
        await _load_configs_to_cache()
        steps.append(("Provider 缓存加载", 0))
    else:
        t = time.perf_counter()
        if await _try_acquire_init_lock("init_menus_roles", timeout_seconds=300):
            try:
                await init_menus()
                await init_apis()
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
        from app.utils.provider_resolver import _load_configs_to_cache
        await _load_configs_to_cache()
        steps.append(("Provider 同步", time.perf_counter() - t))

        await _mark_init_completed()

    total = time.perf_counter() - t0
    detail = " | ".join(f"{name}: {elapsed:.1f}s" for name, elapsed in steps)
    logger.info(f"[Init] 初始化完成 ({total:.1f}s) - {detail}")


async def init_data():
    """种子数据初始化入口（幂等，不做数据库修复/迁移）。

    职责：超级用户、全局配置。
    菜单/API/角色/Provider 同步由 init_essential() 完成。
    """
    await init_essential()
    await init_superuser()
    await init_configs()


async def _ensure_tortoise_initialized():
    """确保 ORM 已初始化（幂等）。"""
    from app.settings import TORTOISE_ORM

    try:
        connections.get("default")
    except Exception:
        await Tortoise.init(config=TORTOISE_ORM)


async def _run_init_data_with_orm() -> None:
    """独立脚本启动时使用：初始化 ORM → 执行种子数据 → 关闭连接。"""
    await _ensure_tortoise_initialized()
    try:
        await init_data()
    finally:
        try:
            await Tortoise.close_connections()
        except Exception:
            pass


def init_default_data():
    """供 entrypoint.sh / 独立脚本调用的初始化入口。

    容器 entrypoint 不是 FastAPI lifespan，不能依赖其自动完成 ORM 初始化，
    因此本函数内部自行完成 Tortoise.init → init_data → close 的完整生命周期。
    """
    asyncio.run(_run_init_data_with_orm())
