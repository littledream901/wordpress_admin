"""创建账号 (create_account)

参考 hubstudio_s3_create_account.py：
 - 必须使用 http.client 直连 add-account 接口（Connector 自动启动时该接口不可用）
 - 先创建 Gmail 主账号，再创建 WordPress 后台账号
 - 带指数退避重试
"""

import http.client
import json
import socket
import time

from app.core.exceptions import HubStudioError


# 账号添加接口常量
ADD_ACCOUNT_HOST = "127.0.0.1"
ADD_ACCOUNT_PORT = 6873
ADD_ACCOUNT_PATH = "/api/v1/container/add-account"
ADD_ACCOUNT_TIMEOUT = 30


def is_retryable_error(error: Exception) -> bool:
    """判断错误是否可重试（网络/限流/5xx 可重试，参数错误不重试）"""
    err_msg = str(error).lower()
    non_retryable = [
        "无效的api接口", "参数错误", "参数非法", "缺少必填",
        "账号已存在", "容器不存在", "环境不存在", "不存在",
        "无权访问", "权限不足", "格式错误",
    ]
    for kw in non_retryable:
        if kw in err_msg:
            return False
    retryable = [
        "timeout", "timed out", "连接超时", "连接失败",
        "connection refused", "connection reset", "e010205",
        "请求太频繁", "限流", "服务器内部错误", "internal server error",
        "bad gateway", "service unavailable", "502", "503", "504",
        "繁忙", "稍后再试",
    ]
    for kw in retryable:
        if kw in err_msg:
            return True
    if isinstance(error, (socket.timeout, ConnectionError, TimeoutError,
                           http.client.HTTPException, OSError)):
        return True
    return False


def calc_backoff(attempt: int, base: float = 2.0, max_delay: float = 20.0) -> float:
    """指数退避 + 随机抖动"""
    delay = min(max_delay, base * (2 ** (attempt - 1)))
    jitter = 0.8 + 0.4 * (hash(str(time.time())) % 100 / 100)
    return delay * jitter


def call_add_account_direct(executor, create_data: dict, max_retries: int = 5) -> dict:
    """使用 http.client 直连 add-account 接口，带重试"""
    last_err = None
    for attempt in range(1, max_retries + 1):
        conn = None
        try:
            conn = http.client.HTTPConnection(
                ADD_ACCOUNT_HOST, ADD_ACCOUNT_PORT,
                timeout=ADD_ACCOUNT_TIMEOUT,
            )
            headers = {
                "Accept-Language": "zh-CN",
                "Authorization": "NULL",
                "Content-Type": "application/json; charset=utf-8",
            }
            body = json.dumps(create_data, ensure_ascii=False).encode("utf-8")
            conn.request("POST", ADD_ACCOUNT_PATH, body=body, headers=headers)
            res = conn.getresponse()
            raw_data = res.read().decode("utf-8")

            try:
                resp_json = json.loads(raw_data)
            except json.JSONDecodeError as json_err:
                raise HubStudioError(
                    "add account", detail=f"接口返回非JSON: status={res.status}"
                ) from json_err

            if res.status < 200 or res.status >= 300:
                raise HubStudioError("add account", detail=f"HTTP失败: status={res.status}")

            if resp_json.get("code") == 0:
                time.sleep(1.2)
                return resp_json

            raise HubStudioError("add account", detail=f"业务失败: code={resp_json.get('code')}, msg={resp_json.get('msg', '')}")

        except Exception as e:
            last_err = e
            if attempt < max_retries and is_retryable_error(e):
                delay = calc_backoff(attempt)
                executor.logger.warning(
                    f"[create_account] add-account 第{attempt}次失败，"
                    f"{round(delay,1)}秒后重试: {str(e)[:120]}"
                )
                time.sleep(delay)
                continue
            raise
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    raise HubStudioError("add account", detail=f"多次重试失败，最后错误：{last_err}")


def execute_create_account(executor, job: dict, payload: dict) -> dict:
    domain = payload.get("domain", job.get("domain", ""))
    hub_env_id = payload.get("hub_env_id", "")
    login_url = payload.get("login_url", "")
    gmail_username = payload.get("gmail_username", "")
    gmail_password = payload.get("gmail_password", "")
    gmail_2fa_key = payload.get("gmail_2fa_key", "")

    if not hub_env_id:
        return {"status": "failed", "error": "hub_env_id is required"}

    executor.logger.info(
        f"[create_account] 开始: domain={domain}, env_id={hub_env_id}, "
        f"gmail={gmail_username or '(无)'}, login_url={login_url or '(无)'}"
    )

    if not executor.rt.is_port_open():
        executor.logger.warning("[create_account] Connector 端口不可达，尝试启动...")
        executor.rt.start_connector()

    results = {}
    env_id_int = int(hub_env_id)

    # ── 1. 创建 Gmail 主账号 ──
    if gmail_username and gmail_password:
        gmail_data = {
            "containerCode": env_id_int,
            "accountName": gmail_username,
            "accountPassword": gmail_password,
            "siteName": "Gmail",
            "name": "gmc",
        }
        if gmail_2fa_key:
            gmail_data["otpSecret"] = gmail_2fa_key

        executor.logger.info(f"[create_account] 创建 Gmail 账号: {gmail_username}")
        try:
            resp = call_add_account_direct(executor, gmail_data)
            results["gmail_account"] = {"ok": True, "resp": resp}
            executor.logger.info(f"[create_account] Gmail 账号创建成功")
            time.sleep(1.0)
        except Exception as e:
            err_msg = str(e)
            if "账号已存在" in err_msg:
                results["gmail_account"] = {"ok": True, "resp": {}, "existed": True}
                executor.logger.info(f"[create_account] Gmail 账号已存在（HubStudio 中已创建）: {gmail_username}")
            elif "无效的API接口" in err_msg or "add-account" in err_msg:
                executor.logger.warning("[create_account] add-account 直连不可用，回退到 httpx 客户端")
                try:
                    client = executor.rt.ensure_client()
                    resp = client.add_container_account(**gmail_data)
                    results["gmail_account"] = {"ok": True, "resp": resp, "fallback": True}
                    executor.logger.info(f"[create_account] Gmail 账号创建成功（httpx 客户端）")
                    time.sleep(1.0)
                except Exception as e2:
                    results["gmail_account"] = {"ok": False, "error": str(e2)}
                    executor.logger.warning(f"[create_account] Gmail 账号创建失败: {e2}")
            elif is_retryable_error(e):
                results["gmail_account"] = {"ok": False, "error": str(e)[:200]}
                executor.logger.error(f"[create_account] Gmail 账号创建失败（可重试）: {e}")
            else:
                results["gmail_account"] = {"ok": False, "error": str(e)[:200]}
                executor.logger.error(f"[create_account] Gmail 账号创建失败: {e}")
    else:
        executor.logger.warning("[create_account] 无 Gmail 凭证，跳过 Gmail 账号创建")

    # ── 2. 创建 WordPress 后台管理员账号 ──
    if login_url:
        admin_data = {
            "containerCode": env_id_int,
            "accountName": executor.admin_account_name,
            "accountPassword": executor.admin_account_password,
            "siteName": executor.admin_site_name,
            "domainName": login_url,
            "siteAlias": executor.admin_site_alias,
            "name": executor.admin_account_name,
        }
        executor.logger.info(f"[create_account] 创建后台账号: admin -> {login_url}")
        try:
            resp = call_add_account_direct(executor, admin_data, max_retries=3)
            results["admin_account"] = {"ok": True, "resp": resp}
            executor.logger.info(f"[create_account] 后台账号创建成功")
        except Exception as e:
            err_msg = str(e)
            if "账号已存在" in err_msg:
                results["admin_account"] = {"ok": True, "resp": {}, "existed": True}
                executor.logger.info(f"[create_account] 后台账号已存在（HubStudio 中已创建）: admin -> {login_url}")
            elif "无效的API接口" in err_msg or "add-account" in err_msg:
                executor.logger.warning("[create_account] add-account 不可用，回退到旧接口")
                try:
                    client = executor.rt.ensure_client()
                    resp = client.add_container_account(**admin_data)
                    results["admin_account"] = {"ok": True, "resp": resp, "fallback": True}
                    executor.logger.info(f"[create_account] 后台账号创建成功（旧接口）")
                except Exception as e2:
                    results["admin_account"] = {"ok": False, "error": str(e2)}
                    executor.logger.warning(f"[create_account] 后台账号创建失败: {e2}")
            else:
                results["admin_account"] = {"ok": False, "error": str(e)[:200]}
                executor.logger.error(f"[create_account] 后台账号创建失败: {e}")
    else:
        executor.logger.info("[create_account] 无 login_url，使用 add-account 直连创建基础账号")
        try:
            admin_data = {
                "containerCode": env_id_int,
                "accountName": executor.admin_account_name,
                "accountPassword": executor.admin_account_password,
                "siteName": executor.admin_site_name,
                "name": executor.admin_account_name,
            }
            resp = call_add_account_direct(executor, admin_data, max_retries=3)
            results["account"] = {"ok": True, "resp": resp}
            executor.logger.info(f"[create_account] 基础账号创建成功")
        except Exception as e:
            err_msg = str(e)
            if "账号已存在" in err_msg:
                results["account"] = {"ok": True, "resp": {}, "existed": True}
                executor.logger.info(f"[create_account] 基础账号已存在（HubStudio 中已创建）")
            else:
                results["account"] = {"ok": False, "error": str(e)[:200]}
                executor.logger.error(f"[create_account] 基础账号创建失败: {e}")

    # ── 3. 写备注 ──
    remark_fields = payload.get("remark_fields", {})
    if remark_fields and any(v for v in remark_fields.values()):
        from .create_env import build_remark, build_container_name

        remark_text = build_remark(payload)
        if remark_text:
            container_name = build_container_name(domain)
            executor.logger.info(f"[create_account] 写备注: {remark_text[:80]}...")
            try:
                client = executor.rt.ensure_client()
                client.update_env(
                    containerCode=env_id_int,
                    containerName=container_name,
                    remark=remark_text,
                )
                results["remark"] = "ok"
                executor.logger.info(f"[create_account] 备注写入成功")
            except Exception as e:
                results["remark"] = f"failed: {str(e)[:100]}"
                executor.logger.warning(f"[create_account] 备注写入失败: {e}")

    # ── 汇总结果 ──
    task_results = {k: v for k, v in results.items() if isinstance(v, dict)}
    ok_count = sum(1 for v in task_results.values() if v.get("ok"))
    fail_count = len(task_results) - ok_count

    if fail_count == 0:
        status = "success"
    elif ok_count == 0:
        status = "failed"
    else:
        status = "partial"

    # 提取所有失败的错误信息
    errors = []
    for key, val in task_results.items():
        if not val.get("ok"):
            errors.append(f"[{key}] {val.get('error', '未知错误')}")

    summary = f"{ok_count}/{len(task_results)} 成功" + (f", {fail_count} 失败" if fail_count else "")

    # 从成功响应的 data 中提取 account_id（HubStudio API: {code:0, data:{id:...}}）
    account_id = ""
    for _key, val in task_results.items():
        if val.get("ok"):
            resp = val.get("resp", {})
            data = resp.get("data", {}) if isinstance(resp, dict) else {}
            aid = data.get("id") or data.get("accountId") or data.get("account_id")
            if aid:
                account_id = str(aid)
                executor.logger.info(f"[create_account] 提取到 account_id={account_id} (来自 {_key})")
                break

    executor.logger.info(
        f"[create_account] 完成: status={status}, {summary}"
        + (f", errors={errors}" if errors else "")
    )
    return {
        "status": status,
        "summary": summary,
        "account_id": account_id,
        "domain": domain,
        "errors": errors,
        "results": results,
    }
