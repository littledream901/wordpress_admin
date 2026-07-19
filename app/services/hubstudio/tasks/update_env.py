"""更新环境：备注 + 代理 (update_env)"""


# ── 备注来源字段 ──
REMARK_FIELD_MAP = [
    ("Address", "ShippingAddress_1"),
    ("City", "City"),
    ("State", "Province/State"),
    ("Zip", "Zip_code"),
    ("Country", "Country"),
    ("Email", "Recovery_Email"),
]

# ── 默认固定代理配置 ──
DEFAULT_FIXED_PROXY_CONFIG = {
    "proxyTypeName": "HTTP",
    "asDynamicType": 1,
    "proxyHost": "server.iphtml.biz",
    "proxyPort": 15000,
    "proxyAccount": "uid-27498-zone-hubstudio",
    "proxyPassword": "",
    "referenceCountryCode": "US",
    "referenceCity": "New York",
    "referenceProvince": "CA",
    "ipGetRuleType": 1,
}

# ── 代理字段映射 ──
PROXY_FIELD_MAP = {
    "proxyTypeName": "proxy_type_name",
    "asDynamicType": "as_dynamic_type",
    "proxyIp": "proxy_ip",
    "proxyHost": "proxy_host",
    "proxyPort": "proxy_port",
    "proxyUser": "proxy_user",
    "proxyAccount": "proxy_account",
    "proxyPassword": "proxy_password",
    "proxyPwd": "proxy_pwd",
    "referenceCountryCode": "proxy_country_code",
    "proxyCountry": "proxy_country",
    "referenceProvince": "proxy_province",
    "referenceCity": "proxy_city",
    "ipGetRuleType": "ip_get_rule_type",
    "linkCode": "link_code",
}


def build_remark(payload: dict) -> str:
    """构建环境备注文本"""
    remark_fields = payload.get("remark_fields", {})
    if not remark_fields:
        return ""

    parts = []
    for _label, field_key in REMARK_FIELD_MAP:
        val = remark_fields.get(field_key, "")
        if val:
            val_str = str(val).strip()
            if val_str:
                parts.append(val_str)

    return " , ".join(parts) if parts else ""


def build_proxy_config(executor, payload: dict) -> dict:
    """从 payload 构建代理配置

    优先级：
    1. payload.proxy_config — 任务级完整代理对象（最高）
    2. payload.proxy_type_name 等散落字段 — 任务级逐字段
    3. executor.fixed_proxy_config — 执行器级固定代理
    4. 空 — 不更新代理
    """
    # 方式 1: 完整 proxy_config 对象优先
    proxy_config = payload.get("proxy_config")
    if proxy_config and isinstance(proxy_config, dict) and proxy_config.get("proxyTypeName"):
        return {
            k: v for k, v in proxy_config.items()
            if v is not None and str(v).strip() != ""
        }

    # 方式 2: 从散落字段构建
    config = {}
    for api_key, payload_key in PROXY_FIELD_MAP.items():
        val = payload.get(payload_key)
        if val is not None and str(val).strip() != "":
            config[api_key] = str(val).strip()

    if config.get("proxyTypeName") and config["proxyTypeName"] != "不使用代理":
        return config

    # 方式 3: 使用执行器级固定代理
    if executor.use_fixed_proxy and executor.fixed_proxy_config:
        config = {
            k: v for k, v in executor.fixed_proxy_config.items()
            if v is not None and str(v).strip() != ""
        }
        if config.get("proxyTypeName") and config["proxyTypeName"] != "不使用代理":
            executor.logger.info(f"[update_env] 使用固定代理: type={config.get('proxyTypeName')}, "
                               f"host={config.get('proxyHost')}")
            return config

    return {}


def execute_update_env(executor, job: dict, payload: dict) -> dict:
    """更新环境：备注信息 + 代理配置"""
    domain = payload.get("domain", job.get("domain", ""))
    hub_env_id = payload.get("hub_env_id", "")
    server_ip = payload.get("server_ip", "")
    login_url = payload.get("login_url", "")

    if not hub_env_id:
        return {"status": "failed", "error": "hub_env_id is required"}

    executor.logger.info(f"[update_env] 开始: domain={domain}, env_id={hub_env_id}")
    executor.rt.start_connector()
    client = executor.rt.ensure_client()

    from .create_env import build_container_name

    result = {"status": "success", "env_id": hub_env_id, "domain": domain, "actions": {}}

    # ── 步骤 1：更新容器名称 + 备注 ──
    container_name = build_container_name(domain)
    remark = build_remark(payload)

    try:
        update_params = {
            "containerCode": int(hub_env_id),
            "containerName": container_name,
            "remark": remark,
        }

        resp = client.update_env(**update_params)
        result["actions"]["remark"] = "ok"
        executor.logger.info(f"[update_env] 容器名称+备注更新成功: remark={remark}")
    except Exception as e:
        result["actions"]["remark"] = f"failed: {str(e)[:100]}"
        executor.logger.warning(f"[update_env] 容器名称更新失败: {e}")

    # ── 步骤 2：更新代理 ──
    proxy_config = build_proxy_config(executor, payload)
    if proxy_config and proxy_config.get("proxyTypeName", "不使用代理") != "不使用代理":
        try:
            proxy_resp = client.update_env_proxy(int(hub_env_id), **proxy_config)
            result["actions"]["proxy"] = "ok"
            result["proxy_config"] = proxy_config
            executor.logger.info(f"[update_env] 代理更新成功: type={proxy_config.get('proxyTypeName')}")
        except Exception as e:
            result["actions"]["proxy"] = f"failed: {str(e)[:100]}"
            executor.logger.warning(f"[update_env] 代理更新失败: {e}")
    else:
        result["actions"]["proxy"] = "skipped (no proxy config)"
        executor.logger.info(f"[update_env] 无代理配置，跳过")

    # 判断整体结果
    actions_ok = sum(1 for v in result["actions"].values() if v == "ok")
    actions_failed = sum(1 for v in result["actions"].values() if v.startswith("failed"))
    if actions_failed > 0 and actions_ok == 0:
        result["status"] = "failed"
        result["error"] = "; ".join(
            v for v in result["actions"].values() if v.startswith("failed")
        )

    executor.logger.info(f"[update_env] 完成: {result['actions']}")
    return result
