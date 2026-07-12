"""网站控制 (website_control)"""

import time

from app.core.exceptions import HubStudioError


def execute_website_control(executor, job: dict, payload: dict) -> dict:
    """启动浏览器并自动登录 WordPress 后台"""
    domain = payload.get("domain", job.get("domain", ""))
    hub_env_id = payload.get("hub_env_id", "")
    login_url = payload.get("login_url", "")
    wp_username = payload.get("wp_username", "admin")
    wp_password = payload.get("wp_password", "")

    if not hub_env_id:
        return {"status": "failed", "error": "hub_env_id is required"}

    executor.logger.info(
        f"[website_control] 开始: domain={domain}, env_id={hub_env_id}, wp={wp_username}"
    )

    if not executor.rt.is_port_open():
        executor.logger.warning("[website_control] Connector 端口不可达，尝试启动...")
        executor.rt.start_connector()

    client = executor.rt.ensure_client()
    result = {"status": "success", "domain": domain, "actions": {}}

    try:
        # ── 启动浏览器 ──
        resp = client.start_browser(
            int(hub_env_id), isHeadless=False,
            shouldCloseTabsOnOpen=True, skipSystemResourceCheck=True,
        )
        debug_port = resp.get("data", {}).get("debuggingPort")
        if not debug_port:
            raise HubStudioError("start browser", detail="未获取到 debuggingPort")
        executor.logger.info(f"[website_control] 浏览器已启动: port={debug_port}")
        result["debug_port"] = debug_port

        # ── DrissionPage 自动化 ──
        try:
            from DrissionPage import Chromium
        except ImportError:
            executor.logger.warning("[website_control] DrissionPage 未安装，跳过页面自动化")
            result["actions"]["browser"] = "started (no automation)"
            return result

        browser = Chromium(addr_or_opts=f"http://127.0.0.1:{debug_port}")

        # ── WordPress 后台自动登录 ──
        wp_url = login_url or f"https://{domain}/wp-admin"
        executor.logger.info(f"[website_control] 打开 WordPress 后台: {wp_url}")
        try:
            tab_wp = browser.new_tab(wp_url)

            el_user = tab_wp.ele("#user_login", timeout=5)
            el_pass = tab_wp.ele("#user_pass", timeout=5)
            el_submit = tab_wp.ele("#wp-submit", timeout=5)

            if el_user and el_pass and el_submit:
                time.sleep(3)
                el_submit.click()

                logged_in = tab_wp.ele("#wpadminbar", timeout=5) or tab_wp.ele("#dashboard-widgets-wrap", timeout=3)
                if logged_in:
                    result["actions"]["wordpress"] = "logged_in"
                    executor.logger.info(f"[website_control] WordPress 登录成功")
                else:
                    error_el = tab_wp.ele("#login_error", timeout=2)
                    if error_el:
                        result["actions"]["wordpress"] = f"login_failed: {error_el.text[:100]}"
                        executor.logger.warning(f"[website_control] WordPress 登录失败: {error_el.text[:100]}")
                    else:
                        result["actions"]["wordpress"] = "opened (login status unknown)"
                        executor.logger.info(f"[website_control] WordPress 页面已打开，登录状态未知")
            else:
                if tab_wp.ele("#wpadminbar", timeout=3) or tab_wp.url and "wp-admin" in tab_wp.url:
                    result["actions"]["wordpress"] = "already_logged_in"
                    executor.logger.info(f"[website_control] WordPress 已处于登录状态")
                else:
                    result["actions"]["wordpress"] = "form_not_found"
                    executor.logger.warning(f"[website_control] WordPress 登录表单未找到")
        except Exception as e:
            result["actions"]["wordpress"] = f"error: {str(e)[:100]}"
            executor.logger.error(f"[website_control] WordPress 自动化异常: {e}")

        result["url"] = wp_url
        executor.logger.info(f"[website_control] 完成: {result['actions']}")
        return result

    except Exception as e:
        executor.logger.error(f"[website_control] 失败: {e}")
        return {"status": "failed", "error": str(e), "domain": domain}
