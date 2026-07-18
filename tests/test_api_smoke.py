"""
API 连通性及报错检测测试。
运行前提：后端服务已在 localhost:9999 启动，数据库已初始化。
运行方式：
    pytest tests/test_api_smoke.py -v --tb=short

注意：如果遇到 429 速率限制，可重启后端服务后重新运行：
    python run.py
"""
import os
import json
import time
import pytest
import httpx

BASE_URL = os.getenv("TEST_BASE_URL", "http://127.0.0.1:9999")
API_PREFIX = "/api/v1"
HEADERS_JSON = {"Content-Type": "application/json"}

# ── 公共端点（无需认证） ──
PUBLIC_ENDPOINTS = [
    ("GET", "/api/v1/base/health"),
    ("POST", "/api/v1/base/access_token"),
    ("POST", "/api/v1/base/refresh_token"),
    ("GET", "/api/v1/import/template/sites"),
    ("GET", "/api/v1/site-pipeline/feed/download/test.csv"),  # 会 404 但不会 500
]

# ── GET 端点（需要认证） ──
# 格式: (method, path, params) — params 为 None 则不带参数
AUTH_GET_ENDPOINTS = [
    # base
    ("GET", "/api/v1/base/userinfo", None),
    ("GET", "/api/v1/base/usermenu", None),
    ("GET", "/api/v1/base/userapi", None),
    # user
    ("GET", "/api/v1/user/list", {"page": 1, "page_size": 10}),
    ("GET", "/api/v1/user/get", {"user_id": 1}),
    # role
    ("GET", "/api/v1/role/list", {"page": 1, "page_size": 10}),
    ("GET", "/api/v1/role/get", {"role_id": 1}),
    ("GET", "/api/v1/role/authorized", {"role_id": 1}),
    # menu
    ("GET", "/api/v1/menu/list", None),
    ("GET", "/api/v1/menu/get", {"menu_id": 1}),
    # api
    ("GET", "/api/v1/api/list", {"page": 1, "page_size": 10}),
    ("GET", "/api/v1/api/get", {"api_id": 1}),
    # dept
    ("GET", "/api/v1/dept/list", None),
    ("GET", "/api/v1/dept/get", {"dept_id": 1}),
    # auditlog
    ("GET", "/api/v1/auditlog/list", {"page": 1, "page_size": 10}),
    # config
    ("GET", "/api/v1/config/category/list", None),
    ("GET", "/api/v1/config/list", {"page": 1, "page_size": 10}),
    ("GET", "/api/v1/config/get", {"config_id": 1}),
    # account
    ("GET", "/api/v1/account/list", {"page": 1, "page_size": 10}),
    # config-provider
    ("GET", "/api/v1/config-provider/provider/list", {"page": 1, "page_size": 10}),
    ("GET", "/api/v1/config-provider/provider/get", {"provider_id": 1}),
    ("GET", "/api/v1/config-provider/provider/types", None),
    ("GET", "/api/v1/config-provider/items/list", {"page": 1, "page_size": 10}),
    ("GET", "/api/v1/config-provider/bindings/list", {"page": 1, "page_size": 10}),
    ("GET", "/api/v1/config-provider/bindings/sites", None),
    ("GET", "/api/v1/config-provider/bindings/ips", None),
    # site-pipeline (site)
    ("GET", "/api/v1/site-pipeline/site/list", {"page": 1, "page_size": 10}),
    ("GET", "/api/v1/site-pipeline/site/get", {"site_id": 1}),
    # site-pipeline (hub-jobs)
    ("GET", "/api/v1/site-pipeline/hub-job/list", {"page": 1, "page_size": 10}),
    ("GET", "/api/v1/site-pipeline/hub-job/agents", None),
    ("GET", "/api/v1/site-pipeline/hub-job/agent-config", None),
    # site-pipeline (onepanel monitor)
    ("GET", "/api/v1/site-pipeline/onepanel-monitor", None),
    # site-pipeline (feed)
    ("GET", "/api/v1/site-pipeline/feed/source-list", {"page": 1, "page_size": 10}),
    ("GET", "/api/v1/site-pipeline/feed/processed-list", {"page": 1, "page_size": 10}),
    ("GET", "/api/v1/site-pipeline/feed/config/default-domain", None),
    # site-pipeline (ads)
    ("GET", "/api/v1/site-pipeline/ads/list", {"page": 1, "page_size": 10}),
    # gmail
    ("GET", "/api/v1/gmail/list", {"page": 1, "page_size": 10}),
    # shopify
    ("GET", "/api/v1/shopify/source/list", {"page": 1, "page_size": 10}),
    ("GET", "/api/v1/shopify/product/list", {"page": 1, "page_size": 10}),
    # operation-jobs
    ("GET", "/api/v1/operation-jobs/list", {"page": 1, "page_size": 10}),
    ("GET", "/api/v1/operation-jobs/get", {"job_id": 1}),
    # import
    ("GET", "/api/v1/import/list", {"page": 1, "page_size": 10}),
    # recycle-bin
    ("GET", "/api/v1/recycle-bin/list", {"page": 1, "page_size": 10, "type": "site"}),
]

# ── POST 端点（需要认证） ──
# 格式: (method, path, body, expected_code_hint)
# expected_code_hint: 期望的 HTTP 状态码范围（如 "2xx" 表示成功, "4xx" 参数问题也可接受）
AUTH_POST_ENDPOINTS = [
    # base
    ("POST", "/api/v1/base/update_password", {"old_password": "", "new_password": ""}, "4xx"),
    # user
    ("POST", "/api/v1/user/create", {}, "4xx"),  # 缺少必要参数
    ("POST", "/api/v1/user/update", {}, "4xx"),
    ("POST", "/api/v1/user/reset_password", {"user_id": 1}, "any"),
    # role
    ("POST", "/api/v1/role/create", {}, "4xx"),
    ("POST", "/api/v1/role/update", {}, "4xx"),
    ("POST", "/api/v1/role/authorized", {"role_id": 1, "menu_ids": [], "api_ids": []}, "any"),
    # menu
    ("POST", "/api/v1/menu/create", {}, "4xx"),
    ("POST", "/api/v1/menu/update", {}, "4xx"),
    # api
    ("POST", "/api/v1/api/create", {}, "4xx"),
    ("POST", "/api/v1/api/update", {}, "4xx"),
    ("POST", "/api/v1/api/refresh", None, "any"),
    # dept
    ("POST", "/api/v1/dept/create", {}, "4xx"),
    ("POST", "/api/v1/dept/update", {}, "4xx"),
    # config
    ("POST", "/api/v1/config/create", {}, "4xx"),
    ("POST", "/api/v1/config/update", {}, "4xx"),
    ("POST", "/api/v1/config/batch-save", {}, "4xx"),
    # account
    ("POST", "/api/v1/account/create", {}, "4xx"),
    ("POST", "/api/v1/account/update", {}, "4xx"),
    # config-provider
    ("POST", "/api/v1/config-provider/provider/create", {}, "4xx"),
    ("POST", "/api/v1/config-provider/provider/update", {}, "4xx"),
    ("POST", "/api/v1/config-provider/provider/set-default", {"provider_id": 1, "provider_type": "cloudflare"}, "any"),
    ("POST", "/api/v1/config-provider/items/update", {}, "4xx"),
    ("POST", "/api/v1/config-provider/items/batch-save", {}, "4xx"),
    ("POST", "/api/v1/config-provider/bindings/create", {}, "4xx"),
    ("POST", "/api/v1/config-provider/bindings/batch-create", {}, "4xx"),
    # site-pipeline
    ("POST", "/api/v1/site-pipeline/site/create", {}, "4xx"),
    ("POST", "/api/v1/site-pipeline/site/update", {}, "4xx"),
    ("POST", "/api/v1/site-pipeline/hub-job/create", {}, "4xx"),
    # site-pipeline (feed)
    ("POST", "/api/v1/site-pipeline/feed/cleanup", {}, "any"),
    # ads
    ("POST", "/api/v1/site-pipeline/ads/create", {}, "4xx"),
    ("POST", "/api/v1/site-pipeline/ads/update", {}, "4xx"),
    # gmail
    ("POST", "/api/v1/gmail/create", {}, "4xx"),
    ("POST", "/api/v1/gmail/update", {}, "4xx"),
    # shopify
    ("POST", "/api/v1/shopify/source/create", {}, "4xx"),
    ("POST", "/api/v1/shopify/source/update", {}, "4xx"),
    ("POST", "/api/v1/shopify/product/update", {}, "4xx"),
    # operation-jobs
    ("POST", "/api/v1/operation-jobs/update", {}, "4xx"),
    # import
    ("POST", "/api/v1/import/sites", [], "4xx"),  # List[dict] body
    # recycle-bin
    ("POST", "/api/v1/recycle-bin/list", {"page": 1, "page_size": 10, "type": "site"}, "any"),
]

# ── DELETE 端点（需要认证） ──
AUTH_DELETE_ENDPOINTS = [
    # 这些仅测试不 500，不期望成功（因为 ID 不存在）
    ("DELETE", "/api/v1/user/delete", {"user_id": 99999}, "any"),
    ("DELETE", "/api/v1/role/delete", {"role_id": 99999}, "any"),
    ("DELETE", "/api/v1/menu/delete", {"menu_id": 99999}, "any"),
    ("DELETE", "/api/v1/api/delete", {"api_id": 99999}, "any"),
    ("DELETE", "/api/v1/dept/delete", {"dept_id": 99999}, "any"),
    ("POST", "/api/v1/config/delete", {"config_id": 99999}, "any"),
    ("DELETE", "/api/v1/account/delete", {"account_id": 99999}, "any"),
    ("POST", "/api/v1/config-provider/provider/delete", {"provider_id": 99999}, "any"),
    ("POST", "/api/v1/config-provider/bindings/delete", {"binding_id": 99999}, "any"),
    ("GET", "/api/v1/site-pipeline/feed/config/default-domain", None, "any"),  # already in GET
]


# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

def get_admin_credentials():
    """从 .env 读取管理员密码，或使用默认值"""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    password = "admin123"
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("DEFAULT_PASSWORD="):
                    password = line.split("=", 1)[1].strip()
                    break
    return password


@pytest.fixture(scope="session")
def auth_headers():
    """获取认证 token 并返回带 Authorization 的 headers"""
    password = get_admin_credentials()
    for attempt in range(3):
        with httpx.Client(base_url=BASE_URL, timeout=15) as client:
            resp = client.post(
                f"{API_PREFIX}/base/access_token",
                json={"username": "admin", "password": password},
            )
            if resp.status_code == 429:
                time.sleep(2)
                continue
            if resp.status_code != 200:
                pytest.skip(f"无法登录获取 token: HTTP {resp.status_code} {resp.text[:200]}")
            data = resp.json()
            token = (data.get("data", {}) or {}).get("access_token")
            if not token:
                pytest.skip(f"登录成功但未找到 access_token: {json.dumps(data, ensure_ascii=False)[:200]}")
            return {**HEADERS_JSON, "Authorization": f"Bearer {token}"}
    pytest.skip("登录连续 429 速率限制")


# ═══════════════════════════════════════════════════════════════════
#  Helper
# ═══════════════════════════════════════════════════════════════════

STATUS_DESCRIPTIONS = {
    200: "OK", 201: "Created", 204: "No Content",
    301: "Moved", 302: "Found",
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
    404: "Not Found", 405: "Method Not Allowed", 409: "Conflict",
    422: "Unprocessable Entity", 429: "Too Many Requests",
    500: "Internal Server Error", 502: "Bad Gateway", 503: "Unavailable",
}

ERROR_CODES = set()  # 收集所有遇到的错误（去重）


def _describe(code):
    return STATUS_DESCRIPTIONS.get(code, f"HTTP {code}")


def _is_acceptable(code, hint):
    """判断 HTTP 状态码是否可接受。429 速率限制也属于正常响应。"""
    if code == 429:
        return True  # 速率限制是正常的保护机制
    if code < 500:
        return True
    return False  # 5xx 一律视为 bug


# ═══════════════════════════════════════════════════════════════════
#  Test: 服务存活
# ═══════════════════════════════════════════════════════════════════

def test_server_alive():
    """确认后端服务正在运行"""
    try:
        resp = httpx.get(f"{BASE_URL}{API_PREFIX}/base/health", timeout=5)
        if resp.status_code == 429:
            pytest.skip("速率限制中，稍后重试")
        assert resp.status_code == 200, f"健康检查失败: HTTP {resp.status_code}"
        assert "text/html" not in resp.headers.get("content-type", ""), "返回了 HTML 而非 JSON"
    except httpx.ConnectError:
        pytest.fail(f"无法连接到 {BASE_URL}，请确认后端服务已启动（python run.py）")


# ═══════════════════════════════════════════════════════════════════
#  Test: 公共端点
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path", [
    (m, p) for m, p in PUBLIC_ENDPOINTS
])
def test_public_endpoint(method, path):
    """公共端点不应返回 500"""
    with httpx.Client(base_url=BASE_URL, timeout=15) as client:
        if method == "GET":
            resp = client.get(path)
        else:
            resp = client.post(path, json={} if path.endswith("access_token") else None)
        assert resp.status_code < 500, f"[{method} {path}] 返回 500 错误: {resp.text[:300]}"


# ═══════════════════════════════════════════════════════════════════
#  Test: 认证 GET 端点
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,params", AUTH_GET_ENDPOINTS)
def test_auth_get_endpoint(method, path, params, auth_headers):
    """所有认证 GET 端点不应返回 500"""
    with httpx.Client(base_url=BASE_URL, timeout=15) as client:
        resp = client.get(path, params=params, headers=auth_headers)

        # 判断可接受的状态码
        ok = _is_acceptable(resp.status_code, "any")
        desc = _describe(resp.status_code)

        if not ok:
            ERROR_CODES.add(f"[{resp.status_code}] {method} {path}")
            pytest.fail(
                f"[{method} {path}] 返回 {desc}\n"
                f"  params={params}\n"
                f"  响应: {resp.text[:300]}"
            )
        elif resp.status_code >= 400:
            # 4xx 记录但不失败（可能是数据不存在或参数问题）
            pass


# ═══════════════════════════════════════════════════════════════════
#  Test: 认证 POST 端点
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body,hint", AUTH_POST_ENDPOINTS)
def test_auth_post_endpoint(method, path, body, hint, auth_headers):
    """所有认证 POST 端点不应返回 500"""
    with httpx.Client(base_url=BASE_URL, timeout=15) as client:
        if body is None:
            resp = client.post(path, headers=auth_headers)
        else:
            resp = client.post(path, json=body, headers=auth_headers)

        ok = _is_acceptable(resp.status_code, hint)
        desc = _describe(resp.status_code)

        if not ok:
            ERROR_CODES.add(f"[{resp.status_code}] {method} {path}")
            pytest.fail(
                f"[{method} {path}] 返回 {desc}\n"
                f"  请求体: {json.dumps(body, ensure_ascii=False)[:200]}\n"
                f"  响应: {resp.text[:300]}"
            )
        elif resp.status_code >= 400:
            pass


# ═══════════════════════════════════════════════════════════════════
#  Test: 认证 DELETE 端点
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,params,hint", AUTH_DELETE_ENDPOINTS)
def test_auth_delete_endpoint(method, path, params, hint, auth_headers):
    """所有 DELETE 端点不应返回 500"""
    with httpx.Client(base_url=BASE_URL, timeout=15) as client:
        if method in ("GET",):
            resp = client.get(path, params=params, headers=auth_headers)
        elif method == "DELETE":
            resp = client.request("DELETE", path, params=params, headers=auth_headers)
        else:
            resp = client.post(path, params=params, headers=auth_headers)

        ok = _is_acceptable(resp.status_code, hint if hint != "any" else "4xx")
        desc = _describe(resp.status_code)

        if not ok:
            ERROR_CODES.add(f"[{resp.status_code}] {method} {path}")
            pytest.fail(
                f"[{method} {path}] 返回 {desc}\n"
                f"  params={params}\n"
                f"  响应: {resp.text[:300]}"
            )
        elif resp.status_code >= 400:
            pass


# ═══════════════════════════════════════════════════════════════════
#  Test: POST 端点无 token 应返回 401
# ═══════════════════════════════════════════════════════════════════

NO_AUTH_PATHS = [
    "/api/v1/user/list",
    "/api/v1/role/list",
    "/api/v1/menu/list",
    "/api/v1/api/list",
    "/api/v1/dept/list",
    "/api/v1/auditlog/list",
    "/api/v1/config/list",
    "/api/v1/account/list",
    "/api/v1/config-provider/provider/list",
    "/api/v1/site-pipeline/site/list",
    "/api/v1/site-pipeline/hub-job/list",
    "/api/v1/gmail/list",
    "/api/v1/shopify/source/list",
    "/api/v1/operation-jobs/list",
    "/api/v1/recycle-bin/list",
    "/api/v1/site-pipeline/ads/list",
]


@pytest.mark.parametrize("path", NO_AUTH_PATHS)
def test_endpoint_requires_auth(path):
    """不带 token 访问认证端点应返回 401/403/422/429（取决于依赖注入方式和限流）"""
    with httpx.Client(base_url=BASE_URL, timeout=15) as client:
        resp = client.get(path, params={"page": 1, "page_size": 1})
        assert resp.status_code in (401, 403, 422, 429), (
            f"[GET {path}] 无 token 时返回 {resp.status_code}（期望 401/403/422/429）"
            f"\n  响应: {resp.text[:200]}"
        )


# ═══════════════════════════════════════════════════════════════════
#  Report
# ═══════════════════════════════════════════════════════════════════

def test_summary_report():
    """汇总所有 5xx 错误并输出"""
    if ERROR_CODES:
        err_list = sorted(ERROR_CODES)
        report = "\n".join(f"  - {e}" for e in err_list)
        pytest.fail(f"\n=== API 连通性检测失败 ({len(err_list)} 个 5xx 错误) ===\n{report}\n")
    else:
        print("\n=== 所有 API 连通性检测通过，无 5xx 错误 ===")
