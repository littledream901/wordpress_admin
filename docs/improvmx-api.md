# ImprovMX API 参考文档

> 邮件转发服务，管理域名和别名实现邮箱转发
> 接口基础地址: `https://api.improvmx.com/v3`
> 认证方式: HTTP Basic Auth，用户名 `api`，密码为 API Key（在 [Dashboard](https://app.improvmx.com/api) 获取）

---

## 错误码

| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 / 缺少必填参数 |
| 401 | 认证失败（API Key 缺失或无效） |
| 403 | 权限不足（需 Premium 账户） |
| 429 | 请求过于频繁，参考 `Retry-After` 头 |
| 500 | 服务器错误 |

错误响应格式:
```json
{
    "errors": {"email": ["You cannot use your domain in your email."]},
    "success": false
}
```

### 速率限制响应头

| Header | 说明 |
|--------|------|
| `X-RateLimit-Limit` | 当前窗口最大请求数 |
| `X-RateLimit-Remaining` | 当前窗口剩余请求数 |
| `X-RateLimit-Reset` | 窗口重置的 Unix 时间戳（秒） |
| `Retry-After` | 仅 429 时 — 建议等待秒数 |

---

## 账户

### 获取账户信息

```
GET /account
```

**返回:**
```json
{
    "account": {
        "billing_email": null,
        "cancels_on": null,
        "card_brand": "Visa",
        "company_details": "1 Decentralized Street\n92024-2852 California",
        "company_name": "PiedPiper Inc.",
        "company_vat": null,
        "country": "US",
        "created": 1512139382000,
        "email": "richard.hendricks@gmail.com",
        "last4": "1234",
        "limits": {
            "aliases": 10000,
            "daily_quota": 100000,
            "daily_send": 200,
            "domains": 10000,
            "ratelimit": 10,
            "redirections": 50,
            "subdomains": 2,
            "api": 3,
            "credentials": 50,
            "destinations": 5
        },
        "lock_reason": null,
        "locked": null,
        "password": true,
        "plan": {
            "aliases_limit": 10000,
            "daily_quota": 100000,
            "display": "Business - $249",
            "domains_limit": 10000,
            "kind": "enterprise",
            "name": "enterprise249",
            "price": 249,
            "yearly": false
        },
        "premium": true,
        "privacy_level": 1,
        "renew_date": 15881622590000
    },
    "success": true
}
```

### 获取白标域名列表

```
GET /account/whitelabels
```

**返回:**
```json
{
    "whitelabels": [{"name": "piedpiper.com"}],
    "success": true
}
```

---

## 域名

### 列出域名

```
GET /domains
```

**参数:**

| 字段 | 类型 | 位置 | 必填 | 说明 |
|------|------|------|------|------|
| `q` | String | query | 否 | 按子串过滤域名 |
| `is_active` | String | query | 否 | `1` 仅活跃 / `0` 仅不活跃 |
| `limit` | Integer | query | 否 | 每页数量，默认 50，最大 100 |
| `page` | Integer | query | 否 | 页码（从 1 开始），默认 1 |

> 注意: 列表最多返回每个域名下 200 个别名，超过请用 [列出别名](#列出别名) 接口。

**返回:**
```json
{
    "domains": [
        {
            "active": true,
            "domain": "google.com",
            "display": "google.com",
            "dkim_selector": "dkimprovmx",
            "notification_email": null,
            "webhook": null,
            "whitelabel": null,
            "added": 1559639697000,
            "aliases": [
                {
                    "created": 1702393755000,
                    "forward": "sergey@gmail.com",
                    "alias": "sergey",
                    "id": 1
                }
            ]
        }
    ],
    "total": 1,
    "limit": 50,
    "page": 1,
    "success": true
}
```

### 获取单个域名

```
GET /domains/{domain}
```

**路径参数:** `domain` — 域名，如 `piedpiper.com`

**返回:** 同列表中的单个 domain 对象，包裹在 `"domain"` 键下。

---

### 添加域名

```
POST /domains
```

**Body 参数 (JSON):**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `domain` | String | 是 | 域名 |
| `notification_email` | String | 否 | 通知接收邮箱，默认使用账户邮箱 |
| `whitelabel` | String | 否 | DNS 设置中显示的父域名 |

**请求示例:**
```json
{
    "domain": "piedpiper.com"
}
```

**返回:**
```json
{
    "domain": {
        "active": false,
        "domain": "piedpiper.com",
        "display": "piedpiper.com",
        "dkim_selector": "dkimprovmx",
        "notification_email": null,
        "whitelabel": null,
        "added": 1559652806000,
        "aliases": [
            {"forward": "contact@piedpiper.com", "alias": "*", "id": 12}
        ]
    },
    "success": true
}
```

---

### 更新域名

```
PUT /domains/{domain}
```

> 域名名称不可更改。

**Body 参数 (JSON):**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `notification_email` | String | 否 | 通知接收邮箱 |
| `webhook` | String | 否 | 该域名邮件事件的 POST 回调地址 |
| `whitelabel` | String | 否 | 父域名 |

**请求示例:**
```json
{
    "notification_email": "richard.hendricks@gmail.com",
    "webhook": "https://requestbin.com/r/abc123",
    "whitelabel": "hooli.com"
}
```

**返回:** 更新后的 domain 对象。

---

### 验证域名 DNS

```
GET /domains/{domain}/check
```

验证 MX、SPF、DKIM、DMARC 记录是否正确配置。MX 验证通过后服务器开始转发。

**返回:**
```json
{
    "records": {
        "provider": "cloudflare",
        "advanced": true,
        "dkim1": {
            "expected": "dkimprovmx1.improvmx.com.",
            "valid": true,
            "values": "dkimprovmx1.improvmx.com."
        },
        "dkim2": {
            "expected": "dkimprovmx2.improvmx.com.",
            "valid": true,
            "values": "dkimprovmx2.improvmx.com."
        },
        "dmarc": {
            "expected": "v=DMARC1; p=none;",
            "valid": false,
            "values": null
        },
        "error": null,
        "mx": {
            "expected": ["mx1.improvmx.com", "mx2.improvmx.com"],
            "valid": true,
            "values": ["mx2.improvmx.com", "mx1.improvmx.com"]
        },
        "spf": {
            "expected": "v=spf1 include:someservice.org include:spf.improvmx.com ~all",
            "valid": false,
            "values": "v=spf1 include:someservice.org ~all"
        },
        "valid": false
    },
    "success": true
}
```

---

### 删除域名

```
DELETE /domains/{domain}
```

**返回:**
```json
{"success": true}
```

---

## 别名

### 列出别名

```
GET /domains/{domain}/aliases
```

**参数:**

| 字段 | 类型 | 位置 | 必填 | 说明 |
|------|------|------|------|------|
| `q` | String | query | 否 | 按子串过滤别名和转发目标 |
| `alias` | String | query | 否 | 按前缀过滤别名 |
| `limit` | Integer | query | 否 | 每页数量，默认 20，最大 100 |
| `page` | Integer | query | 否 | 页码（从 1 开始），默认 1 |

**返回:**
```json
{
    "aliases": [
        {
            "created": 1702982672000,
            "forward": "richard.hendricks@gmail.com",
            "alias": "richard",
            "id": 4
        }
    ],
    "limit": 20,
    "page": 1,
    "total": 1,
    "success": true
}
```

---

### 获取单个别名

```
GET /domains/{domain}/aliases/{alias}
```

> `alias` 路径参数可以是别名字符串（如 `richard`）或别名 ID（如 `11`）。

**返回:**
```json
{
    "alias": {
        "created": 1702982672000,
        "forward": "richard.hendricks@protonmail.com",
        "alias": "richard",
        "id": 11
    },
    "success": true
}
```

---

### 创建别名

```
POST /domains/{domain}/aliases
```

**Body 参数 (JSON):**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `alias` | String | 是 | 别名本地部分（如 `contact`、`info`） |
| `forward` | String | 是 | 逗号分隔的目标邮箱和/或 webhook 地址 |

**请求示例:**
```json
{
    "alias": "richard",
    "forward": "richard.hendricks@gmail.com"
}
```

**返回:**
```json
{
    "alias": {
        "forward": "richard.hendricks@gmail.com",
        "alias": "richard",
        "id": 11
    },
    "success": true
}
```

---

### 批量创建别名

```
POST /domains/{domain}/aliases/batch
```

**Body 参数 (JSON):**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `aliases` | Array | 是 | 别名对象数组，每个对象包含 `alias` 和 `forward`，最多 500 个 |

> 部分失败不影响整体请求，成功和失败的条目分别返回。

**请求示例:**
```json
{
    "aliases": [
        {"alias": "richard", "forward": "richard.hendricks@gmail.com"},
        {"alias": "jared", "forward": "jared.dunn@gmail.com"}
    ]
}
```

**返回:**
```json
{
    "added": [
        {
            "alias": "richard",
            "forward": "richard.hendricks@gmail.com",
            "id": "12345",
            "created_at": "2026-05-05T11:32:00Z",
            "updated_at": "2026-05-05T11:32:00Z"
        }
    ],
    "failed": []
}
```

---

### 更新别名

```
PUT /domains/{domain}/aliases/{alias}
```

> `alias` 路径参数可以是别名字符串或别名 ID。

**Body 参数 (JSON):**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `forward` | String | 是 | 新的逗号分隔目标邮箱和/或 webhook 地址 |

**请求示例:**
```json
{
    "forward": "richard.hendricks@protonmail.com"
}
```

**返回:** 更新后的 alias 对象。

---

## Python 客户端示例

```python
import requests
from typing import Optional

class ImprovMxClient:
    """ImprovMX API v3 客户端"""

    def __init__(self, api_key: str):
        self.base = "https://api.improvmx.com/v3"
        self.session = requests.Session()
        self.session.auth = ("api", api_key)
        self.session.headers.update({"Content-Type": "application/json"})

    # ---- Account ----

    def get_account(self) -> dict:
        return self._request("GET", "/account")

    def get_whitelabels(self) -> dict:
        return self._request("GET", "/account/whitelabels")

    # ---- Domains ----

    def list_domains(
        self,
        q: str = None,
        is_active: str = None,
        limit: int = 50,
        page: int = 1,
    ) -> dict:
        params = {"limit": limit, "page": page}
        if q:
            params["q"] = q
        if is_active is not None:
            params["is_active"] = is_active
        return self._request("GET", "/domains", params=params)

    def get_domain(self, domain: str) -> dict:
        return self._request("GET", f"/domains/{domain}")

    def add_domain(
        self,
        domain: str,
        notification_email: str = None,
        whitelabel: str = None,
    ) -> dict:
        body = {"domain": domain}
        if notification_email:
            body["notification_email"] = notification_email
        if whitelabel:
            body["whitelabel"] = whitelabel
        return self._request("POST", "/domains", json=body)

    def update_domain(
        self,
        domain: str,
        notification_email: str = None,
        webhook: str = None,
        whitelabel: str = None,
    ) -> dict:
        body = {}
        if notification_email is not None:
            body["notification_email"] = notification_email
        if webhook is not None:
            body["webhook"] = webhook
        if whitelabel is not None:
            body["whitelabel"] = whitelabel
        return self._request("PUT", f"/domains/{domain}", json=body)

    def check_domain(self, domain: str) -> dict:
        return self._request("GET", f"/domains/{domain}/check")

    def delete_domain(self, domain: str) -> dict:
        return self._request("DELETE", f"/domains/{domain}")

    # ---- Aliases ----

    def list_aliases(
        self,
        domain: str,
        q: str = None,
        alias: str = None,
        limit: int = 20,
        page: int = 1,
    ) -> dict:
        params = {"limit": limit, "page": page}
        if q:
            params["q"] = q
        if alias:
            params["alias"] = alias
        return self._request("GET", f"/domains/{domain}/aliases", params=params)

    def get_alias(self, domain: str, alias: str) -> dict:
        return self._request("GET", f"/domains/{domain}/aliases/{alias}")

    def add_alias(self, domain: str, alias: str, forward: str) -> dict:
        body = {"alias": alias, "forward": forward}
        return self._request("POST", f"/domains/{domain}/aliases", json=body)

    def batch_add_aliases(self, domain: str, aliases: list[dict]) -> dict:
        """aliases: [{"alias": "xxx", "forward": "xxx@yyy.com"}, ...] 最多 500 个"""
        return self._request(
            "POST", f"/domains/{domain}/aliases/batch", json={"aliases": aliases}
        )

    def update_alias(self, domain: str, alias: str, forward: str) -> dict:
        return self._request(
            "PUT", f"/domains/{domain}/aliases/{alias}", json={"forward": forward}
        )

    # ---- Internal ----

    def _request(
        self,
        method: str,
        path: str,
        params: dict = None,
        json: dict = None,
    ) -> dict:
        resp = self.session.request(
            method, f"{self.base}{path}", params=params, json=json, timeout=30
        )
        resp.raise_for_status()
        return resp.json()


# 使用示例
if __name__ == "__main__":
    client = ImprovMxClient("your_api_key_here")

    # 获取账户信息
    account = client.get_account()
    print(f"邮箱: {account['account']['email']}")
    print(f"套餐: {account['account']['plan']['display']}")

    # 列出域名
    domains = client.list_domains()
    for d in domains["domains"]:
        print(f"域名: {d['domain']}, 活跃: {d['active']}")

    # 添加域名
    result = client.add_domain("example.com")
    print(f"添加域名: {result}")

    # 添加别名
    alias = client.add_alias("example.com", "hello", "my@gmail.com")
    print(f"添加别名: {alias}")

    # 验证域名 DNS
    check = client.check_domain("example.com")
    print(f"MX 有效: {check['records']['mx']['valid']}")
```
