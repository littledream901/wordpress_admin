"""GMC 状态检查 (gmc_check)"""

import time

from app.core.exceptions import HubStudioError


def execute_gmc_check(executor, job: dict, payload: dict) -> dict:
    """查询 GMC (Google Merchant Center) 账号/商品状态"""
    domain = payload.get("domain", job.get("domain", ""))
    hub_env_id = payload.get("hub_env_id", "")

    if not hub_env_id:
        return {"status": "failed", "error": "hub_env_id is required"}

    executor.logger.info(f"[gmc_check] 开始: domain={domain}, env_id={hub_env_id}")

    if not executor.rt.is_port_open():
        executor.logger.warning("[gmc_check] Connector 端口不可达，尝试启动...")
        executor.rt.start_connector()

    client = executor.rt.ensure_client()
    result = {"status": "success", "domain": domain, "actions": {}}

    try:
        # ── 启动浏览器 ──
        resp = client.start_browser(
            int(hub_env_id), isHeadless=False,
            shouldCloseTabsOnOpen=False,
            skipSystemResourceCheck=True,
        )
        debug_port = resp.get("data", {}).get("debuggingPort")
        if not debug_port:
            raise HubStudioError("start browser", detail="未获取到 debuggingPort")
        executor.logger.info(f"[gmc_check] 浏览器已启动: port={debug_port}")
        result["debug_port"] = debug_port

        # ── DrissionPage 自动化 ──
        try:
            from DrissionPage import Chromium
        except ImportError:
            executor.logger.warning("[gmc_check] DrissionPage 未安装，跳过页面自动化")
            result["actions"]["browser"] = "started (no automation)"
            return result

        browser = Chromium(addr_or_opts=f"http://127.0.0.1:{debug_port}")

        # ── GMC 状态查询 ──
        executor.logger.info(f"[gmc_check] 打开 GMC: https://merchants.google.com/")
        try:
            gmc_result = _query_gmc_status(browser, executor)
            result["actions"]["gmc"] = gmc_result
            result["gmc_status"] = gmc_result.get("status", "unknown")
            result["gmc_data"] = gmc_result
            executor.logger.info(f"[gmc_check] GMC 查询完成: {gmc_result.get('status')}")
        except Exception as e:
            result["actions"]["gmc"] = f"error: {str(e)[:200]}"
            result["gmc_status"] = "query_failed"
            result["gmc_data"] = {"status": "query_failed", "error": str(e)[:200]}
            executor.logger.error(f"[gmc_check] GMC 查询异常: {e}")

        result["url"] = "https://merchants.google.com/"
        executor.logger.info(f"[gmc_check] 完成: {result['actions']}")
        return result

    except Exception as e:
        executor.logger.error(f"[gmc_check] 失败: {e}")
        return {"status": "failed", "error": str(e), "domain": domain}


def _query_gmc_status(browser, executor) -> dict:
    """通过 DrissionPage 接管浏览器，打开 GMC 页面查询状态"""
    result = {
        "status": "unknown",
        "account_status": "",
        "product_status": "",
        "issues": [],
        "feed_status": "",
        "raw_text": "",
    }

    gmc_url = "https://merchants.google.com/"
    tab_gmc = None

    try:
        for t in browser.tabs:
            try:
                url = t.url or ""
                if "merchants.google.com" in url:
                    tab_gmc = t
                    executor.logger.info(f"[GMC] 复用已有 tab: {url[:80]}")
                    break
            except Exception:
                pass
    except Exception:
        pass

    if not tab_gmc:
        tab_gmc = browser.new_tab(gmc_url)
        executor.logger.info(f"[GMC] 新建 tab: {gmc_url}")

    time.sleep(5)

    try:
        result["raw_text"] = (tab_gmc.html or "")[:3000]
    except Exception:
        pass

    # ── 查询账号状态 ──
    account_status_selectors = [
        ('text:已批准', '已批准'), ('text:Approved', '已批准'),
        ('text:已暂停', '已暂停'), ('text:Suspended', '已暂停'),
        ('text:审核中', '审核中'), ('text:Under review', '审核中'),
        ('text:待验证', '待验证'), ('text:Pending verification', '待验证'),
        ('text:需要操作', '需要操作'), ('text:Action required', '需要操作'),
        ('text:未批准', '未批准'), ('text:Disapproved', '未批准'),
    ]
    for sel, label in account_status_selectors:
        try:
            el = tab_gmc.ele(sel, timeout=2)
            if el:
                result["account_status"] = label
                executor.logger.info(f"[GMC] 账号状态: {label}")
                break
        except Exception:
            continue

    # ── 查询商品状态 ──
    product_indicators = [
        ('text:有效', '有效'), ('text:Active', '有效'),
        ('text:被拒', '被拒'), ('text:Disapproved', '被拒'),
        ('text:待审核', '待审核'), ('text:Pending', '待审核'),
        ('text:即将到期', '即将到期'), ('text:Expiring', '即将到期'),
        ('text:已过期', '已过期'), ('text:Expired', '已过期'),
    ]
    for sel, label in product_indicators:
        try:
            el = tab_gmc.ele(sel, timeout=2)
            if el and el.text:
                result["product_status"] = label
                executor.logger.info(f"[GMC] 商品状态: {label}")
                break
        except Exception:
            continue

    # ── 查询问题/告警 ──
    issue_selectors = [
        'div[role="alert"]',
        '[class*="error" i]', '[class*="warning" i]',
        '[class*="issue" i]', '[class*="alert" i]',
        '[class*="notification" i]',
    ]
    for sel in issue_selectors:
        try:
            els = tab_gmc.eles(sel, timeout=2)
            for el in els:
                txt = (el.text or "").strip()
                if txt and len(txt) > 5 and txt not in [i["message"] for i in result["issues"]]:
                    result["issues"].append({"type": "warning", "message": txt[:200]})
        except Exception:
            continue

    # ── 查询 Feed 状态 ──
    for sel, _ in [('text:Feed', None), ('text:feed', None)]:
        try:
            el = tab_gmc.ele(sel, timeout=2)
            if el:
                parent_text = ""
                try:
                    parent = el.parent(2)
                    if parent:
                        parent_text = (parent.text or "")[:200]
                except Exception:
                    pass
                result["feed_status"] = parent_text or (el.text or "")[:100]
                break
        except Exception:
            continue

    # ── 综合判定 status ──
    if result["account_status"] in ("已暂停", "未批准"):
        result["status"] = "suspended"
    elif result["account_status"] in ("审核中", "待验证"):
        result["status"] = "pending"
    elif result["issues"]:
        result["status"] = "warning"
    elif result["account_status"] in ("已批准",):
        result["status"] = "active"
    else:
        result["status"] = "unknown"

    return result
