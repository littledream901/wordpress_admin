from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "api" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "path" VARCHAR(100) NOT NULL  /* API路径 */,
    "method" VARCHAR(6) NOT NULL  /* 请求方法 */,
    "summary" VARCHAR(500) NOT NULL  /* 请求简介 */,
    "tags" VARCHAR(100) NOT NULL  /* API标签 */
);
CREATE INDEX IF NOT EXISTS "idx_api_created_78d19f" ON "api" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_api_updated_643c8b" ON "api" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_api_path_9ed611" ON "api" ("path");
CREATE INDEX IF NOT EXISTS "idx_api_method_a46dfb" ON "api" ("method");
CREATE INDEX IF NOT EXISTS "idx_api_summary_400f73" ON "api" ("summary");
CREATE INDEX IF NOT EXISTS "idx_api_tags_04ae27" ON "api" ("tags");
CREATE TABLE IF NOT EXISTS "auditlog" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "user_id" INT NOT NULL  /* 用户ID */,
    "username" VARCHAR(64) NOT NULL  DEFAULT '' /* 用户名称 */,
    "module" VARCHAR(64) NOT NULL  DEFAULT '' /* 功能模块 */,
    "summary" VARCHAR(128) NOT NULL  DEFAULT '' /* 请求描述 */,
    "method" VARCHAR(10) NOT NULL  DEFAULT '' /* 请求方法 */,
    "path" VARCHAR(255) NOT NULL  DEFAULT '' /* 请求路径 */,
    "status" INT NOT NULL  DEFAULT -1 /* 状态码 */,
    "response_time" INT NOT NULL  DEFAULT 0 /* 响应时间(单位ms) */,
    "request_args" JSON   /* 请求参数 */,
    "response_body" JSON   /* 返回数据 */
);
CREATE INDEX IF NOT EXISTS "idx_auditlog_created_cc33d0" ON "auditlog" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_auditlog_updated_2f871f" ON "auditlog" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_auditlog_user_id_4b93fa" ON "auditlog" ("user_id");
CREATE INDEX IF NOT EXISTS "idx_auditlog_usernam_b187b3" ON "auditlog" ("username");
CREATE INDEX IF NOT EXISTS "idx_auditlog_module_04058b" ON "auditlog" ("module");
CREATE INDEX IF NOT EXISTS "idx_auditlog_summary_3e27da" ON "auditlog" ("summary");
CREATE INDEX IF NOT EXISTS "idx_auditlog_method_4270a2" ON "auditlog" ("method");
CREATE INDEX IF NOT EXISTS "idx_auditlog_path_b99502" ON "auditlog" ("path");
CREATE INDEX IF NOT EXISTS "idx_auditlog_status_2a72d2" ON "auditlog" ("status");
CREATE INDEX IF NOT EXISTS "idx_auditlog_respons_8caa87" ON "auditlog" ("response_time");
CREATE TABLE IF NOT EXISTS "config" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "name" VARCHAR(100) NOT NULL  /* 配置键名 */,
    "value" TEXT NOT NULL  /* 配置值 */,
    "description" VARCHAR(255)   /* 配置说明 */,
    "category" VARCHAR(50) NOT NULL  /* 配置分类 */,
    "sort_order" INT NOT NULL  DEFAULT 0 /* 排序 */,
    "is_secret" INT NOT NULL  DEFAULT 0 /* 是否为敏感信息（前端脱敏显示） */,
    "is_enabled" INT NOT NULL  DEFAULT 1 /* 是否启用 */
) /* 系统配置键值对表，按 category 分类管理 1Panel、Cloudflare、Dynadot、HubStudio 等配置 */;
CREATE INDEX IF NOT EXISTS "idx_config_created_0e70f0" ON "config" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_config_updated_b46384" ON "config" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_config_name_2c83c8" ON "config" ("name");
CREATE INDEX IF NOT EXISTS "idx_config_categor_8d9ac8" ON "config" ("category");
CREATE TABLE IF NOT EXISTS "config_provider" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "provider_type" VARCHAR(64) NOT NULL  /* 提供者类型 */,
    "provider_name" VARCHAR(128) NOT NULL  /* 名称 */,
    "description" VARCHAR(500) NOT NULL  DEFAULT '' /* 描述 */,
    "remark" VARCHAR(500) NOT NULL  DEFAULT '' /* 备注 */,
    "status" VARCHAR(32) NOT NULL  DEFAULT 'active' /* 状态 */,
    "is_default" INT NOT NULL  DEFAULT 0 /* 是否默认 */,
    "priority" INT NOT NULL  DEFAULT 0 /* 优先级（越大越高） */,
    "tags" VARCHAR(500) NOT NULL  DEFAULT '' /* 标签(逗号分隔) */
) /* 配置提供者（一个实例 = 一个账号\/节点\/环境） */;
CREATE INDEX IF NOT EXISTS "idx_config_prov_created_c9be2d" ON "config_provider" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_config_prov_updated_90a68f" ON "config_provider" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_config_prov_provide_84d9d5" ON "config_provider" ("provider_type");
CREATE TABLE IF NOT EXISTS "account" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "account_type" VARCHAR(50) NOT NULL  /* 账号类型 */,
    "username" VARCHAR(200) NOT NULL  /* 账号 */,
    "password" VARCHAR(500) NOT NULL  /* 密码 */,
    "env_id" INT NOT NULL  DEFAULT 0 /* 环境ID */,
    "two_fa" VARCHAR(500)   /* 2FA */,
    "remark" TEXT   /* 备注 */,
    "provider_id" BIGINT REFERENCES "config_provider" ("id") ON DELETE CASCADE /* 关联Provider */
);
CREATE INDEX IF NOT EXISTS "idx_account_created_028865" ON "account" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_account_updated_63b235" ON "account" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_account_account_628e69" ON "account" ("account_type");
CREATE INDEX IF NOT EXISTS "idx_account_usernam_c7a6b4" ON "account" ("username");
CREATE INDEX IF NOT EXISTS "idx_account_env_id_62e409" ON "account" ("env_id");
CREATE TABLE IF NOT EXISTS "dept" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "name" VARCHAR(20) NOT NULL UNIQUE /* 部门名称 */,
    "desc" VARCHAR(500)   /* 备注 */,
    "is_deleted" INT NOT NULL  DEFAULT 0 /* 软删除标记 */,
    "order" INT NOT NULL  DEFAULT 0 /* 排序 */,
    "parent_id" INT NOT NULL  DEFAULT 0 /* 父部门ID */
);
CREATE INDEX IF NOT EXISTS "idx_dept_created_4b11cf" ON "dept" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_dept_updated_0c0bd1" ON "dept" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_dept_name_c2b9da" ON "dept" ("name");
CREATE INDEX IF NOT EXISTS "idx_dept_is_dele_466228" ON "dept" ("is_deleted");
CREATE INDEX IF NOT EXISTS "idx_dept_order_ddabe1" ON "dept" ("order");
CREATE INDEX IF NOT EXISTS "idx_dept_parent__a71a57" ON "dept" ("parent_id");
CREATE TABLE IF NOT EXISTS "deptclosure" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "ancestor" INT NOT NULL  /* 父代 */,
    "descendant" INT NOT NULL  /* 子代 */,
    "level" INT NOT NULL  DEFAULT 0 /* 深度 */
);
CREATE INDEX IF NOT EXISTS "idx_deptclosure_created_96f6ef" ON "deptclosure" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_deptclosure_updated_41fc08" ON "deptclosure" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_deptclosure_ancesto_fbc4ce" ON "deptclosure" ("ancestor");
CREATE INDEX IF NOT EXISTS "idx_deptclosure_descend_2ae8b1" ON "deptclosure" ("descendant");
CREATE INDEX IF NOT EXISTS "idx_deptclosure_level_ae16b2" ON "deptclosure" ("level");
CREATE TABLE IF NOT EXISTS "site_pipeline_feed_file" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "original_name" VARCHAR(500) NOT NULL  DEFAULT '' /* 原始文件名 */,
    "source_file" VARCHAR(500) NOT NULL  DEFAULT '' /* 源文件路径 (文件A) */,
    "copy_file" VARCHAR(500) NOT NULL  DEFAULT '' /* 副本文件路径 (文件B) */,
    "processed_file" VARCHAR(500) NOT NULL  DEFAULT '' /* 替换后的文件路径 */,
    "file_type" VARCHAR(10) NOT NULL  DEFAULT '' /* 文件类型: csv \/ xml */,
    "file_size" INT NOT NULL  DEFAULT 0 /* 文件大小(字节) */,
    "source_domain" VARCHAR(255) NOT NULL  DEFAULT '' /* 原始域名 */,
    "target_domain" VARCHAR(255) NOT NULL  DEFAULT '' /* 替换目标域名 */,
    "replace_count" INT NOT NULL  DEFAULT 0 /* 替换次数 */,
    "status" VARCHAR(32) NOT NULL  DEFAULT 'uploaded' /* 状态: uploaded\/copied\/replaced */
) /* Feed 文件 */;
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_created_8094f4" ON "site_pipeline_feed_file" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_updated_c37945" ON "site_pipeline_feed_file" ("updated_at");
CREATE TABLE IF NOT EXISTS "site_pipeline_gmail_account" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "last_name" VARCHAR(100) NOT NULL  DEFAULT '' /* last name */,
    "first_name" VARCHAR(100) NOT NULL  DEFAULT '' /* first name */,
    "full_name" VARCHAR(200) NOT NULL  DEFAULT '' /* full name */,
    "zip_code" VARCHAR(32) NOT NULL  DEFAULT '' /* zip code */,
    "shipping_address_1" VARCHAR(255) NOT NULL  DEFAULT '' /* Shipping address 1 */,
    "shipping_address_2" VARCHAR(255) NOT NULL  DEFAULT '' /* Shipping address 2 */,
    "country" VARCHAR(100) NOT NULL  DEFAULT '' /* Country */,
    "province_state" VARCHAR(100) NOT NULL  DEFAULT '' /* Province\/State */,
    "city" VARCHAR(100) NOT NULL  DEFAULT '' /* City */,
    "phone" VARCHAR(64) NOT NULL  DEFAULT '' /* phone */,
    "username" VARCHAR(255) NOT NULL UNIQUE /* Username */,
    "password" VARCHAR(255) NOT NULL  DEFAULT '' /* Password */,
    "two_fa_key" VARCHAR(255) NOT NULL  DEFAULT '' /* 2FA Key */,
    "two_fa_code" VARCHAR(16) NOT NULL  DEFAULT '' /* 2FA 验证码 */,
    "link_to_generate_login_code" VARCHAR(500) NOT NULL  DEFAULT '' /* Link To Generate Login Code from 2FA Key */,
    "recovery_email" VARCHAR(255) NOT NULL  DEFAULT '' /* Recovery Email */,
    "status" VARCHAR(64) NOT NULL  DEFAULT '正常' /* 健康状态 */,
    "assigned_site_id" INT   /* 分配站点ID */,
    "assigned_site_domain" VARCHAR(255) NOT NULL  DEFAULT '' /* 分配站点域名 */
);
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_created_645482" ON "site_pipeline_gmail_account" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_updated_37164f" ON "site_pipeline_gmail_account" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_usernam_7e1db3" ON "site_pipeline_gmail_account" ("username");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_status_be1d6a" ON "site_pipeline_gmail_account" ("status");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_assigne_cab5d0" ON "site_pipeline_gmail_account" ("assigned_site_id");
CREATE TABLE IF NOT EXISTS "site_pipeline_hubstudio_agent_heartbeat" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "worker_name" VARCHAR(128) NOT NULL UNIQUE /* 节点名称 */,
    "provider_id" INT NOT NULL  DEFAULT 0 /* 对应的 provider_id */,
    "last_heartbeat" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP /* 最后心跳时间 */,
    "status" VARCHAR(32) NOT NULL  DEFAULT 'online' /* 状态: online \/ offline */,
    "version" VARCHAR(32) NOT NULL  DEFAULT '' /* Agent 版本 */,
    "host_info" VARCHAR(255) NOT NULL  DEFAULT '' /* 主机信息 */,
    "last_task_id" INT NOT NULL  DEFAULT 0 /* 最后执行的任务ID */,
    "last_task_status" VARCHAR(32) NOT NULL  DEFAULT '' /* 最后任务状态 */,
    "total_tasks" INT NOT NULL  DEFAULT 0 /* 累计执行任务数 */
) /* Agent 心跳记录 — 用于检测 Agent 是否在线 */;
CREATE TABLE IF NOT EXISTS "site_pipeline_hubstudio_job" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "site_id" INT NOT NULL  /* 站点ID */,
    "domain" VARCHAR(255) NOT NULL  /* 域名 */,
    "provider_id" INT NOT NULL  DEFAULT 0 /* 执行节点 provider_id */,
    "job_type" VARCHAR(64) NOT NULL  DEFAULT 'create_env' /* 任务类型 */,
    "status" VARCHAR(32) NOT NULL  DEFAULT 'pending' /* 任务状态 */,
    "payload_json" TEXT NOT NULL  /* 任务负载 */,
    "result_json" TEXT NOT NULL  /* 任务结果 */,
    "error_message" TEXT NOT NULL  /* 错误信息 */,
    "worker_name" VARCHAR(128) NOT NULL  DEFAULT '' /* 执行节点名称 */,
    "retry_count" INT NOT NULL  DEFAULT 0 /* 重试次数 */,
    "started_at" TIMESTAMP   /* 开始执行时间 */,
    "finished_at" TIMESTAMP   /* 完成时间 */
);
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_created_cde205" ON "site_pipeline_hubstudio_job" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_updated_7bd671" ON "site_pipeline_hubstudio_job" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_site_id_2056b8" ON "site_pipeline_hubstudio_job" ("site_id");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_domain_d8f602" ON "site_pipeline_hubstudio_job" ("domain");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_job_typ_9904bd" ON "site_pipeline_hubstudio_job" ("job_type");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_status_faffe3" ON "site_pipeline_hubstudio_job" ("status");
CREATE TABLE IF NOT EXISTS "import_job" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "import_type" VARCHAR(32) NOT NULL  /* 导入类型 */,
    "file_name" VARCHAR(255) NOT NULL  /* 文件名 */,
    "status" VARCHAR(16) NOT NULL  DEFAULT 'pending' /* 状态 */,
    "success_count" INT NOT NULL  DEFAULT 0 /* 成功数量 */,
    "fail_count" INT NOT NULL  DEFAULT 0 /* 失败数量 */,
    "error_report" TEXT NOT NULL  /* 错误报告(JSON) */
) /* 导入任务表 */;
CREATE INDEX IF NOT EXISTS "idx_import_job_created_086fb2" ON "import_job" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_import_job_updated_3ce89d" ON "import_job" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_import_job_import__699ba4" ON "import_job" ("import_type");
CREATE TABLE IF NOT EXISTS "menu" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "name" VARCHAR(20) NOT NULL  /* 菜单名称 */,
    "remark" JSON   /* 保留字段 */,
    "menu_type" VARCHAR(7)   /* 菜单类型 */,
    "icon" VARCHAR(100)   /* 菜单图标 */,
    "path" VARCHAR(100) NOT NULL  /* 菜单路径 */,
    "order" INT NOT NULL  DEFAULT 0 /* 排序 */,
    "parent_id" INT NOT NULL  DEFAULT 0 /* 父菜单ID */,
    "is_hidden" INT NOT NULL  DEFAULT 0 /* 是否隐藏 */,
    "component" VARCHAR(100) NOT NULL  /* 组件 */,
    "keepalive" INT NOT NULL  DEFAULT 1 /* 存活 */,
    "redirect" VARCHAR(100)   /* 重定向 */
);
CREATE INDEX IF NOT EXISTS "idx_menu_created_b6922b" ON "menu" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_menu_updated_e6b0a1" ON "menu" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_menu_name_b9b853" ON "menu" ("name");
CREATE INDEX IF NOT EXISTS "idx_menu_path_bf95b2" ON "menu" ("path");
CREATE INDEX IF NOT EXISTS "idx_menu_order_606068" ON "menu" ("order");
CREATE INDEX IF NOT EXISTS "idx_menu_parent__bebd15" ON "menu" ("parent_id");
CREATE TABLE IF NOT EXISTS "operation_job" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "resource_type" VARCHAR(32) NOT NULL  /* 资源类型 */,
    "resource_id" INT NOT NULL  DEFAULT 0 /* 资源ID */,
    "domain" VARCHAR(255) NOT NULL  DEFAULT '' /* 关联域名 */,
    "action_type" VARCHAR(32) NOT NULL  /* 操作类型 */,
    "status" VARCHAR(16) NOT NULL  DEFAULT 'pending' /* 任务状态 */,
    "step" VARCHAR(64) NOT NULL  DEFAULT '' /* 当前步骤标识 */,
    "total_steps" INT NOT NULL  DEFAULT 1 /* 总步骤数 */,
    "payload_json" TEXT NOT NULL  /* 任务负载(JSON) */,
    "result_json" TEXT NOT NULL  /* 任务结果(JSON) */,
    "error_message" TEXT NOT NULL  /* 错误信息 */,
    "worker_name" VARCHAR(128) NOT NULL  DEFAULT '' /* 执行节点 */,
    "batch_id" VARCHAR(64) NOT NULL  DEFAULT '' /* 批次ID（批量操作） */,
    "retry_count" INT NOT NULL  DEFAULT 0 /* 已重试次数 */,
    "max_retry" INT NOT NULL  DEFAULT 3 /* 最大重试次数 */,
    "started_at" TIMESTAMP   /* 开始执行时间 */,
    "finished_at" TIMESTAMP   /* 完成时间 */
) /* 通用操作任务表 */;
CREATE INDEX IF NOT EXISTS "idx_operation_j_created_d648b1" ON "operation_job" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_operation_j_updated_9dddc9" ON "operation_job" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_operation_j_resourc_80f7d7" ON "operation_job" ("resource_type");
CREATE INDEX IF NOT EXISTS "idx_operation_j_resourc_52734e" ON "operation_job" ("resource_id");
CREATE INDEX IF NOT EXISTS "idx_operation_j_domain_dd3dd6" ON "operation_job" ("domain");
CREATE INDEX IF NOT EXISTS "idx_operation_j_action__8fe844" ON "operation_job" ("action_type");
CREATE INDEX IF NOT EXISTS "idx_operation_j_status_ff68f5" ON "operation_job" ("status");
CREATE INDEX IF NOT EXISTS "idx_operation_j_batch_i_63533f" ON "operation_job" ("batch_id");
CREATE TABLE IF NOT EXISTS "provider_config_item" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "config_key" VARCHAR(128) NOT NULL  /* 配置键名 */,
    "config_value" TEXT NOT NULL  /* 配置值 */,
    "config_type" VARCHAR(32) NOT NULL  DEFAULT 'string' /* 值类型 */,
    "is_secret" INT NOT NULL  DEFAULT 0 /* 是否敏感 */,
    "is_required" INT NOT NULL  DEFAULT 0 /* 是否必填 */,
    "description" VARCHAR(500) NOT NULL  DEFAULT '' /* 描述 */,
    "remark" VARCHAR(500) NOT NULL  DEFAULT '' /* 备注 */,
    "sort" INT NOT NULL  DEFAULT 0 /* 排序 */,
    "provider_id" BIGINT NOT NULL REFERENCES "config_provider" ("id") ON DELETE CASCADE /* 所属提供者 */,
    CONSTRAINT "uid_provider_co_provide_e56aae" UNIQUE ("provider_id", "config_key")
) /* 配置提供者的键值对项 */;
CREATE INDEX IF NOT EXISTS "idx_provider_co_created_4408bb" ON "provider_config_item" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_provider_co_updated_88b372" ON "provider_config_item" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_provider_co_config__686a49" ON "provider_config_item" ("config_key");
CREATE TABLE IF NOT EXISTS "resource_provider_binding" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "resource_type" VARCHAR(64) NOT NULL  /* 资源类型 (site\/operation_job\/gmail_account) */,
    "resource_id" INT NOT NULL  /* 资源ID */,
    "provider_type" VARCHAR(64) NOT NULL  /* 提供者类型 */,
    "bind_type" VARCHAR(32) NOT NULL  DEFAULT 'preferred' /* 绑定类型 */,
    "remark" VARCHAR(500) NOT NULL  DEFAULT '' /* 备注 */,
    "provider_id" BIGINT NOT NULL REFERENCES "config_provider" ("id") ON DELETE CASCADE /* 提供者 */,
    CONSTRAINT "uid_resource_pr_resourc_46566b" UNIQUE ("resource_type", "resource_id", "provider_type")
) /* 资源 → 提供者绑定关系 */;
CREATE INDEX IF NOT EXISTS "idx_resource_pr_created_1f9be9" ON "resource_provider_binding" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_resource_pr_updated_989db5" ON "resource_provider_binding" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_resource_pr_resourc_711f75" ON "resource_provider_binding" ("resource_type");
CREATE INDEX IF NOT EXISTS "idx_resource_pr_resourc_f9479a" ON "resource_provider_binding" ("resource_id");
CREATE INDEX IF NOT EXISTS "idx_resource_pr_provide_a90673" ON "resource_provider_binding" ("provider_type");
CREATE TABLE IF NOT EXISTS "role" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "name" VARCHAR(20) NOT NULL UNIQUE /* 角色名称 */,
    "desc" VARCHAR(500)   /* 角色描述 */
);
CREATE INDEX IF NOT EXISTS "idx_role_created_7f5f71" ON "role" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_role_updated_5dd337" ON "role" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_role_name_e5618b" ON "role" ("name");
CREATE TABLE IF NOT EXISTS "site_pipeline_shopify_product" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "source_id" INT NOT NULL  /* 来源ID */,
    "source_url" VARCHAR(500) NOT NULL  DEFAULT '' /* 来源URL */,
    "product_url" VARCHAR(500) NOT NULL UNIQUE /* 产品URL */,
    "handle" VARCHAR(255) NOT NULL  DEFAULT '' /* handle */,
    "title" VARCHAR(500) NOT NULL  DEFAULT '' /* 标题 */,
    "vendor" VARCHAR(255) NOT NULL  DEFAULT '' /* vendor */,
    "product_type" VARCHAR(255) NOT NULL  DEFAULT '' /* product_type */,
    "tags" TEXT NOT NULL  /* tags */,
    "status" VARCHAR(64) NOT NULL  DEFAULT 'ready' /* 状态 */,
    "prod_info_json" TEXT NOT NULL  /* 完整产品JSON */,
    "assigned_site_id" INT   /* 分配目标站点ID */,
    "assigned_status" VARCHAR(64) NOT NULL  DEFAULT '' /* 分配状态 */,
    "imported_site_id" INT   /* 最近导入站点ID */,
    "imported_status" VARCHAR(64) NOT NULL  DEFAULT '' /* 导入状态 */,
    "imported_result" TEXT NOT NULL  /* 导入结果 */
);
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_created_090e5d" ON "site_pipeline_shopify_product" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_updated_0143e3" ON "site_pipeline_shopify_product" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_source__a99cbc" ON "site_pipeline_shopify_product" ("source_id");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_product_a86692" ON "site_pipeline_shopify_product" ("product_url");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_handle_093641" ON "site_pipeline_shopify_product" ("handle");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_status_f53802" ON "site_pipeline_shopify_product" ("status");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_assigne_56cbed" ON "site_pipeline_shopify_product" ("assigned_site_id");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_assigne_47458a" ON "site_pipeline_shopify_product" ("assigned_status");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_importe_1879ea" ON "site_pipeline_shopify_product" ("imported_site_id");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_importe_e99987" ON "site_pipeline_shopify_product" ("imported_status");
CREATE TABLE IF NOT EXISTS "site_pipeline_shopify_source" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "source_url" VARCHAR(500) NOT NULL UNIQUE /* 待采集URL */,
    "source_type" VARCHAR(32) NOT NULL  DEFAULT 'collection' /* source类型：collection\/product */,
    "status" VARCHAR(64) NOT NULL  DEFAULT 'pending' /* 采集状态 */,
    "max_products" INT NOT NULL  DEFAULT 0 /* 最大采集数量，0=不限 */,
    "last_collect_count" INT NOT NULL  DEFAULT 0 /* 最近一次采集数量 */,
    "last_collect_at" TIMESTAMP   /* 最近一次采集时间 */,
    "remark" VARCHAR(500) NOT NULL  DEFAULT '' /* 备注 */
);
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_created_9d40a8" ON "site_pipeline_shopify_source" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_updated_928bd4" ON "site_pipeline_shopify_source" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_source__0c3228" ON "site_pipeline_shopify_source" ("source_url");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_status_d07774" ON "site_pipeline_shopify_source" ("status");
CREATE TABLE IF NOT EXISTS "site_pipeline_site" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "domain" VARCHAR(255) NOT NULL UNIQUE /* 域名 */,
    "server_ip" VARCHAR(64) NOT NULL  DEFAULT '' /* 服务器IP */,
    "status" VARCHAR(64) NOT NULL  DEFAULT '待处理' /* 站点状态 */,
    "login_url" VARCHAR(500) NOT NULL  DEFAULT '' /* 登录地址 */,
    "woo_ck" VARCHAR(255) NOT NULL  DEFAULT '' /* Woo CK */,
    "woo_cs" VARCHAR(255) NOT NULL  DEFAULT '' /* Woo CS */,
    "ctx_refresh_url" VARCHAR(500) NOT NULL  DEFAULT '' /* CTX刷新链接 */,
    "feed_link" VARCHAR(500) NOT NULL  DEFAULT '' /* Feed链接 */,
    "cloudflare_status" VARCHAR(64) NOT NULL  DEFAULT '' /* Cloudflare状态 */,
    "dynadot_status" VARCHAR(64) NOT NULL  DEFAULT '' /* Dynadot状态 */,
    "onepanel_status" VARCHAR(64) NOT NULL  DEFAULT '' /* 1Panel建站状态 */,
    "hub_env_id" VARCHAR(255) NOT NULL  DEFAULT '' /* Hub环境ID */,
    "hub_env_name" VARCHAR(255) NOT NULL  DEFAULT '' /* Hub容器名称 */,
    "hub_status" VARCHAR(64) NOT NULL  DEFAULT '' /* Hub状态 */,
    "hub_account_id" VARCHAR(255) NOT NULL  DEFAULT '' /* Hub账号ID */,
    "hub_last_action" VARCHAR(64) NOT NULL  DEFAULT '' /* Hub最后操作类型 */,
    "woo_import_status" VARCHAR(64) NOT NULL  DEFAULT '' /* Woo导入状态 */,
    "gmc_status" VARCHAR(64) NOT NULL  DEFAULT '' /* GMC状态 */,
    "gmc_data" TEXT NOT NULL  /* GMC详细数据(JSON) */,
    "pipeline_status" VARCHAR(64) NOT NULL  DEFAULT '' /* 流水线状态 */,
    "pipeline_log" TEXT NOT NULL  /* 流水线日志 */
);
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_created_e85415" ON "site_pipeline_site" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_updated_182d9f" ON "site_pipeline_site" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_domain_49396a" ON "site_pipeline_site" ("domain");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_status_ad85be" ON "site_pipeline_site" ("status");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_cloudfl_07baa8" ON "site_pipeline_site" ("cloudflare_status");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_dynadot_da3d4b" ON "site_pipeline_site" ("dynadot_status");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_onepane_bdff56" ON "site_pipeline_site" ("onepanel_status");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_hub_sta_860396" ON "site_pipeline_site" ("hub_status");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_woo_imp_e96fb0" ON "site_pipeline_site" ("woo_import_status");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_gmc_sta_a52ccf" ON "site_pipeline_site" ("gmc_status");
CREATE INDEX IF NOT EXISTS "idx_site_pipeli_pipelin_21b003" ON "site_pipeline_site" ("pipeline_status");
CREATE TABLE IF NOT EXISTS "user" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "username" VARCHAR(20) NOT NULL UNIQUE /* 用户名称 */,
    "alias" VARCHAR(30)   /* 姓名 */,
    "email" VARCHAR(255) NOT NULL UNIQUE /* 邮箱 */,
    "phone" VARCHAR(20)   /* 电话 */,
    "password" VARCHAR(128)   /* 密码 */,
    "is_active" INT NOT NULL  DEFAULT 1 /* 是否激活 */,
    "is_superuser" INT NOT NULL  DEFAULT 0 /* 是否为超级管理员 */,
    "avatar" VARCHAR(512) NOT NULL  DEFAULT '' /* 头像URL或路径 */,
    "last_login" TIMESTAMP   /* 最后登录时间 */,
    "dept_id" INT   /* 部门ID */
);
CREATE INDEX IF NOT EXISTS "idx_user_created_b19d59" ON "user" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_user_updated_dfdb43" ON "user" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_user_usernam_9987ab" ON "user" ("username");
CREATE INDEX IF NOT EXISTS "idx_user_alias_6f9868" ON "user" ("alias");
CREATE INDEX IF NOT EXISTS "idx_user_email_1b4f1c" ON "user" ("email");
CREATE INDEX IF NOT EXISTS "idx_user_phone_4e3ecc" ON "user" ("phone");
CREATE INDEX IF NOT EXISTS "idx_user_is_acti_83722a" ON "user" ("is_active");
CREATE INDEX IF NOT EXISTS "idx_user_is_supe_b8a218" ON "user" ("is_superuser");
CREATE INDEX IF NOT EXISTS "idx_user_last_lo_af118a" ON "user" ("last_login");
CREATE INDEX IF NOT EXISTS "idx_user_dept_id_d4490b" ON "user" ("dept_id");
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS "role_api" (
    "role_id" BIGINT NOT NULL REFERENCES "role" ("id") ON DELETE CASCADE,
    "api_id" BIGINT NOT NULL REFERENCES "api" ("id") ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS "uidx_role_api_role_id_ba4286" ON "role_api" ("role_id", "api_id");
CREATE TABLE IF NOT EXISTS "role_menu" (
    "role_id" BIGINT NOT NULL REFERENCES "role" ("id") ON DELETE CASCADE,
    "menu_id" BIGINT NOT NULL REFERENCES "menu" ("id") ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS "uidx_role_menu_role_id_90801c" ON "role_menu" ("role_id", "menu_id");
CREATE TABLE IF NOT EXISTS "user_role" (
    "user_id" BIGINT NOT NULL REFERENCES "user" ("id") ON DELETE CASCADE,
    "role_id" BIGINT NOT NULL REFERENCES "role" ("id") ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS "uidx_user_role_user_id_d0bad3" ON "user_role" ("user_id", "role_id");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """
