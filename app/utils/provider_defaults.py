"""Provider 默认配置项定义。

被 init_providers() 和 ConfigProviderController.create() 共用。
"""

from typing import Any, List, Tuple

# 每条: (config_key, default_value, description, config_type, is_secret, is_required)
_ItemDef = Tuple[str, Any, str, str, bool, bool]
# 整个 entry: (provider_type, provider_name, description, priority, [items])
_ProviderDef = Tuple[str, str, str, int, List[_ItemDef]]


def get_default_items(provider_type: str) -> List[_ItemDef]:
    """返回某 Provider 类型的默认配置项列表；未定义的类型返回空列表。"""
    for entry in _PROVIDER_DEFAULTS:
        ptype, _, _, _, items = entry
        if ptype == provider_type:
            return items
    return []


_PROVIDER_DEFAULTS: List[_ProviderDef] = [
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
        ("business_group_name",       "Gmc申请", "HubStudio 业务分组名称（创建环境时匹配 tag）", "string", False, False),
        ("gmc_check_cron",           "",   "GMC 定时巡检 cron 表达式，空=禁用（例: */30 * * * *）", "string", False, False),
        ("gmc_check_cron_statuses",  '["未检测","有违规","已暂停","审核中","未创建","未知"]',
         "GMC 巡检需查询的状态标签（JSON），可选: 未检测/正常/审核中/有违规/已暂停/未创建/未知", "json", False, False),
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
        ("batch_size",                 "10", "批量上传每批产品数", "int", False, False),
        ("enable_images",              "true", "是否上传产品图片到 Woo", "bool", False, False),
        ("max_images_per_product",     "5", "每个产品最大图片数", "int", False, False),
        ("upload_variants",            "false", "是否上传变体产品", "bool", False, False),
        ("check_existing_before_create","true", "创建前按 SKU 查重", "bool", False, False),
    ]),
]
