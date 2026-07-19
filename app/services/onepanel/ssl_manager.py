import time
from typing import Dict, Optional

from app.utils.provider_resolver import ProviderResolver
from .client import OnePanelAPI
from .utils import _log, _provider_value


class OnePanelSSLManager:
    def __init__(self, api: OnePanelAPI):
        self.api = api
        cfgs = ProviderResolver.sync_get_config_map('onepanel')
        self.enable_ssl = str(_provider_value(cfgs, 'OP_ENABLE_SSL', 'enable_ssl', 'true')).lower() == 'true'
        self.force_https = str(_provider_value(cfgs, 'OP_FORCE_HTTPS', 'force_https', 'true')).lower() == 'true'
        self.ssl_ready_timeout = int(_provider_value(cfgs, 'OP_SSL_READY_TIMEOUT', 'ssl_ready_timeout', '180'))

    def get_acme_id(self) -> Optional[int]:
        ok, data = self.api.post('/websites/acme/search', {'page': 1, 'pageSize': 10})
        if ok and isinstance(data, dict) and data.get('items'):
            return int(data['items'][0]['id'])
        return None

    def find_ready_ssl(self, domain: str) -> Optional[int]:
        """查找域名已就绪的 SSL 证书"""
        ok, data = self.api.post('/websites/ssl/search', {'page': 1, 'pageSize': 100, 'domain': domain})
        if not ok or not isinstance(data, dict):
            return None
        for cert in (data.get('items') or []):
            if cert.get('primaryDomain') == domain and cert.get('status') == 'ready':
                return int(cert['id'])
        return None

    def apply_and_bind(self, site_id: int, domain: str) -> str:
        """申请 SSL 证书并绑定到站点，返回最终协议"""
        if not self.enable_ssl or not self.force_https:
            _log.info("SSL 未启用（enable_ssl=%s, force_https=%s），使用 HTTP", self.enable_ssl, self.force_https)
            return 'http'

        acme_id = self.get_acme_id()
        if not acme_id:
            _log.warning("未找到 ACME 账户，无法申请 SSL，回退到 HTTP")
            return 'http'

        try:
            ssl_id = self.find_ready_ssl(domain)
            if not ssl_id:
                ok, data = self.api.post('/websites/ssl', {
                    'acmeAccountId': acme_id,
                    'apply': False,
                    'autoRenew': True,
                    'primaryDomain': domain,
                    'provider': 'http',
                    'keyType': 'EC256',
                    'pushDir': False,
                })
                if not ok or not isinstance(data, dict) or not data.get('id'):
                    _log.warning("创建 SSL 记录失败：%s，回退 HTTP", data)
                    return 'http'
                ssl_id = int(data['id'])

                ok, msg = self.api.post('/websites/ssl/obtain', {'ID': ssl_id, 'skipDNSCheck': False})
                # 1Panel 可能返回 500 "任务执行中" — SSL 已在签发中，继续轮询等待即可
                if not ok:
                    msg_str = str(msg)
                    if '任务执行中' in msg_str or '重复执行' in msg_str:
                        _log.info("SSL 已在签发中（1Panel 正在执行），继续等待: id=%s", ssl_id)
                    else:
                        _log.warning("SSL 签发请求失败: %s，回退 HTTP", msg_str)
                        return 'http'

                # 轮询等待证书就绪
                start = time.time()
                while time.time() - start < self.ssl_ready_timeout:
                    ready_id = self.find_ready_ssl(domain)
                    if ready_id:
                        ssl_id = ready_id
                        break
                    time.sleep(5)
                else:
                    _log.warning("SSL 证书等待超时 %s 秒，回退 HTTP", self.ssl_ready_timeout)
                    return 'http'

            ok, msg = self.api.post(f'/websites/{site_id}/https', {
                'websiteId': site_id,
                'enable': True,
                'type': 'existed',
                'websiteSSLId': ssl_id,
                'httpConfig': 'HTTPToHTTPS',
                'hsts': False,
                'httpsPorts': [443],
            })
            if ok:
                return 'https'
            _log.warning("HTTPS 绑定失败：%s，回退 HTTP", msg)
        except Exception as exc:
            _log.warning("SSL 处理失败，降级 HTTP：%s", exc)
        return 'http'
