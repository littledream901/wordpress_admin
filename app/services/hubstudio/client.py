"""HubStudio Connector API 客户端"""

import requests


class HubStudioAPIError(Exception):
    """HubStudio 接口业务异常"""
    pass


class HubStudioClient:
    """HubStudio Connector API 客户端（同步，供 Agent 本地调用）"""

    def __init__(self, base_url: str = "http://localhost:6873", timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def request(self, method: str, path: str, json_data=None, params=None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.request(
                method.upper(), url, json=json_data, params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, OSError) as exc:
            raise HubStudioAPIError(f"HTTP error: {exc}") from exc
        if data.get("code") != 0:
            raise HubStudioAPIError(f"code:{data.get('code')}, msg:{data.get('msg')}")
        return data

    def post(self, path: str, payload: dict) -> dict:
        return self.request("POST", path, json_data=payload)

    # ── 分组管理 ──
    def get_group_list(self) -> dict:
        return self.post("/api/v1/group/list", {})

    # ── 环境管理 ──
    def create_env(self, **kwargs) -> dict:
        return self.post("/api/v1/env/create", kwargs)

    def get_env_list(self, current: int = 1, size: int = 200, tagCode=None, **kwargs) -> dict:
        payload = {"current": current, "size": size}
        if tagCode is not None:
            payload["tagCode"] = str(tagCode)
        payload.update(kwargs)
        return self.post("/api/v1/env/list", payload)

    def update_env(self, containerCode: int, containerName: str, **kwargs) -> dict:
        payload = {"containerCode": containerCode, "containerName": containerName}
        payload.update(kwargs)
        return self.post("/api/v1/env/update", payload)

    def update_env_proxy(self, containerCode: int, **kwargs) -> dict:
        payload = {"containerCode": containerCode}
        payload.update(kwargs)
        return self.post("/api/v1/env/proxy/update", payload)

    def delete_envs(self, containerCodes: list) -> dict:
        return self.post("/api/v1/env/del", {"containerCodes": [int(c) for c in containerCodes]})

    # ── 账号管理 ──
    def add_container_account(self, **kwargs) -> dict:
        return self.post("/api/v1/container/add-account", kwargs)

    def get_account_list(self, **kwargs) -> dict:
        """查询账号列表，常用参数: containerCode, current, size"""
        return self.post("/api/v1/account/list", kwargs)

    def delete_accounts(self, accountIds: list) -> dict:
        """删除账号，accountIds 必须至少包含一个账号 ID"""
        return self.post("/api/v1/account/del", {"accountIds": [int(a) for a in accountIds]})

    # ── 浏览器控制 ──
    def start_browser(self, containerCode: int, isHeadless: bool = False, **kwargs) -> dict:
        payload = {"containerCode": str(containerCode), "isHeadless": isHeadless,
                   "isWebDriverReadOnlyMode": False}
        payload.update(kwargs)
        return self.post("/api/v1/browser/start", payload)

    def stop_browser(self, containerCode: int) -> dict:
        return self.post("/api/v1/browser/stop", {"containerCode": str(containerCode)})

    def stop_all_browsers(self, clearOpening: bool = True) -> dict:
        return self.post("/api/v1/browser/stop-all", {"clearOpening": clearOpening})
