"""打开浏览器环境 (open_env)"""


def execute_open_env(executor, job: dict, payload: dict) -> dict:
    """打开 HubStudio 浏览器环境（仅启动浏览器，不等待操作）"""
    domain = payload.get("domain", job.get("domain", ""))
    hub_env_id = payload.get("hub_env_id", "")

    if not hub_env_id:
        return {"status": "failed", "error": "hub_env_id is required"}

    executor.logger.info(f"[open_env] 开始: domain={domain}, env_id={hub_env_id}")

    executor.rt.start_connector()
    client = executor.rt.ensure_client()

    executor.logger.info(f"[open_env] 启动浏览器: env_id={hub_env_id}")
    client.start_browser(int(hub_env_id), isHeadless=False, shouldCloseTabsOnOpen=True)

    executor.logger.info(f"[open_env] 完成: domain={domain}")
    return {"status": "success", "domain": domain, "env_id": hub_env_id, "message": "浏览器已启动"}
