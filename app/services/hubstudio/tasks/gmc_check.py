"""GMC 状态检查 (gmc_check)"""

import re
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

        browser = None
        for i in range(10):
            try:
                browser = Chromium(addr_or_opts=f"http://127.0.0.1:{debug_port}")
                browser.set.auto_handle_alert()
                executor.logger.info(f"[gmc_check] DrissionPage 连接成功 (尝试 {i + 1} 次)")
                break
            except Exception:
                if i < 9:
                    executor.logger.info(f"[gmc_check] 端口 {debug_port} 未就绪，2s 后重试...")
                    time.sleep(2)
                else:
                    raise
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
            executor.logger.info(f"[gmc_check] 完成: gmc_status={result.get('gmc_status')}")
            return result
        
        finally:
            browser.quit()

    except Exception as e:
        executor.logger.error(f"[gmc_check] 失败: {e}")
        return {"status": "failed", "error": str(e), "domain": domain}


def _parse_count(raw: str) -> int:
    """解析数字字符串: "3280" / "3.28K" / "1,234" / "1.5M" → int"""
    num = raw.replace(",", "").strip()
    mul = 1
    if num.upper().endswith("K"):
        num, mul = num[:-1], 1000
    elif num.upper().endswith("M"):
        num, mul = num[:-1], 1000000
    try:
        return int(float(num) * mul)
    except (ValueError, TypeError):
        return 0


def _extract_chart_count(chart_text: str, label: str, key: str, result: dict, executor) -> bool:
    """从 chart 文本中提取某个状态的数量

    匹配格式: "Approved\n0 Approved" / "Not approved\n3.28K Not approved"
    大小写不敏感，支持 K/M 后缀。
    """
    # 用标签首尾包裹，兼容 re.escape 处理空格
    escaped = re.escape(label)
    # 匹配: 标签行 → 换行 → 数字+标签行
    pattern = escaped + r"\s*\n\s*([\d,]+(?:\.\d+)?[KMkm]?)\s+" + escaped
    m = re.search(pattern, chart_text, re.IGNORECASE)
    if not m:
        return False
    count = _parse_count(m.group(1))
    result[key] = count
    executor.logger.info(f"[GMC] {label}: {count} (raw: {m.group(1)})")
    return True


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
    }

    gmc_url = "https://merchants.google.com/"
    tab_gmc = None

    try:
        for t in browser.tabs:
            try:
                url = t.url or ""
                if "merchants.google.com" in url:
                    # 复用已有 tab，刷新页面确保数据最新
                    tab_gmc = t
                    tab_gmc.refresh()
                    executor.logger.info(f"[GMC] 复用已有 tab 并刷新: {url[:80]}")
                    break
            except Exception:
                pass
    except Exception:
        pass

    if not tab_gmc:
        tab_gmc = browser.new_tab(gmc_url)
        executor.logger.info(f"[GMC] 新建 tab: {gmc_url}")

    # ── 等待 Angular 渲染完成（DrissionPage 原生等待，基础超时 10s） ──
    try:
        tab_gmc.wait.ele_displayed("tag:tab-scorecard", timeout=90)
        executor.logger.info("[GMC] tab-scorecard 已渲染")
    except Exception:
        try:
            tab_gmc.wait.ele_displayed("tag:product-status-chart", timeout=20)
            executor.logger.info("[GMC] product-status-chart 已渲染")
        except Exception:
            executor.logger.warning("[GMC] 关键元素未在超时内出现，继续尝试解析")
    # Angular 数据绑定需要额外等待
    time.sleep(1)

    # ── 1. 解析 Total products ──
    # aria-label 格式多种: "Total products 21998 +22K" / "Total clicks 65 Up from 0" 等
    try:
        scorecard = tab_gmc.ele("tag:tab-scorecard", timeout=10)
        if scorecard:
            aria_label = scorecard.attr("aria-label") or ""
            executor.logger.info(f"[GMC] scorecard aria-label: {aria_label}")
            # 优先级: Total products > Total 任意指标 > 首个大数字
            for pat in (r"Total products\s+([\d,]+(?:\.\d+)?[KM]?)",
                         r"Total\s+\w+\s+([\d,]+(?:\.\d+)?[KM]?)",
                         r"\b([\d,]{4,}(?:\.\d+)?[KM]?)\b"):
                m = re.search(pat, aria_label, re.IGNORECASE)
                if m:
                    count = _parse_count(m.group(1))
                    if count > 0:
                        result["product_count"] = count
                        executor.logger.info(f"[GMC] product_count 提取成功: {count}")
                        break
    except Exception as e:
        executor.logger.warning(f"[GMC] 解析 Total products 失败: {e}")

    # ── 2. 解析 product-status-chart 各行 ──
    # 文本格式: "Approved\n0 Approved\n+0 Approved from 7 days ago\nLimited\n..."
    # 兼容 Not approved / Disapproved 等多种表述，大小写不敏感，K/M 后缀
    status_key_map = {
        "Approved":      "approved",
        "Limited":       "limited",
        "Under review":  "under_review",
    }
    # "Not approved" 可能显示为 "Disapproved"、"Not Approved" 等，用备选列表
    not_approved_labels = ("Not approved", "Disapproved", "Not Approved")
    try:
        chart = tab_gmc.ele("tag:product-status-chart", timeout=10)
        if chart:
            executor.logger.info("[GMC] 找到 product-status-chart，文本解析...")
            chart_text = chart.text or ""
            executor.logger.info(f"[GMC] chart text ({len(chart_text)} chars): {chart_text[:500]}")
            # 先处理标准状态
            for label_text, count_key in status_key_map.items():
                _extract_chart_count(chart_text, label_text, count_key, result, executor)
            # 再处理 Not approved（多种表述）
            for label in not_approved_labels:
                if _extract_chart_count(chart_text, label, "not_approved", result, executor):
                    break
            else:
                executor.logger.warning("[GMC] Not approved / Disapproved 文本模式未匹配")
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
