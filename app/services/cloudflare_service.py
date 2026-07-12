import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.utils.config_reader import get_config, get_provider_info
from app.models.site_pipeline import Site
from app.core.exceptions import CloudflareError

logger = logging.getLogger(__name__)


class CloudflareService:
    def __init__(self):
        self.base = 'https://api.cloudflare.com/client/v4'
        self.session = httpx.Client(http2=True)
        self.session.headers.update({
            'Authorization': f'Bearer {get_config("CF_API_TOKEN")}',
            'Content-Type': 'application/json',
        })
        self.account_id = get_config('CF_ACCOUNT_ID')
        self.proxied = get_config('CF_PROXIED', 'false').lower() == 'true'
        self.ttl = int(get_config('CF_TTL') or '1')
        self.timeout_val = int(get_config('CF_TIMEOUT') or '20')
        self.timeout = httpx.Timeout(self.timeout_val)

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, **params) -> Dict[str, Any]:
        try:
            resp = self.session.request(
                method, self.base + path, json=payload, params=params or None,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, OSError) as exc:
            logger.error("Cloudflare API error: %s %s -> %s", method, path, str(exc))
            return {"success": False, "errors": [{"message": str(exc)}]}

    def _get(self, path: str, **params) -> Dict[str, Any]:
        return self._request("GET", path, payload=None, **params)

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", path, payload=payload)

    def _put(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("PUT", path, payload=payload)

    def get_or_create_zone(self, root_domain: str) -> Tuple[Optional[str], List[str], str]:
        data = self._get('/zones', name=root_domain)
        if data.get('success') and data.get('result'):
            z = data['result'][0]
            return z['id'], z.get('name_servers') or [], z.get('status', '')
        payload = {'account': {'id': self.account_id}, 'name': root_domain, 'jump_start': True}
        data = self._post('/zones', payload)
        if data.get('success'):
            z = data['result']
            return z['id'], z.get('name_servers') or [], 'pending'
        return None, [], ''

    def add_or_update_a_record(self, zone_id: str, record_name: str, target_ip: str) -> bool:
        data = self._get(f'/zones/{zone_id}/dns_records', name=record_name, type='A')
        if not data.get('success'):
            return False
        payload = {'type': 'A', 'name': record_name, 'content': target_ip, 'ttl': self.ttl, 'proxied': self.proxied}
        records = data.get('result') or []
        if records:
            record = records[0]
            if record.get('content') == target_ip and record.get('proxied') == self.proxied:
                return True
            data = self._put(f'/zones/{zone_id}/dns_records/{record["id"]}', payload)
            return bool(data.get('success'))
        data = self._post(f'/zones/{zone_id}/dns_records', payload)
        return bool(data.get('success'))

    async def provision_dns(self, site: Site) -> Dict[str, Any]:
        """DNS + NS 一起运行：
        1. 获取/创建 Cloudflare Zone
        2. 如果 Zone 状态为 pending 或 invalid_nameservers，自动调用 Dynadot 修改 NS
        3. 添加根域名 + www 的 A 记录
        """
        started = datetime.now()
        zone_id, ns, status = self.get_or_create_zone(site.domain)
        if not zone_id:
            raise CloudflareError("create zone", detail=f"domain={site.domain}")

        # DNS + NS 一起运行：新Zone或NS异常时，自动修改Dynadot NS
        dynadot_result = None
        if status == 'pending' or status == 'invalid_nameservers':
            if status == 'invalid_nameservers':
                logger.warning("{{domain:{}}} 域名 NS 状态异常(invalid_nameservers)，执行修复 NS 操作".format(site.domain))
            else:
                logger.info("{{domain:{}}} 全新域名 Zone，调用 Dynadot API 修改 NS 服务器".format(site.domain))
            try:
                from app.services.providers.dynadot_service import DynadotService
                dynadot_svc = DynadotService()
                dynadot_result = dynadot_svc.set_nameserver(site.domain, ns)
                ok = dynadot_result.get("success", False)
                site.dynadot_status = "ns_updated" if ok else f"ns_failed:{str(dynadot_result.get('error',''))[:80]}"
                logger.info("{{domain:{}}} Dynadot NS 修改结果: {}".format(site.domain, '成功' if ok else '失败'))
            except Exception as e:
                dynadot_result = {"success": False, "error": str(e)}
                site.dynadot_status = f"ns_failed:{str(e)[:80]}"
                logger.error("{{domain:{}}} Dynadot NS 修改异常: {}".format(site.domain, str(e)))
        else:
            logger.info("{{domain:{}}} Zone 状态为 {}，无需修改 NS".format(site.domain, status))
            site.dynadot_status = f"zone_{status}"

        root_ok = self.add_or_update_a_record(zone_id, site.domain, site.server_ip)
        www_ok = self.add_or_update_a_record(zone_id, f'www.{site.domain}', site.server_ip)
        site.cloudflare_status = '已解析' if root_ok and www_ok else '部分失败'

        now = datetime.now()
        log_entry = json.dumps({
            "ts": now.isoformat(),
            "source": "cloudflare_dns_ns",
            "action": "Cloudflare DNS解析 + NS配置",
            "status": "success" if (root_ok and www_ok) else "partial_fail",
            "started_at": started.isoformat() if dynadot_result else now.isoformat(),
            "completed_at": now.isoformat(),
            "duration_ms": int((now - started).total_seconds() * 1000),
            "zone_id": zone_id,
            "zone_status": status,
            "name_servers": ns,
            "root_ok": root_ok,
            "www_ok": www_ok,
            "dynadot_result": dynadot_result,
            "provider": get_provider_info("cloudflare"),
        }, ensure_ascii=False)
        site.pipeline_log = (site.pipeline_log or '') + '\n' + log_entry

        await site.save()
        return {
            'zone_id': zone_id, 'zone_status': status, 'name_servers': ns,
            'root_ok': root_ok, 'www_ok': www_ok,
            'dynadot_result': dynadot_result,
        }
