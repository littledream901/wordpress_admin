import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.utils.config_reader import get_provider_info
from app.utils.provider_resolver import ProviderResolver
from app.utils.http_retry import retry_request
from app.models.site_pipeline import Site
from app.core.exceptions import CloudflareError

logger = logging.getLogger(__name__)


class CloudflareService:
    """Cloudflare API 客户端 — 配置延迟加载，避免模块导入时 Tortoise 未初始化"""

    def __init__(self):
        self.base = 'https://api.cloudflare.com/client/v4'
        self._session = None
        self._config_loaded = False

    def _ensure_config(self):
        """延迟加载配置（首次 API 调用时触发）"""
        if self._config_loaded:
            return
        self.account_id = ProviderResolver.sync_get_config('cloudflare', 'account_id', '')
        self.proxied = ProviderResolver.sync_get_config('cloudflare', 'proxied', 'false').lower() == 'true'
        self.ttl = int(ProviderResolver.sync_get_config('cloudflare', 'ttl', '') or '1')
        self.timeout_val = int(ProviderResolver.sync_get_config('cloudflare', 'timeout', '') or '20')
        self.timeout = httpx.Timeout(self.timeout_val)
        self._config_loaded = True

    @property
    def session(self):
        if self._session is None:
            self._ensure_config()
            token = ProviderResolver.sync_get_config('cloudflare', 'api_token', '')
            s = httpx.Client(http2=True)
            s.headers.update({
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            })
            self._session = s
        return self._session

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, **params) -> Dict[str, Any]:
        try:
            resp = retry_request(
                lambda: self.session.request(
                    method, self.base + path, json=payload, params=params or None,
                    timeout=self.timeout,
                ),
                max_retries=3,
                context=f"Cloudflare {method} {path}",
            )
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, OSError) as exc:
            err_detail = str(exc)
            # 尝试提取 Cloudflare 返回的错误详情
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    cf_body = exc.response.json()
                    cf_errors = cf_body.get('errors', [])
                    if cf_errors:
                        err_detail = '; '.join(e.get('message', str(e)) for e in cf_errors)
                except Exception:
                    pass
            logger.error("Cloudflare API error: %s %s -> %s", method, path, err_detail)
            return {"success": False, "errors": [{"message": err_detail}]}

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
            return z['id'], z.get('name_servers') or [], z.get('status') or 'active'
        # 记录 GET 失败详情
        if not data.get('success'):
            err_msgs = [e.get('message', str(e)) for e in data.get('errors', [])]
            logger.warning("Cloudflare GET zones 失败 (domain=%s): %s", root_domain, '; '.join(err_msgs) or data)
        payload = {'account': {'id': self.account_id}, 'name': root_domain, 'jump_start': True}
        data = self._post('/zones', payload)
        if data.get('success'):
            z = data['result']
            return z['id'], z.get('name_servers') or [], 'pending'
        # 记录 POST 失败详情
        err_msgs = [e.get('message', str(e)) for e in data.get('errors', [])]
        logger.warning("Cloudflare POST zones 失败 (domain=%s, account_id=%s): %s",
                       root_domain, self.account_id[:8] + '...' if self.account_id else '(empty)',
                       '; '.join(err_msgs) or data)
        return None, [], ''

    def delete_records_by_type(self, zone_id: str, record_type: str) -> int:
        """删除 Zone 下指定类型的所有 DNS 记录，返回删除数量"""
        data = self._get(f'/zones/{zone_id}/dns_records', type=record_type, per_page=100)
        if not data.get('success'):
            return 0
        deleted = 0
        for record in (data.get('result') or []):
            resp = self._request('DELETE', f'/zones/{zone_id}/dns_records/{record["id"]}')
            if resp.get('success'):
                deleted += 1
                logger.info("已删除 DNS %s 记录: %s → %s", record_type, record.get('name'), record.get('content'))
        return deleted

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

    def add_or_update_cname_record(self, zone_id: str, record_name: str, target: str) -> bool:
        """添加或更新 CNAME 记录"""
        data = self._get(f'/zones/{zone_id}/dns_records', name=record_name, type='CNAME')
        if not data.get('success'):
            return False
        payload = {'type': 'CNAME', 'name': record_name, 'content': target, 'ttl': self.ttl, 'proxied': self.proxied}
        records = data.get('result') or []
        if records:
            record = records[0]
            if record.get('content') == target and record.get('proxied') == self.proxied:
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

    async def provision_shopify_dns(self, site: Site) -> Dict[str, Any]:
        """Shopify 站点 DNS 配置：
        1. 获取/创建 Cloudflare Zone + 自动 Dynadot NS
        2. 删除域名上所有 A 和 AAAA 记录
        3. A 记录 @ → 23.227.38.65
        4. CNAME 记录 www → shops.myshopify.com.
        """
        SHOPIFY_IP = '23.227.38.65'
        SHOPIFY_CNAME = 'shops.myshopify.com.'

        started = datetime.now()
        zone_id, ns, status = self.get_or_create_zone(site.domain)
        if not zone_id:
            raise CloudflareError("create zone", detail=f"domain={site.domain}")

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

        # 删除域名上所有 A 和 AAAA 记录
        deleted_a = self.delete_records_by_type(zone_id, 'A')
        deleted_aaaa = self.delete_records_by_type(zone_id, 'AAAA')
        logger.info("{{domain:{}}} Shopify DNS: 已删除 {} 条 A 记录, {} 条 AAAA 记录".format(
            site.domain, deleted_a, deleted_aaaa))

        # A 记录：@ → Shopify IP
        root_ok = self.add_or_update_a_record(zone_id, site.domain, SHOPIFY_IP)
        # CNAME 记录：www → shops.myshopify.com.
        www_ok = self.add_or_update_cname_record(zone_id, f'www.{site.domain}', SHOPIFY_CNAME)

        site.cloudflare_status = '已解析' if root_ok and www_ok else '部分失败'

        now = datetime.now()
        log_entry = json.dumps({
            "ts": now.isoformat(),
            "source": "cloudflare_shopify_dns",
            "action": "Shopify DNS 解析 + NS 配置",
            "status": "success" if (root_ok and www_ok) else "partial_fail",
            "started_at": started.isoformat(),
            "completed_at": now.isoformat(),
            "duration_ms": int((now - started).total_seconds() * 1000),
            "zone_id": zone_id,
            "zone_status": status,
            "name_servers": ns,
            "root_ok": root_ok,
            "www_ok": www_ok,
            "dynadot_result": dynadot_result,
            "deleted_a": deleted_a,
            "deleted_aaaa": deleted_aaaa,
            "provider": get_provider_info("cloudflare"),
        }, ensure_ascii=False)
        site.pipeline_log = (site.pipeline_log or '') + '\n' + log_entry

        await site.save()
        return {
            'zone_id': zone_id, 'zone_status': status, 'name_servers': ns,
            'root_ok': root_ok, 'www_ok': www_ok,
            'dynadot_result': dynadot_result,
            'deleted_a': deleted_a, 'deleted_aaaa': deleted_aaaa,
        }
