import json
import logging
from typing import Any, Dict, Optional

import httpx

from app.utils.config_reader import get_config, get_provider_info
from app.models.site_pipeline import Site
from app.core.exceptions import CloudflareError

logger = logging.getLogger(__name__)


class CloudflareRedirectService:
    """Cloudflare Page Rule 301 重定向服务

    参考 cf_redirect_YY.py 逻辑：获取全部规则 → 按 match_url 查重 → upsert
    每个域名创建两条规则：{domain}/* 和 www.{domain}/*
    """

    def __init__(self):
        self.base = 'https://api.cloudflare.com/client/v4'
        self.session = httpx.Client(http2=True)
        self.session.headers.update({
            'Authorization': f'Bearer {get_config("CF_API_TOKEN")}',
            'Content-Type': 'application/json',
        })
        self.timeout = httpx.Timeout(int(get_config('CF_TIMEOUT') or '20'))

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, **params) -> Dict[str, Any]:
        try:
            resp = self.session.request(
                method, self.base + path, json=payload, params=params or None,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, OSError) as exc:
            logger.error("Cloudflare Redirect API error: %s %s -> %s", method, path, str(exc))
            return {"success": False, "errors": [{"message": str(exc)}]}

    def _get(self, path: str, **params) -> Dict[str, Any]:
        return self._request("GET", path, payload=None, **params)

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", path, payload=payload)

    def _put(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("PUT", path, payload=payload)

    def get_zone_id(self, domain: str) -> Optional[str]:
        """根据域名获取 Cloudflare Zone ID"""
        data = self._get('/zones', name=domain)
        return data['result'][0]['id'] if data.get('success') and data.get('result') else None

    def get_all_page_rules(self, zone_id: str) -> list:
        """获取全部 Page Rule（不过滤状态），参考 cf_redirect_YY.py"""
        data = self._get(f'/zones/{zone_id}/pagerules', per_page=100)
        return data.get('result') or [] if data.get('success') else []

    def upsert_redirect_rule(self, zone_id: str, match_url: str,
                             redirect_target: str, redirect_code: int = 301) -> bool:
        """存在则更新，不存在则创建（参考 cf_redirect_YY.py upsert_redirect_rule）

        :param zone_id:  域名 Zone ID
        :param match_url: 匹配 URL，如 wygknzvv.shop/*
        :param redirect_target: 跳转目标，如 https://baidu.com/$1
        :param redirect_code: 跳转状态码，默认 301
        """
        all_rules = self.get_all_page_rules(zone_id)
        target_rule_id = None

        # 查找同名匹配规则
        for rule in all_rules:
            constraint_val = rule["targets"][0]["constraint"]["value"]
            if constraint_val == match_url:
                target_rule_id = rule["id"]
                break

        payload = {
            "targets": [
                {
                    "target": "url",
                    "constraint": {
                        "operator": "matches",
                        "value": match_url
                    }
                }
            ],
            "actions": [
                {
                    "id": "forwarding_url",
                    "value": {
                        "url": redirect_target,
                        "status_code": redirect_code
                    }
                }
            ],
            "priority": 1,
            "status": "active"
        }

        if target_rule_id:
            # 已有规则 → PUT 更新
            data = self._put(f'/zones/{zone_id}/pagerules/{target_rule_id}', payload)
            ok = bool(data.get("success"))
            if ok:
                logger.info("{{domain:全局}} √ 更新跳转规则成功：{} -> {}".format(match_url, redirect_target))
            else:
                logger.error("{{domain:全局}} × 更新跳转规则失败 {} | 错误：{}".format(match_url, data.get('errors')))
            return ok
        else:
            # 无规则 → POST 新建
            data = self._post(f'/zones/{zone_id}/pagerules', payload)
            ok = bool(data.get("success"))
            if ok:
                logger.info("{{domain:全局}} √ 创建跳转规则成功：{} -> {}".format(match_url, redirect_target))
            else:
                logger.error("{{domain:全局}} × 创建跳转规则失败 {} | 错误：{}".format(match_url, data.get('errors')))
            return ok

    async def setup_redirect(self, site: Site, target_url: str = '') -> Dict[str, Any]:
        """为站点创建 301 重定向规则（根域名 + www 各一条）

        参考 cf_redirect_YY.py main()：每个域名创建两条规则
        - {domain}/*
        - www.{domain}/*

        :param site:      站点对象
        :param target_url: 跳转目标 URL，为空则默认跳转到 https://{domain}/$1
        """
        zone_id = self.get_zone_id(site.domain)
        if not zone_id:
            raise CloudflareError("get zone", detail=f"zone not found for {site.domain}")

        target = target_url or f'https://{site.domain}/$1'

        # 规则1：根域名
        rule1_match = f"{site.domain}/*"
        rule1_ok = self.upsert_redirect_rule(zone_id, rule1_match, target, 301)

        # 规则2：www 子域名
        rule2_match = f"www.{site.domain}/*"
        rule2_ok = self.upsert_redirect_rule(zone_id, rule2_match, target, 301)

        all_ok = rule1_ok and rule2_ok
        site.pipeline_status = 'redirect:success' if all_ok else 'redirect:partial' if (rule1_ok or rule2_ok) else 'redirect:failed'

        log_entry = json.dumps({
            "source": "cloudflare_redirect",
            "rules": [
                {"match": rule1_match, "ok": rule1_ok},
                {"match": rule2_match, "ok": rule2_ok},
            ],
            "target": target,
            "provider": get_provider_info("cloudflare"),
        }, ensure_ascii=False)
        site.pipeline_log = (site.pipeline_log or '') + '\n' + log_entry

        await site.save()
        return {
            'ok': all_ok,
            'rules': [
                {"match": rule1_match, "ok": rule1_ok},
                {"match": rule2_match, "ok": rule2_ok},
            ],
            'target': target,
        }
