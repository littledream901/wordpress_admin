"""更新环境：代理配置和备注

代理配置两级优先级：
1. 任务级代理（payload.proxy_config）
   - 来源：站点已分配的 HubStudioProxyConfig 记录
   - 完整代理对象，包含所有必要字段
   - 当站点有绑定代理时，通过 payload.proxy_config 传入

2. 无代理配置
   - 来源：未分配任何代理
   - 不下发代理配置到 HubStudio API
   - 环境使用 Provider 默认代理（需前端确认）

注意：
- 已移除 executor.fixed_proxy_config 兜底逻辑
- 已移除散落字段代理（payload.proxy_type_name 等）构建逻辑
"""

from ._common import build_container_name, build_remark


def build_proxy_config(executor, payload: dict) -> dict:
    """从 payload 构建代理配置

    优先级：
    1. payload.proxy_config — 完整代理对象（从站点绑定的代理配置）
    2. 空 — 不更新代理，使用 HubStudio Provider 默认代理
    """
    proxy_config = payload.get("proxy_config")
    if proxy_config and isinstance(proxy_config, dict) and proxy_config.get("proxyTypeName"):
        return {
            k: v for k, v in proxy_config.items()
            if v is not None and str(v).strip() != ""
        }

    return {}


def execute_update_env(executor, job: dict, payload: dict) -> dict:
    """更新环境：代理配置和备注"""
    domain = payload.get("domain", job.get("domain", ""))
    hub_env_id = payload.get("hub_env_id", "")
    server_ip = payload.get("server_ip", "")
    login_url = payload.get("login_url", "")

    if not hub_env_id:
        return {"status": "failed", "error": "hub_env_id is required"}

    executor.logger.info(f"[update_env] 开始: domain={domain}, env_id={hub_env_id}")
    executor.rt.start_connector()
    client = executor.rt.ensure_client()

    result = {"status": "success", "env_id": hub_env_id, "domain": domain, "actions": {}}

    # ── 更新代理（优先使用已分配代理，未分配时使用 HubStudio Provider 默认代理）──
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
        result["actions"]["proxy"] = "skipped (no assigned proxy, using HubStudio default)"
        executor.logger.info(f"[update_env] 未分配代理，使用 HubStudio 环境默认代理")

    # ── 更新备注 ──
    remark = build_remark(payload)
    if remark:
        try:
            client.update_env_remark(int(hub_env_id), remark)
            result["actions"]["remark"] = "ok"
            result["remark"] = remark
            executor.logger.info(f"[update_env] 备注更新成功: {remark[:100]}")
        except Exception as e:
            result["actions"]["remark"] = f"failed: {str(e)[:100]}"
            executor.logger.warning(f"[update_env] 备注更新失败: {e}")
    else:
        result["actions"]["remark"] = "skipped (empty remark)"
        executor.logger.info(f"[update_env] 备注为空，跳过更新")

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
