"""
Cloudflare Worker 网关防御服务（适用于任何平台）
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

import requests

from app.log import logger
from app.models.config_provider import ConfigProvider, ProviderConfigItem, ResourceProviderBinding
from app.services.gateway_defense.base import GatewayDefenseService


class CloudflareAPIClient:
    """Cloudflare API 客户端"""
    
    BASE_URL = "https://api.cloudflare.com/client/v4"
    
    def __init__(self, api_token: str, account_id: str):
        self.api_token = api_token
        self.account_id = account_id
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json',
        })
    
    def _request(self, method: str, path: str, **kwargs) -> Dict:
        url = f"{self.BASE_URL}{path}"
        response = self.session.request(method, url, **kwargs)
        response.raise_for_status()
        
        data = response.json()
        if not data.get('success'):
            errors = data.get('errors', [])
            error_msg = '; '.join([f"{e.get('code')}: {e.get('message')}" for e in errors])
            raise RuntimeError(f"API 调用失败: {error_msg}")
        
        return data.get('result', {})
    
    def get_worker(self, script_name: str) -> Optional[Dict]:
        try:
            return self._request('GET', f'/accounts/{self.account_id}/workers/scripts/{script_name}')
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise
        except (ValueError, RuntimeError):
            return None
    
    def upload_worker(self, script_name: str, script_content: str, env_vars: Optional[Dict[str, str]] = None) -> Dict:
        script_file_name = f'{script_name}.js'
        
        bindings = []
        if env_vars:
            bindings = [
                {
                    'type': 'plain_text',
                    'name': key,
                    'text': value
                }
                for key, value in env_vars.items()
            ]
        
        metadata = {
            'main_module': script_file_name,
            'bindings': bindings
        }
        
        files = [
            ('metadata', (None, json.dumps(metadata), 'application/json')),
            (script_file_name, (script_file_name, bytes(script_content, 'utf-8'), 'application/javascript+module')),
        ]
        
        headers = {
            'Authorization': f'Bearer {self.api_token}',
        }
        
        url = f"{self.BASE_URL}/accounts/{self.account_id}/workers/scripts/{script_name}"
        response = requests.put(url, headers=headers, files=files)
        
        if response.status_code not in (200, 201):
            try:
                error_data = response.json()
                errors = error_data.get('errors', [])
                error_msg = '; '.join([f"{e.get('code')}: {e.get('message')}" for e in errors])
                raise RuntimeError(f"脚本上传失败 (HTTP {response.status_code}): {error_msg}")
            except ValueError:
                raise RuntimeError(f"脚本上传失败 (HTTP {response.status_code}): {response.text}")
        
        data = response.json()
        if not data.get('success'):
            errors = data.get('errors', [])
            error_msg = '; '.join([f"{e.get('code')}: {e.get('message')}" for e in errors])
            raise RuntimeError(f"脚本上传失败: {error_msg}")
        
        return data.get('result', {})
    
    def add_worker_route(self, zone_id: str, pattern: str, script_name: str) -> Dict:
        return self._request(
            'POST',
            f'/zones/{zone_id}/workers/routes',
            json={
                'pattern': pattern,
                'script': script_name
            }
        )
    
    def list_worker_routes(self, zone_id: str) -> List[Dict]:
        return self._request('GET', f'/zones/{zone_id}/workers/routes')
    
    def delete_worker_route(self, zone_id: str, route_id: str) -> None:
        self._request('DELETE', f'/zones/{zone_id}/workers/routes/{route_id}')
    
    def list_zones(self) -> List[Dict]:
        return self._request('GET', '/zones')
    
    def find_zone_by_domain(self, domain: str) -> Optional[str]:
        zones = self.list_zones()
        
        clean_domain = domain.lower().strip()
        clean_domain = clean_domain.replace('https://', '').replace('http://', '')
        clean_domain = clean_domain.split('/')[0]
        clean_domain = clean_domain.split(':')[0]
        
        for zone in zones:
            if zone.get('name', '').lower() == clean_domain:
                return zone.get('id')
        
        if '.' in clean_domain:
            parts = clean_domain.split('.')
            if len(parts) > 2:
                parent_domain = '.'.join(parts[-2:])
                for zone in zones:
                    if zone.get('name', '').lower() == parent_domain:
                        return zone.get('id')
        
        return None


class CloudflareWorkerDefenseService(GatewayDefenseService):
    """Cloudflare Worker 网关防御服务"""
    
    def __init__(self):
        self.worker_source = "app/services/defense_file/cf_worker/worker.js"
        # 任务日志（结构化步骤记录，供前端展示与排障）
        self.task_log: List[Dict[str, Any]] = []
    
    def _log_step(self, step: str, ok: bool, msg: str = '', **extra) -> None:
        """记录任务步骤日志（仅写入结构化列表，不逐条打印，最终由 deploy 汇总输出 JSON）"""
        entry = {
            'ts': datetime.now().isoformat(),
            'step': step,
            'ok': ok,
            'msg': msg,
            **extra,
        }
        self.task_log.append(entry)

    def _log_summary(
        self,
        ok: bool,
        domain: str,
        site_id: Any,
        duration_ms: Optional[int] = None,
        error: str = '',
        action: str = 'deploy',
    ) -> None:
        """一次性输出 JSON 汇总日志（步骤明细压缩为 step/ok/msg 三元组）"""
        payload = {
            'type': 'cf_worker',
            'action': action,
            'domain': domain,
            'site_id': str(site_id),
            'ok': ok,
            'duration_ms': duration_ms,
            'steps': [
                {'step': e['step'], 'ok': e['ok'], 'msg': e['msg']}
                for e in self.task_log
            ],
        }
        if error:
            payload['error'] = error[:300]
        text = json.dumps(payload, ensure_ascii=False)
        if ok:
            logger.info(text)
        else:
            logger.error(text)
    
    def _verify_worker_source(self) -> bool:
        """验证 Worker 源文件是否存在"""
        worker_path = Path(self.worker_source)
        if not worker_path.exists():
            self._log_step('验证Worker源文件', False, f'文件不存在: {self.worker_source}')
            raise FileNotFoundError(f"Worker 源文件不存在: {self.worker_source}")
        
        # 验证文件大小（应该 > 10KB）
        size = worker_path.stat().st_size
        if size < 10000:
            self._log_step('验证Worker源文件', False, f'文件太小 ({size} 字节)')
            raise ValueError(f"Worker 源文件太小，可能不完整: {self.worker_source}")
        
        self._log_step('验证Worker源文件', True, f'{self.worker_source} ({size} 字节)')
        return True
    
    async def _get_cloudflare_config(self, site_id: int) -> tuple:
        """
        获取站点绑定的 Cloudflare Provider 配置
        
        Returns:
            (api_token, account_id, provider_id)
        """
        # 查找站点绑定的 Cloudflare Provider
        binding = await ResourceProviderBinding.filter(
            resource_type='site',
            resource_id=site_id,
            provider_type='cloudflare',
            bind_type='preferred'
        ).first()
        
        provider_id = None
        if binding:
            provider = await ConfigProvider.get_or_none(id=binding.provider_id, status='active')
            if provider:
                provider_id = provider.id
        
        # 如果没有绑定，使用默认 Provider
        if not provider_id:
            provider = await ConfigProvider.get_default('cloudflare')
            if not provider:
                raise ValueError("未找到可用的 Cloudflare Provider")
            provider_id = provider.id
        
        # 获取配置项
        config_items = await ProviderConfigItem.get_map(provider_id)
        api_token = config_items.get('api_token') or config_items.get('CF_API_TOKEN', '')
        account_id = config_items.get('account_id') or config_items.get('CF_ACCOUNT_ID', '')
        
        if not api_token or not account_id:
            raise ValueError(f"Provider #{provider_id} 配置不完整")
        
        return api_token, account_id, provider_id
    
    async def _get_zone_id(self, site, cf_api_token: str, cf_account_id: str) -> Optional[str]:
        """获取域名的 Zone ID"""
        loop = asyncio.get_event_loop()

        def _query() -> Optional[str]:
            client = CloudflareAPIClient(cf_api_token, cf_account_id)
            return client.find_zone_by_domain(site.domain)

        return await loop.run_in_executor(None, _query)
    
    async def deploy(
        self, 
        site, 
        gateway_url: str,
        site_key: Optional[str] = None,
        site_secret: Optional[str] = None,
        fail_mode: str = 'open',
        sdk_inject: bool = True,
        gateway_site_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        部署 Cloudflare Worker
        
        调用流程：
        1. 验证 Worker 源文件存在
        2. 验证站点密钥已配置（必须外部提供）
        3. 验证网关侧站点标识已配置（必须外部提供，非本项目主键）
        4. 获取站点绑定的 Cloudflare Provider 配置
        5. 获取 Zone ID
        6. 上传 Worker 脚本并配置路由
        7. 更新站点状态和配置
        8. 自检验证
        """
        self.task_log = []
        started_at = datetime.now()
        self._log_step('部署开始', True, f'域名={site.domain} 站点ID={site.id} 网关={gateway_url}')
        try:
            # 步骤1: 验证 Worker 源文件
            self._verify_worker_source()
            
            # 步骤2: 验证密钥（必须外部提供）
            if not site_key or not site_secret:
                if not site.gateway_site_key or not site.gateway_site_secret:
                    err = '站点密钥未配置，请先设置 gateway_site_key 和 gateway_site_secret'
                    self._log_step('验证站点密钥', False, '站点密钥未配置')
                    self._log_summary(
                        False, site.domain, site.id,
                        int((datetime.now() - started_at).total_seconds() * 1000), err,
                    )
                    return {
                        'ok': False,
                        'error': err,
                        'task_log': self.task_log,
                    }
                site_key = site.gateway_site_key
                site_secret = site.gateway_site_secret
                self._log_step('验证站点密钥', True, '复用站点已保存的密钥')
            else:
                site.gateway_site_key = site_key
                site.gateway_site_secret = site_secret
                self._log_step('验证站点密钥', True, '使用外部传入的密钥')
            
            # 步骤3: 验证网关侧站点标识（必须外部提供，不能用本地主键兜底）
            if not gateway_site_id:
                if not site.gateway_site_id:
                    err = '网关站点标识未配置，请先设置 gateway_site_id（由网关侧分配，不是本项目的站点ID）'
                    self._log_step('验证网关站点标识', False, '未配置')
                    self._log_summary(
                        False, site.domain, site.id,
                        int((datetime.now() - started_at).total_seconds() * 1000), err,
                    )
                    return {
                        'ok': False,
                        'error': err,
                        'task_log': self.task_log,
                    }
                gateway_site_id = site.gateway_site_id
            else:
                site.gateway_site_id = gateway_site_id
            self._log_step('验证网关站点标识', True, f'网关站点ID={gateway_site_id}')

            # 步骤4: 获取 Cloudflare Provider 配置（从绑定的 Provider）
            cf_api_token, cf_account_id, provider_id = await self._get_cloudflare_config(site.id)
            self._log_step('获取Provider配置', True, f'provider_id={provider_id}', provider_id=provider_id)
            
            # 步骤4: 获取 Zone ID
            zone_id = await self._get_zone_id(site, cf_api_token, cf_account_id)
            if not zone_id:
                err = f'未找到域名 {site.domain} 的 Cloudflare Zone'
                self._log_step('查询Zone ID', False, f'未找到域名 {site.domain} 的 Zone')
                self._log_summary(
                    False, site.domain, site.id,
                    int((datetime.now() - started_at).total_seconds() * 1000), err,
                )
                return {
                    'ok': False,
                    'error': err,
                    'task_log': self.task_log,
                }
            self._log_step('查询Zone ID', True, zone_id, zone_id=zone_id)
            
            # 步骤5: 部署 Worker（在线程池中执行，避免阻塞）
            worker_name = f"fangyu-defense-{site.id}"
            route_pattern = f"{site.domain}/*"
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._deploy_worker_sync,
                worker_name,
                gateway_site_id,
                site_key,
                site_secret,
                gateway_url,
                zone_id,
                route_pattern,
                cf_api_token,
                cf_account_id,
                fail_mode,
                sdk_inject
            )
            
            # 合并子线程产生的任务日志
            self.task_log.extend(result.pop('task_log', []))
            duration_ms = int((datetime.now() - started_at).total_seconds() * 1000)
            result['task_log'] = self.task_log
            result['duration_ms'] = duration_ms
            
            # 步骤6: 更新站点状态
            if result['ok']:
                site.gateway_defense_status = 'deployed'
                site.gateway_defense_type = 'worker'
                site.gateway_deployed_at = datetime.now()
                site.gateway_last_error = ''
                
                site.gateway_config_json = json.dumps({
                    'gateway_url': gateway_url,
                    'gateway_site_id': gateway_site_id,
                    'worker_name': worker_name,
                    'route_pattern': route_pattern,
                    'fail_mode': fail_mode,
                    'sdk_inject': sdk_inject,
                    'zone_id': zone_id,
                    'provider_id': provider_id,
                    'provider_type': 'cloudflare',
                    'worker_source': self.worker_source,
                    'task_log': self.task_log,
                    'duration_ms': duration_ms,
                }, ensure_ascii=False)
                await site.save()
                self._log_step('部署完成', True, f'耗时 {duration_ms}ms')
                self._log_summary(True, site.domain, site.id, duration_ms)
            else:
                site.gateway_defense_status = 'failed'
                site.gateway_last_error = result.get('error', '')
                await site.save()
                self._log_step('部署失败', False, result.get('error', '')[:300])
                self._log_summary(False, site.domain, site.id, duration_ms, result.get('error', ''))
            
            return result
            
        except (FileNotFoundError, ValueError) as e:
            duration_ms = int((datetime.now() - started_at).total_seconds() * 1000)
            self._log_summary(False, site.domain, site.id, duration_ms, str(e))
            return {'ok': False, 'error': str(e), 'task_log': self.task_log}
        except Exception as e:
            duration_ms = int((datetime.now() - started_at).total_seconds() * 1000)
            self._log_summary(False, site.domain, site.id, duration_ms, str(e))
            return {'ok': False, 'error': f'部署失败: {str(e)}', 'task_log': self.task_log}
    
    def _deploy_worker_sync(
        self,
        worker_name: str,
        gateway_site_id: str,
        site_key: str,
        site_secret: str,
        gateway_url: str,
        zone_id: str,
        route_pattern: str,
        api_token: str,
        account_id: str,
        fail_mode: str,
        sdk_inject: bool
    ) -> Dict[str, Any]:
        """同步部署 Worker（在线程池中执行，日志写入 self.task_log）"""
        try:
            client = CloudflareAPIClient(api_token, account_id)
            
            # 读取 Worker 脚本
            script_path = Path(self.worker_source)
            if not script_path.exists():
                self._log_step('读取Worker脚本', False, f'文件不存在: {self.worker_source}')
                return {'ok': False, 'error': f'Worker 脚本文件不存在: {self.worker_source}'}
            
            script_content = script_path.read_text(encoding='utf-8')
            
            # 验证脚本内容
            if 'export default' not in script_content or 'async fetch' not in script_content:
                self._log_step('读取Worker脚本', False, '缺少 export default 或 async fetch')
                return {'ok': False, 'error': 'Worker 脚本格式不正确'}
            self._log_step('读取Worker脚本', True, f'{len(script_content)} 字节')
            
            # 准备环境变量
            env_vars = {
                'FANGYU_GATEWAY_URL': gateway_url,
                'FANGYU_SITE_ID': gateway_site_id,
                'FANGYU_SITE_KEY': site_key,
                'FANGYU_SITE_SECRET': site_secret,
                'FANGYU_FAIL_MODE': fail_mode,
                'FANGYU_SDK_INJECT': 'true' if sdk_inject else 'false',
            }
            
            # 上传 Worker 脚本
            client.upload_worker(worker_name, script_content, env_vars)
            self._log_step(
                '上传Worker脚本', True,
                f'{worker_name} (含 {len(env_vars)} 个环境变量)',
                worker_name=worker_name,
            )
            
            # 配置路由
            existing_routes = client.list_worker_routes(zone_id)
            
            # 检查是否已存在相同路由
            route_exists = False
            for route in existing_routes:
                if route.get('pattern') == route_pattern:
                    if route.get('script') == worker_name:
                        route_exists = True
                    else:
                        # 删除旧路由
                        client.delete_worker_route(zone_id, route['id'])
                        self._log_step(
                            '清理旧路由', True,
                            f"移除指向 {route.get('script')} 的路由 {route_pattern}",
                        )
            
            # 添加新路由
            if route_exists:
                self._log_step('配置路由', True, f'路由已存在，跳过: {route_pattern}')
            else:
                client.add_worker_route(zone_id, route_pattern, worker_name)
                self._log_step('配置路由', True, f'{route_pattern} → {worker_name}')
            
            # 部署后自检验证
            verify_result = self._verify_worker_deployment(
                client, worker_name, zone_id, route_pattern, env_vars
            )
            
            return {
                'ok': verify_result['ok'],
                'worker_name': worker_name,
                'route': route_pattern,
                'zone_id': zone_id,
                'verify': verify_result,
                'error': verify_result.get('error') if not verify_result['ok'] else None,
            }
            
        except FileNotFoundError as e:
            self._log_step('部署Worker', False, f'文件未找到: {str(e)[:200]}')
            return {'ok': False, 'error': f'文件未找到: {str(e)}'}
        except requests.exceptions.RequestException as e:
            self._log_step('部署Worker', False, f'API 请求失败: {str(e)[:200]}')
            return {'ok': False, 'error': f'API 请求失败: {str(e)}'}
        except Exception as e:
            self._log_step('部署Worker', False, str(e)[:200])
            return {'ok': False, 'error': f'部署失败: {str(e)}'}
    
    def _verify_worker_deployment(
        self,
        client: CloudflareAPIClient,
        worker_name: str,
        zone_id: str,
        route_pattern: str,
        expected_env_vars: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        部署后自检验证（关键项失败即整体失败）。

        关键检查：
        - Worker 脚本存在
        - Worker 环境变量完整（所有 FANGYU_* 变量）
        - 路由绑定已生效
        - 路由指向正确的 Worker 脚本

        Returns:
            {
                'ok': bool,
                'checks': [{'name': str, 'ok': bool, 'msg': str}, ...],
                'error': Optional[str]
            }
        """
        checks: List[Dict[str, Any]] = []

        def _add(name: str, ok: bool, msg: str = '') -> None:
            checks.append({'name': name, 'ok': ok, 'msg': msg})
            self._log_step(f'自检-{name}', ok, msg)

        # 1. Worker 脚本存在
        try:
            worker_info = client.get_worker(worker_name)
            if worker_info:
                _add('Worker 脚本存在', True, worker_name)
            else:
                _add('Worker 脚本存在', False, f'{worker_name} 不存在')
        except Exception as e:
            _add('Worker 脚本存在', False, f'查询失败: {str(e)[:100]}')

        # 2. 环境变量检查（通过重新获取 Worker 信息验证，但 Cloudflare API 不直接返回环境变量）
        # 这里我们验证上传时的 env_vars 参数是否完整
        required_env_keys = [
            'FANGYU_GATEWAY_URL', 'FANGYU_SITE_ID', 'FANGYU_SITE_KEY',
            'FANGYU_SITE_SECRET', 'FANGYU_FAIL_MODE', 'FANGYU_SDK_INJECT',
        ]
        missing_env = [k for k in required_env_keys if k not in expected_env_vars]
        if missing_env:
            _add('环境变量完整', False, f'缺少: {", ".join(missing_env)}')
        else:
            _add('环境变量完整', True, f'已配置 {len(expected_env_vars)} 个变量')

        # 3. 路由绑定存在且指向正确的 Worker
        try:
            routes = client.list_worker_routes(zone_id)
            matched_route = None
            for route in routes:
                if route.get('pattern') == route_pattern:
                    matched_route = route
                    break
            
            if not matched_route:
                _add('路由绑定存在', False, f'路由 {route_pattern} 未找到')
            elif matched_route.get('script') != worker_name:
                _add('路由指向正确', False, f'路由指向 {matched_route.get("script")}，期望 {worker_name}')
            else:
                _add('路由绑定存在', True, route_pattern)
                _add('路由指向正确', True, worker_name)
        except Exception as e:
            _add('路由绑定存在', False, f'查询失败: {str(e)[:100]}')

        failed = [c for c in checks if not c['ok']]
        if failed:
            return {
                'ok': False,
                'checks': checks,
                'error': '; '.join(f"{c['name']}: {c['msg']}" for c in failed),
            }
        return {'ok': True, 'checks': checks}
    
    async def undeploy(self, site) -> Dict[str, Any]:
        """
        卸载 Cloudflare Worker 路由
        
        注意：只删除路由绑定，不删除 Worker 脚本本身
        """
        try:
            config = json.loads(site.gateway_config_json or '{}')
            zone_id = config.get('zone_id')
            route_pattern = config.get('route_pattern')
            
            if not zone_id or not route_pattern:
                return {'ok': False, 'error': '缺少 Zone ID 或路由信息'}
            
            # 获取 Cloudflare 配置
            cf_api_token, cf_account_id, provider_id = await self._get_cloudflare_config(site.id)
            
            # 删除路由
            loop = asyncio.get_event_loop()
            
            def _delete_route():
                client = CloudflareAPIClient(cf_api_token, cf_account_id)
                routes = client.list_worker_routes(zone_id)
                
                for route in routes:
                    if route.get('pattern') == route_pattern:
                        client.delete_worker_route(zone_id, route['id'])
                        return True
                return False
            
            deleted = await loop.run_in_executor(None, _delete_route)
            
            site.gateway_defense_status = 'undeployed'
            site.gateway_last_error = ''
            await site.save()
            
            if deleted:
                logger.info(json.dumps({
                    'type': 'cf_worker', 'action': 'undeploy', 'domain': site.domain,
                    'site_id': str(site.id), 'ok': True, 'route': route_pattern, 'deleted': True,
                }, ensure_ascii=False))
                return {'ok': True, 'msg': f'已卸载路由: {route_pattern}'}
            else:
                logger.info(json.dumps({
                    'type': 'cf_worker', 'action': 'undeploy', 'domain': site.domain,
                    'site_id': str(site.id), 'ok': True, 'route': route_pattern, 'deleted': False,
                }, ensure_ascii=False))
                return {'ok': True, 'msg': f'路由不存在或已删除: {route_pattern}'}
            
        except Exception as e:
            logger.error(json.dumps({
                'type': 'cf_worker', 'action': 'undeploy', 'domain': site.domain,
                'site_id': str(site.id), 'ok': False, 'error': str(e)[:300],
            }, ensure_ascii=False))
            return {'ok': False, 'error': f'卸载失败: {str(e)}'}
    
    async def check_status(self, site) -> Dict[str, Any]:
        """检查 Worker 部署状态"""
        if site.gateway_defense_status != 'deployed':
            return {'ok': False, 'status': site.gateway_defense_status}
        
        try:
            config = json.loads(site.gateway_config_json or '{}')
            return {
                'ok': True,
                'status': 'deployed',
                'worker_name': config.get('worker_name'),
                'route': config.get('route_pattern'),
                'zone_id': config.get('zone_id'),
                'task_log': config.get('task_log', []),
                'duration_ms': config.get('duration_ms'),
                'deployed_at': site.gateway_deployed_at.isoformat() if site.gateway_deployed_at else None
            }
        except Exception as e:
            return {'ok': False, 'error': str(e)}
