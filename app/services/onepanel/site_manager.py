import hashlib
import random
import secrets
import string
import time
import uuid
from typing import Any, Dict, Optional

from app.utils.config_reader import get_config
from app.utils.provider_resolver import ProviderResolver
from app.models.site_pipeline import Site
from app.core.exceptions import OnePanelError, DomainAlreadyExistsError
from .client import OnePanelAPI
from .utils import _log, _provider_value, parse_env_text, safe_alias


class OnePanelSiteManager:
    def __init__(self, api: OnePanelAPI, file_manager: 'OnePanelFileManager' = None):
        self.api = api
        self.file_manager = file_manager
        cfgs = ProviderResolver.sync_get_config_map('onepanel')
        self.website_group_id = int(_provider_value(cfgs, 'OP_WEBSITE_GROUP_ID', 'website_group_id', '1'))
        auto_clean = _provider_value(cfgs, 'OP_AUTO_CLEAN_CONFLICT', 'auto_clean_conflict_site', 'true')
        self.auto_clean_conflict = str(auto_clean).lower() == 'true'
        self.delete_sleep = int(_provider_value(cfgs, 'OP_DELETE_SLEEP', 'delete_sleep', '8'))
        self.wp_app_key = str(_provider_value(cfgs, 'OP_WP_APP_KEY', 'wp_app_key', 'wordpress'))
        self.wp_app_type = str(_provider_value(cfgs, 'OP_WP_APP_TYPE', 'wp_app_type', 'docker'))
        self.wp_app_id = int(_provider_value(cfgs, 'OP_WP_APP_ID', 'wp_app_id', '0'))
        self.wp_app_detail_id = int(_provider_value(cfgs, 'OP_WP_APP_DETAIL_ID', 'wp_app_detail_id', '0'))
        self.wp_version = str(_provider_value(cfgs, 'OP_WP_VERSION', 'wp_version', 'latest'))
        self.auto_detect_wp_app = str(_provider_value(cfgs, 'OP_AUTO_DETECT_WP_APP', 'auto_detect_wp_app', 'true')).lower() == 'true'
        self.wp_admin_user = str(_provider_value(cfgs, 'OP_WP_ADMIN_USER', 'wp_admin_user', 'admin'))
        self.wp_admin_email_prefix = str(_provider_value(cfgs, 'OP_WP_ADMIN_EMAIL_PREFIX', 'wp_admin_email_prefix', 'admin'))
        self.panel_base = str(_provider_value(cfgs, 'OP_PANEL_BASE', 'panel_base', '/opt/1panel'))
        self.wp_app_root = str(_provider_value(cfgs, 'OP_WP_APP_ROOT', 'wp_app_root', '/opt/1panel/apps/wordpress'))
        self._wp_app_detail_cache: Optional[Dict[str, Any]] = None

    def get_site_id(self, domain: str) -> Optional[int]:
        ok, data = self.api.post('/websites/search', {'page': 1, 'pageSize': 200, 'OrderBy': 'created_at', 'Order': 'descending'})
        if not ok or not isinstance(data, dict):
            return None
        for item in (data.get('items') or []):
            if item.get('primaryDomain') == domain:
                return int(item['id'])
        return None

    def wait_site_id(self, domain: str, timeout: int = 60, interval: int = 3) -> Optional[int]:
        """轮询获取 site_id，避免站点创建后列表未刷新"""
        start = time.time()
        while time.time() - start < timeout:
            site_id = self.get_site_id(domain)
            if site_id:
                return site_id
            time.sleep(interval)
        return None

    def delete_site_by_id(self, site_id: int, delete_app: bool = True, delete_db: bool = True, delete_backup: bool = False) -> None:
        ok, msg = self.api.post('/websites/del', {'id': site_id, 'deleteApp': delete_app, 'deleteBackup': delete_backup, 'deleteDB': delete_db, 'forceDelete': True})
        if not ok:
            raise OnePanelError("delete site", detail=str(msg), status_code=None)
        time.sleep(self.delete_sleep)

    def resolve_wp_app(self) -> Dict[str, Any]:
        if self._wp_app_detail_cache:
            return self._wp_app_detail_cache
        if self.wp_app_detail_id > 0:
            _log.info("resolve_wp_app 使用手动配置: app_id=%s app_detail_id=%s version=%s", self.wp_app_id, self.wp_app_detail_id, self.wp_version)
            result = {'app_id': self.wp_app_id, 'app_detail_id': self.wp_app_detail_id, 'version': self.wp_version, 'app_type': self.wp_app_type, 'app_key': self.wp_app_key}
            self._wp_app_detail_cache = result
            return result
        # /apps/:key 是 GET 端点，不是 POST（参考 doc.json 中 request.AppSearch）
        _log.info("resolve_wp_app 自动检测模式: wp_app_key=%s 目标版本=%s", self.wp_app_key, self.wp_version)
        ok, app_data = self.api.get(f'/apps/{self.wp_app_key}')
        if not ok or not isinstance(app_data, dict):
            raise OnePanelError("get app info", detail=str(app_data))
        app_id = int(app_data.get('id') or self.wp_app_id or 0)
        app_type = app_data.get('type') or self.wp_app_type or 'docker'
        # 版本迭代：从 app 元数据中获取可用版本列表，依次尝试
        versions = []
        if isinstance(app_data.get('versions'), list):
            versions = [v for v in app_data['versions'] if v]
        if not versions:
            versions = [app_data.get('version') or self.wp_version or 'latest']
        if self.wp_version != 'latest' and self.wp_version not in versions:
            versions.insert(0, self.wp_version)
        _log.info("resolve_wp_app 尝试版本列表: %s (app_id=%s app_type=%s)", versions, app_id, app_type)
        for v in versions:
            ok, detail = self.api.get(f'/apps/detail/{app_id}/{v}/{app_type}')
            if ok and isinstance(detail, dict) and detail.get('id'):
                result = {'app_id': app_id, 'app_detail_id': int(detail['id']), 'version': v, 'app_type': app_type, 'app_key': self.wp_app_key}
                _log.info("resolve_wp_app 自动检测成功: app_id=%s app_detail_id=%s version=%s", app_id, result['app_detail_id'], v)
                self._wp_app_detail_cache = result
                return result
        raise OnePanelError("get app detail", detail=f"已尝试版本 {versions}")
    def get_db_info(self, service_name: str, default_db_name: str = '', default_db_user: str = '', default_db_password: str = '') -> Dict[str, str]:
        """从多种数据源获取已安装 WordPress 应用的数据库信息"""
        ok, items_data = self.api.post('/apps/installed/search', {'page': 1, 'pageSize': 200, 'sync': True})
        env_from_search: Dict[str, str] = {}
        found_params: Dict[str, str] = {}
        app_install_id: Optional[int] = None

        if ok and isinstance(items_data, dict):
            for item in (items_data.get('items') or []):
                if item.get('name') == service_name or item.get('serviceName') == service_name:
                    app_install_id = int(item.get('id') or 0)
                    for sub in ('params', 'env', 'config', 'setting'):
                        if isinstance(item.get(sub), dict):
                            env_from_search.update(item[sub])

        def pick(env_dict: Dict[str, str]) -> Dict[str, str]:
            db_name = env_dict.get('PANEL_DB_NAME') or env_dict.get('DB_NAME') or env_dict.get('MYSQL_DATABASE') or env_dict.get('WORDPRESS_DATABASE_NAME') or ''
            db_user = env_dict.get('PANEL_DB_USER') or env_dict.get('DB_USER') or env_dict.get('MYSQL_USER') or env_dict.get('WORDPRESS_DATABASE_USER') or ''
            db_pwd = env_dict.get('PANEL_DB_PASSWORD') or env_dict.get('PANEL_DB_USER_PASSWORD') or env_dict.get('DB_PASSWORD') or env_dict.get('MYSQL_PASSWORD') or env_dict.get('WORDPRESS_DATABASE_PASSWORD') or ''
            db_host = env_dict.get('PANEL_DB_HOST') or env_dict.get('DB_HOST') or 'mysql'
            db_port = env_dict.get('PANEL_DB_PORT') or env_dict.get('DB_PORT') or '3306'
            return {'DB_NAME': db_name or default_db_name, 'DB_USER': db_user or default_db_user, 'DB_PASSWORD': db_pwd or default_db_password, 'DB_HOST': db_host, 'DB_PORT': db_port}

        # 1. search 返回的 params
        found_params = pick(env_from_search)
        if found_params['DB_NAME'] and found_params['DB_USER']:
            return found_params

        # 2. /apps/installed/params/:id
        if app_install_id:
            ok2, params_data = self.api.get(f'/apps/installed/params/{app_install_id}')
            if ok2 and isinstance(params_data, dict):
                merged = dict(env_from_search)
                for sub in ('params', 'env', 'config', 'setting'):
                    if isinstance(params_data.get(sub), dict):
                        merged.update(params_data[sub])
                found_params = pick(merged)
                if found_params['DB_NAME']:
                    return found_params

        # 3. /apps/installed/info/:id
        if app_install_id:
            ok3, info_data = self.api.get(f'/apps/installed/info/{app_install_id}')
            if ok3 and isinstance(info_data, dict):
                merged = dict(env_from_search)
                for sub in ('params', 'env', 'config', 'setting'):
                    if isinstance(info_data.get(sub), dict):
                        merged.update(info_data[sub])
                found_params = pick(merged)
                if found_params['DB_NAME']:
                    return found_params

        # 4. /apps/installed/conninfo
        if app_install_id:
            ok4, conn = self.api.post('/apps/installed/conninfo', {'id': app_install_id, 'key': 'mysql'})
            if ok4 and isinstance(conn, dict):
                found_params['DB_USER'] = conn.get('user', conn.get('username')) or found_params['DB_USER']
                found_params['DB_PASSWORD'] = conn.get('password') or found_params['DB_PASSWORD']
                if found_params['DB_NAME']:
                    return found_params

        # 5. .env 文件（需要 FileManager）
        if self.file_manager and service_name:
            env_path = f'{self.wp_app_root}/{service_name}/.env'
            for _ in range(12):
                if self.file_manager.exists(env_path):
                    content = self.file_manager.read(env_path)
                    if content:
                        found_params.update(pick(parse_env_text(content)))
                        return found_params
                time.sleep(5)

        return found_params

    def wait_app_ready(self, alias: str, domain: str, timeout: int = 420) -> Dict[str, Any]:
        start = time.time()
        while time.time() - start < timeout:
            ok, data = self.api.post('/apps/installed/search', {'page': 1, 'pageSize': 200, 'sync': True})
            if ok and isinstance(data, dict):
                for item in (data.get('items') or []):
                    name = str(item.get('name', ''))
                    service = str(item.get('serviceName', ''))
                    matched = alias in name or alias in service or domain.replace('.', '-') in name
                    if not matched:
                        continue
                    status = str(item.get('status', ''))
                    if status == 'Running':
                        return {'app_id': int(item['id']), 'name': item.get('name', alias), 'service_name': item.get('serviceName') or item.get('name') or alias, 'params': item.get('params') or {}}
                    if 'fail' in status.lower() or 'error' in status.lower() or 'err' in status.lower():
                        raise OnePanelError("install app", detail=f"status={status}")
            time.sleep(8)
        raise TimeoutError(f'应用启动超时：{domain}')

    def rebuild_app(self, app_id: int, wait: int = 8) -> None:
        """重建应用容器（文件变更后需要重建才能生效）"""
        self.api.post('/apps/installed/op', {'installId': app_id, 'operate': 'rebuild', 'taskID': str(uuid.uuid4())})
        time.sleep(wait)

    def create_wordpress_website(self, site: Site) -> Dict[str, Any]:
        domain = site.domain
        existed = self.get_site_id(domain)
        if existed:
            if not self.auto_clean_conflict:
                raise DomainAlreadyExistsError(domain=domain, onepanel_site_id=existed)
            self.delete_site_by_id(existed, True, True)
        wp_app = self.resolve_wp_app()
        _log.info(
            "建站诊断: domain=%s group_id=%s app_id=%s app_detail_id=%s app_type=%s app_key=%s version=%s",
            domain, self.website_group_id, wp_app['app_id'], wp_app['app_detail_id'],
            wp_app['app_type'], wp_app['app_key'], wp_app['version'],
        )
        alias = safe_alias(domain)
        app_port = random.randint(10000, 60000)
        db_suffix = hashlib.md5(f'{domain}-{time.time()}'.encode('utf-8')).hexdigest()[:8]
        db_name = f'wp_{db_suffix}'
        db_user = f'u_{db_suffix}'
        db_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(18))
        wp_admin_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(18))
        payload = {
            'alias': alias,
            'type': 'deployment',
            'webSiteGroupID': self.website_group_id,
            'appType': 'new',
            'domains': [{'domain': domain, 'port': 80}],
            'port': 80,
            'remark': 'Auto cloned WordPress',
            'appInstall': {
                'appId': wp_app['app_id'],
                'appDetailID': wp_app['app_detail_id'],
                'appDetailId': wp_app['app_detail_id'],
                'name': alias,
                'type': wp_app['app_type'],
                'version': wp_app['version'],
                'appkey': wp_app['app_key'],
                'appKey': wp_app['app_key'],
                'params': {
                    'HOST_IP': '127.0.0.1',
                    'PANEL_APP_PORT_HTTP': str(app_port),
                    'PANEL_DB_HOST': 'mysql',
                    'PANEL_DB_PORT': '3306',
                    'PANEL_DB_NAME': db_name,
                    'PANEL_DB_USER': db_user,
                    'PANEL_DB_PASSWORD': db_password,
                    'PANEL_DB_USER_PASSWORD': db_password,
                    'DATABASE_NAME': 'mysql',
                    'PANEL_DB_TYPE': 'mysql',
                    'PANEL_DB_HOST_NAME': 'mysql',
                    'format': 'utf8mb4',
                    'collation': 'utf8mb4_general_ci',
                    'PANEL_DB_FORMAT': 'utf8mb4',
                    'PANEL_DB_COLLATION': 'utf8mb4_general_ci',
                    'WORDPRESS_ADMIN_USER': self.wp_admin_user,
                    'WORDPRESS_ADMIN_PASSWORD': wp_admin_password,
                    'WORDPRESS_ADMIN_EMAIL': f'{self.wp_admin_email_prefix}@{domain}',
                },
                'advanced': True,
                'allowPort': False,
                'pullImage': False,
                'restartPolicy': 'always',
                'memoryLimit': int(ProviderResolver.sync_get_config('onepanel', 'wp_container_memory_limit', '384')),
                'memoryUnit': ProviderResolver.sync_get_config('onepanel', 'wp_container_memory_unit', '') or 'MB',
                'cpuQuota': 0,
                'containerName': f'1Panel-wordpress-{alias}',
                'specifyIP': '',
                'webUI': '',
            },
            'taskID': str(uuid.uuid4()),
        }
        ok, msg = self.api.post('/websites', payload)
        retry_count = 0
        while (not ok) and ('端口已被占用' in str(msg) or 'port is occupied' in str(msg).lower() or 'port already' in str(msg).lower()) and retry_count < 8:
            retry_count += 1
            app_port = random.randint(10000, 60000)
            payload['appInstall']['params']['PANEL_APP_PORT_HTTP'] = str(app_port)
            ok, msg = self.api.post('/websites', payload)
        if not ok:
            diag = f"group_id={self.website_group_id} app_id={wp_app['app_id']} app_detail_id={wp_app['app_detail_id']}"
            raise OnePanelError("create site", detail=f"{msg} | {diag}")
        app_info = self.wait_app_ready(alias=alias, domain=domain)
        app_info['site_id'] = self.wait_site_id(domain)
        app_info['params'] = app_info.get('params') or {}
        app_info['params'].update({'PANEL_DB_NAME': db_name, 'PANEL_DB_USER': db_user, 'PANEL_DB_PASSWORD': db_password, 'PANEL_DB_USER_PASSWORD': db_password})
        return app_info
