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
        try:
            # ── GMC 状态查询 ──
            executor.logger.info(f"[gmc_check] 打开 GMC: https://merchants.google.com/")
            try:
                gmc_result = _query_gmc_status(browser, executor)
                result["gmc_status"] = gmc_result.get("status", "unknown")
                result["gmc_data"] = gmc_result
                executor.logger.info(f"[gmc_check] GMC 查询完成: {gmc_result.get('status')}")
            except Exception as e:
                result["gmc_status"] = "query_failed"
                result["gmc_data"] = {"status": "query_failed", "error": str(e)[:200]}
                executor.logger.error(f"[gmc_check] GMC 查询异常: {e}")

            result["url"] = "https://merchants.google.com/"
            executor.logger.info(f"[gmc_check] 完成: {result['actions']}")
            return result
        finally:
            browser.quit()

    except Exception as e:
        executor.logger.error(f"[gmc_check] 失败: {e}")
        return {"status": "failed", "error": str(e), "domain": domain}


def _query_gmc_status(browser, executor) -> dict:
    """通过 DrissionPage 接管浏览器，打开 GMC 页面查询状态

    目标页面: https://merchants.google.com/
    解析 Angular 渲染的 scorecard + product-status-chart 组件。
    """
    result = {
        "status": "",
        "account_status": "",
        "product_status": "",
        "product_count": 0,
        "approved": 0,
        "not_approved": 0,
        "limited": 0,
        "under_review": 0,
        "issues": [],
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

    # ── 1. 解析 Total products ──
    try:
        scorecard = tab_gmc.ele("tag:tab-scorecard", timeout=3)
        if scorecard:
            aria_label = scorecard.attr("aria-label") or ""
            executor.logger.info(f"[GMC] scorecard aria-label: {aria_label}")
            # "Total products 21998 +22K" → 提取数字
            import re as _re
            m = _re.search(r"Total products\s+([\d,]+)", aria_label)
            if m:
                result["product_count"] = int(m.group(1).replace(",", ""))
    except Exception as e:
        executor.logger.warning(f"[GMC] 解析 Total products 失败: {e}")

    # ── 2. 解析 product-status-chart 各行 ──
    # DrissionPage 选择器在 Angular 自定义元素内部不稳定，改用文本解析
    # 模式: "Approved\n0 Approved\n+0 Approved from 7 days ago\nLimited\n..."
    status_key_map = {
        "Approved":      "approved",
        "Limited":       "limited",
        "Not approved":  "not_approved",
        "Under review":  "under_review",
    }
    try:
        chart = tab_gmc.ele("tag:product-status-chart", timeout=5)
        if chart:
            executor.logger.info("[GMC] 找到 product-status-chart，文本解析...")
            import re as _re
            chart_text = chart.text or ""
            executor.logger.info(f"[GMC] chart text ({len(chart_text)} chars): {chart_text[:500]}")
            for label_text, count_key in status_key_map.items():
                # 匹配: label\n数字 label   (如 "Approved\n0 Approved")
                pattern = _re.escape(label_text) + r"\s*\n\s*([\d,]+K?)\s+" + _re.escape(label_text)
                m = _re.search(pattern, chart_text)
                if m:
                    num_text = m.group(1)
                    cleaned = num_text.replace("K", "").replace("M", "").replace(",", "")
                    if cleaned.isdigit():
                        count = int(num_text.replace("K", "000").replace("M", "000000").replace(",", ""))
                        result[count_key] = count
                        executor.logger.info(f"[GMC] {label_text}: {count} (raw: {num_text})")
                    else:
                        executor.logger.warning(f"[GMC] {label_text} 无法解析数字: {num_text}")
                else:
                    executor.logger.warning(f"[GMC] {label_text} 文本模式未匹配")
        else:
            executor.logger.warning("[GMC] 未找到 product-status-chart 元素")
    except Exception as e:
        executor.logger.warning(f"[GMC] 解析 product-status-chart 失败: {e}")

    # ── 2b. 归一化：单个状态数量不超过 product_count（K/M 取整可能略大） ──
    pc = result["product_count"]
    if pc > 0:
        for key in ("approved", "not_approved", "limited", "under_review"):
            if result[key] > pc:
                executor.logger.info(f"[GMC] {key} {result[key]} > product_count {pc}，归一化")
                result[key] = pc

    # ── 3. 综合判定 product_status ──
    not_approved = result["not_approved"]
    approved = result["approved"]
    limited = result["limited"]
    under_review = result["under_review"]
    chart_sum = not_approved + approved + limited + under_review
    total = result["product_count"] or chart_sum

    # 如果 chart 行全部为 0 但 product_count > 0，说明页面解析不完整
    if chart_sum == 0 and result["product_count"] > 0:
        result["product_status"] = "解析不完整"
        result["account_status"] = "未知"
        result["status"] = "pending"
        executor.logger.warning(
            f"[GMC] chart 行全部为 0，但 product_count={result['product_count']}，"
            "可能页面未完全加载或解析失败"
        )
    elif not total:
        result["product_status"] = "unknown"
        result["account_status"] = "未知"
        result["status"] = "pending"
    elif approved == total:
        result["product_status"] = "已批准"
    elif not_approved == total:
        result["product_status"] = "未批准"
    elif not_approved > 0:
        result["product_status"] = f"部分未批准({not_approved}/{total})"
    else:
        result["product_status"] = "审核中"

    # ── 4. 综合判定 account_status（仅当上一步未设置时） ──
    if not result["account_status"]:
        if not total:
            result["account_status"] = "未知"
        elif not_approved == 0 and approved > 0:
            result["account_status"] = "已批准"
        elif not_approved > 0 and approved > 0:
            result["account_status"] = "警告"
        elif not_approved > 0 and approved == 0:
            result["account_status"] = "未批准"

    # ── 5. 综合判定 status（仅当上一步未设置时） ──
    if not result["status"]:
        if result["account_status"] in ("未批准",):
            result["status"] = "suspended"
        elif result["account_status"] in ("未知",):
            result["status"] = "pending"
        elif result["not_approved"] > 0:
            result["status"] = "warning"
        elif result["under_review"] > 0 or result["limited"] > 0:
            result["status"] = "reviewing"
        else:
            result["status"] = "active"

    executor.logger.info(
        f"[GMC] 查询完成: status={result['status']}, "
        f"products={result['product_count']}, "
        f"approved={result['approved']}, "
        f"not_approved={result['not_approved']}"
    )
    return result
