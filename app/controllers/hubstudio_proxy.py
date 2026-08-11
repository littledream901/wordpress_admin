"""HubStudio 代理配置控制器"""
from typing import Optional
from datetime import datetime
from fastapi import HTTPException
from tortoise.expressions import Q
import httpx
import asyncio

from app.models.hubstudio_proxy import HubStudioProxyConfig
from app.schemas.hubstudio_proxy import (
    HubStudioProxyConfigCreate,
    HubStudioProxyConfigUpdate,
    HubStudioProxyBatchImport,
    SiteBatchAssignProxy,
    ProxyBatchDelete,
    ProxyBatchCheck,
    ProxyCheckResult,
)
from app.core.crud import CRUDBase
import logging

logger = logging.getLogger(__name__)


def parse_proxy_lines(raw_text: str) -> tuple[list[dict], list[dict]]:
    """解析批量粘贴的代理文本

    格式：host:port:account:password（每行一条）
    示例：163.123.201.136:5921:powygrwn:mbe5zxysoih3

    Returns:
        (成功解析的列表, 解析失败的列表)
    """
    success, errors = [], []
    lines = [line.strip() for line in raw_text.strip().split('\n') if line.strip()]

    for idx, line in enumerate(lines, 1):
        parts = line.split(':')
        if len(parts) != 4:
            errors.append({'line': idx, 'raw': line, 'error': '格式错误，应为 host:port:account:password'})
            continue

        host, port_str, account, password = parts
        if not host or not port_str:
            errors.append({'line': idx, 'raw': line, 'error': 'host 或 port 为空'})
            continue

        try:
            port = int(port_str)
            if port <= 0 or port > 65535:
                raise ValueError('端口范围 1-65535')
        except ValueError as e:
            errors.append({'line': idx, 'raw': line, 'error': f'端口错误: {e}'})
            continue

        success.append({
            'line': idx,
            'raw': line,
            'proxy_host': host,
            'proxy_port': port,
            'proxy_account': account,
            'proxy_password': password,
        })

    return success, errors


class HubStudioProxyController(CRUDBase[HubStudioProxyConfig, HubStudioProxyConfigCreate, HubStudioProxyConfigUpdate]):
    """HubStudio 代理配置管理控制器"""

    def __init__(self):
        super().__init__(model=HubStudioProxyConfig)
    
    async def list_proxies(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str = '',
        keyword: str = '',
    ) -> tuple[int, list[dict]]:
        """获取代理配置列表（不含软删除）"""
        query = HubStudioProxyConfig.filter(is_deleted=False)
        
        if status:
            query = query.filter(status=status)
        if keyword:
            query = query.filter(
                Q(proxy_host__icontains=keyword) |
                Q(description__icontains=keyword)
            )
        
        total = await query.count()
        items = await query.offset((page - 1) * page_size).limit(page_size)
        
        # 附加分配的站点信息（每条代理只能分配一个站点）
        from app.models.site_pipeline import Site
        data = []
        for item in items:
            item_dict = await item.to_dict()
            # 获取分配的站点（理论上只会有一个）
            assigned_site = await Site.filter(proxy_config_id=item.id).first()
            if assigned_site:
                item_dict['assigned_site'] = {
                    'id': assigned_site.id,
                    'domain': assigned_site.domain,
                    'platform': assigned_site.platform
                }
            else:
                item_dict['assigned_site'] = None
            data.append(item_dict)
        
        return total, data
    
    async def get_proxy(self, proxy_id: int) -> dict:
        """获取单个代理配置"""
        proxy = await HubStudioProxyConfig.get_or_none(id=proxy_id)
        if not proxy:
            raise HTTPException(status_code=404, detail=f"代理配置 {proxy_id} 不存在")
        return await proxy.to_dict()
    
    async def create_proxy(self, data: HubStudioProxyConfigCreate) -> dict:
        """创建代理配置"""
        # 检查是否已存在相同的代理地址
        exists = await HubStudioProxyConfig.get_or_none(
            proxy_host=data.proxy_host,
            proxy_port=data.proxy_port
        )
        if exists:
            raise HTTPException(
                status_code=400, 
                detail=f"代理 {data.proxy_host}:{data.proxy_port} 已存在"
            )
        
        proxy = await HubStudioProxyConfig.create(**data.dict())
        return await proxy.to_dict()
    
    async def batch_import(self, data: HubStudioProxyBatchImport) -> dict:
        """批量导入代理配置

        解析每行 host:port:account:password，逐条落库并汇总结果。
        """
        parsed, parse_errors = parse_proxy_lines(data.raw_text)
        if not parsed and not parse_errors:
            raise HTTPException(status_code=400, detail='未解析到有效代理，请检查粘贴内容')

        success, errors = [], list(parse_errors)

        for item in parsed:
            host, port = item['proxy_host'], item['proxy_port']

            # 检查是否已存在
            dup = await HubStudioProxyConfig.filter(
                proxy_host=host, 
                proxy_port=port
            ).first()
            if dup:
                errors.append({'line': item['line'], 'raw': item['raw'], 'error': '代理已存在'})
                continue

            try:
                proxy = await HubStudioProxyConfig.create(
                    description=f'批量导入 {host}:{port}',
                    proxy_type_name=data.proxy_type_name,
                    proxy_host=host,
                    proxy_port=port,
                    proxy_account=item['proxy_account'],
                    proxy_password=item['proxy_password'],
                    reference_country_code=data.reference_country_code,
                    reference_city=data.reference_city,
                    reference_region_code=data.reference_region_code,
                    as_dynamic_type=data.as_dynamic_type,
                    ip_get_rule_type=data.ip_get_rule_type,
                    status='active',
                )
                success.append({'id': proxy.id, 'proxy': f'{host}:{port}'})
            except Exception as e:
                errors.append({'line': item['line'], 'raw': item['raw'], 'error': str(e)[:200]})

        return {
            'total': len(parsed) + len(parse_errors),
            'success_count': len(success),
            'failed_count': len(errors),
            'success': success,
            'errors': errors,
        }

    async def batch_assign_sites(self, data: SiteBatchAssignProxy) -> dict:
        """站点批量分配代理
        
        只从代理池分配代理，不再提供使用默认代理的选项
        未分配代理的站点会自动使用 HubStudio Provider 默认代理（需前端确认）
        """
        from app.models.site_pipeline import Site

        sites = await Site.filter(id__in=data.site_ids)
        if not sites:
            raise HTTPException(status_code=404, detail='未找到可分配的站点')

        # 从代理池分配：每个站点分配一条未被其他站点占用的代理
        # 本次待分配站点自身占用的代理视为可回收，避免重复分配同一批站点时误判不足
        occupied_ids = await Site.filter(proxy_config_id__gt=0).exclude(
            id__in=data.site_ids
        ).values_list('proxy_config_id', flat=True)

        available_proxies = await HubStudioProxyConfig.filter(
            status='active'
        ).exclude(id__in=list(occupied_ids)).order_by('id')

        if len(available_proxies) < len(sites):
            raise HTTPException(
                status_code=400,
                detail=f'可用代理不足：需要 {len(sites)} 条，仅有 {len(available_proxies)} 条未占用代理'
            )

        assigned = []
        for idx, site in enumerate(sites):
            proxy = available_proxies[idx]
            site.proxy_config_id = proxy.id
            await site.save(update_fields=['proxy_config_id'])
            assigned.append({
                'site_id': site.id,
                'domain': site.domain,
                'proxy_id': proxy.id,
                'proxy': f'{proxy.proxy_host}:{proxy.proxy_port}'
            })
        
        return {
            'message': f'已为 {len(assigned)} 个站点分配代理',
            'updated': len(assigned),
            'detail': assigned
        }
    
    async def update_proxy(self, data: HubStudioProxyConfigUpdate) -> dict:
        """更新代理配置"""
        proxy = await HubStudioProxyConfig.get_or_none(id=data.proxy_id)
        if not proxy:
            raise HTTPException(status_code=404, detail=f"代理配置 {data.proxy_id} 不存在")
        
        update_data = data.dict(exclude_unset=True, exclude={'proxy_id'})
        
        # 检查地址唯一性（如果修改了 host 或 port）
        if 'proxy_host' in update_data or 'proxy_port' in update_data:
            new_host = update_data.get('proxy_host', proxy.proxy_host)
            new_port = update_data.get('proxy_port', proxy.proxy_port)
            
            if new_host != proxy.proxy_host or new_port != proxy.proxy_port:
                exists = await HubStudioProxyConfig.get_or_none(
                    proxy_host=new_host,
                    proxy_port=new_port
                )
                if exists:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"代理 {new_host}:{new_port} 已存在"
                    )
        
        await proxy.update_from_dict(update_data).save()
        return await proxy.to_dict()
    
    async def delete_proxy(self, proxy_id: int):
        """删除代理配置（软删除）"""
        proxy = await HubStudioProxyConfig.get_or_none(id=proxy_id, is_deleted=False)
        if not proxy:
            raise HTTPException(status_code=404, detail=f"代理配置 {proxy_id} 不存在")
        
        # 软删除标记
        proxy.is_deleted = True
        proxy.deleted_at = datetime.now()
        await proxy.save(update_fields=['is_deleted', 'deleted_at'])
    
    async def list_options(self) -> list[dict]:
        """获取可用代理下拉选项（不含软删除）"""
        proxies = await HubStudioProxyConfig.filter(
            status='active', 
            is_deleted=False
        ).order_by('id')
        
        return [
            {
                'value': p.id,
                'label': f'{p.proxy_host}:{p.proxy_port}',
                'proxy_host': p.proxy_host,
                'proxy_port': p.proxy_port,
                'country': p.reference_country_code,
            }
            for p in proxies
        ]
    
    async def batch_delete(self, data: ProxyBatchDelete) -> dict:
        """批量软删除代理"""
        proxies = await HubStudioProxyConfig.filter(
            id__in=data.proxy_ids,
            is_deleted=False
        )
        
        if not proxies:
            raise HTTPException(status_code=404, detail='未找到可删除的代理')
        
        # 批量软删除
        now = datetime.now()
        updated = await HubStudioProxyConfig.filter(
            id__in=[p.id for p in proxies]
        ).update(is_deleted=True, deleted_at=now)
        
        return {
            'deleted_count': updated,
            'message': f'已软删除 {updated} 条代理配置'
        }
    
    async def check_proxy_connectivity(self, proxy: HubStudioProxyConfig) -> ProxyCheckResult:
        """检测单个代理连通性
        
        通过代理访问 ip-api.com 获取 IP 地理位置信息
        """
        proxy_url = f"http://{proxy.proxy_account}:{proxy.proxy_password}@{proxy.proxy_host}:{proxy.proxy_port}"
        
        start_time = datetime.now()
        try:
            transport = httpx.AsyncHTTPTransport(proxy=proxy_url)
            async with httpx.AsyncClient(transport=transport, timeout=10.0, follow_redirects=True) as client:
                # 使用 ip-api.com 获取 IP 地理位置信息
                response = await client.get("http://ip-api.com/json/?fields=status,message,country,regionName,city,timezone,query")
                response_time = (datetime.now() - start_time).total_seconds() * 1000
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # 检查 API 返回状态
                    if data.get('status') == 'success':
                        # 更新代理状态
                        proxy.status = 'active'
                        proxy.success_count += 1
                        proxy.last_used_at = datetime.now()
                        await proxy.save(update_fields=['status', 'success_count', 'last_used_at'])
                        
                        return ProxyCheckResult(
                            proxy_id=proxy.id,
                            proxy_host=proxy.proxy_host,
                            proxy_port=proxy.proxy_port,
                            status='success',
                            response_time=round(response_time, 2),
                            error_message=None,
                            detected_ip=data.get('query'),
                            detected_country=data.get('country'),
                            detected_region=data.get('regionName'),
                            detected_city=data.get('city'),
                            detected_timezone=data.get('timezone')
                        )
                    else:
                        # API 返回失败
                        error_msg = data.get('message', '未知错误')
                        proxy.status = 'disabled'
                        await proxy.save(update_fields=['status'])
                        
                        return ProxyCheckResult(
                            proxy_id=proxy.id,
                            proxy_host=proxy.proxy_host,
                            proxy_port=proxy.proxy_port,
                            status='failed',
                            response_time=round(response_time, 2),
                            error_message=f'IP检测失败: {error_msg}'
                        )
                else:
                    # HTTP 状态码错误
                    proxy.status = 'disabled'
                    await proxy.save(update_fields=['status'])
                    
                    return ProxyCheckResult(
                        proxy_id=proxy.id,
                        proxy_host=proxy.proxy_host,
                        proxy_port=proxy.proxy_port,
                        status='failed',
                        response_time=round(response_time, 2),
                        error_message=f'HTTP {response.status_code}'
                    )
                    
        except asyncio.TimeoutError:
            proxy.status = 'disabled'
            await proxy.save(update_fields=['status'])
            
            return ProxyCheckResult(
                proxy_id=proxy.id,
                proxy_host=proxy.proxy_host,
                proxy_port=proxy.proxy_port,
                status='timeout',
                response_time=None,
                error_message='连接超时'
            )
        except Exception as e:
            proxy.status = 'disabled'
            await proxy.save(update_fields=['status'])
            
            return ProxyCheckResult(
                proxy_id=proxy.id,
                proxy_host=proxy.proxy_host,
                proxy_port=proxy.proxy_port,
                status='failed',
                response_time=None,
                error_message=str(e)[:200]
            )
    
    async def check_single_proxy(self, proxy_id: int) -> ProxyCheckResult:
        """检测单条代理"""
        proxy = await HubStudioProxyConfig.get_or_none(id=proxy_id, is_deleted=False)
        if not proxy:
            raise HTTPException(status_code=404, detail=f"代理配置 {proxy_id} 不存在")
        
        # 标记为检测中
        proxy.status = 'testing'
        await proxy.save(update_fields=['status'])
        
        result = await self.check_proxy_connectivity(proxy)
        return result
    
    async def batch_check(self, data: ProxyBatchCheck) -> dict:
        """批量检测代理"""
        proxies = await HubStudioProxyConfig.filter(
            id__in=data.proxy_ids,
            is_deleted=False
        )
        
        if not proxies:
            raise HTTPException(status_code=404, detail='未找到可检测的代理')
        
        # 标记为检测中
        await HubStudioProxyConfig.filter(
            id__in=[p.id for p in proxies]
        ).update(status='testing')
        
        # 并发检测（限制并发数避免资源耗尽）
        results = []
        for i in range(0, len(proxies), 5):  # 每批5个
            batch = proxies[i:i+5]
            batch_results = await asyncio.gather(*[
                self.check_proxy_connectivity(p) for p in batch
            ])
            results.extend(batch_results)
        
        success_count = sum(1 for r in results if r.status == 'success')
        failed_count = len(results) - success_count
        
        return {
            'total': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'results': [r.dict() for r in results]
        }
    
    async def batch_unassign(self, data: ProxyBatchDelete) -> dict:
        """批量取消代理分配"""
        proxies = await HubStudioProxyConfig.filter(
            id__in=data.proxy_ids,
            is_deleted=False
        )
        
        if not proxies:
            raise HTTPException(status_code=404, detail='未找到可取消分配的代理')
        
        from app.models.site_pipeline import Site
        
        success_count = 0
        failed_count = 0
        results = []
        
        for proxy in proxies:
            try:
                # 查找使用该代理的站点
                affected_sites = await Site.filter(proxy_config_id=proxy.id).count()
                
                # 取消分配：将站点的 proxy_config_id 设为 None
                await Site.filter(proxy_config_id=proxy.id).update(
                    proxy_config_id=None,
                    updated_at=datetime.now()
                )
                
                success_count += 1
                results.append({
                    'proxy_id': proxy.id,
                    'proxy': f'{proxy.proxy_host}:{proxy.proxy_port}',
                    'status': 'success',
                    'affected_sites': affected_sites,
                    'message': f'成功取消 {affected_sites} 个站点的代理分配'
                })
                
            except Exception as e:
                failed_count += 1
                results.append({
                    'proxy_id': proxy.id,
                    'proxy': f'{proxy.proxy_host}:{proxy.proxy_port}',
                    'status': 'failed',
                    'error': str(e)
                })
                logger.error(f"取消代理 {proxy.id} 分配失败: {e}")
        
        return {
            'total': len(proxies),
            'success_count': success_count,
            'failed_count': failed_count,
            'results': results
        }
    
    async def get_assigned_sites(self, proxy_id: int) -> dict:
        """获取代理分配的站点列表"""
        proxy = await HubStudioProxyConfig.get_or_none(id=proxy_id)
        if not proxy:
            raise HTTPException(status_code=404, detail=f"代理配置 {proxy_id} 不存在")
        
        from app.models.site_pipeline import Site
        sites = await Site.filter(proxy_config_id=proxy_id).values('id', 'domain', 'platform', 'status')
        
        return {
            'proxy_id': proxy_id,
            'proxy': f'{proxy.proxy_host}:{proxy.proxy_port}',
            'sites': sites
        }
    
    async def soft_delete_by_site(self, site_id: int) -> int:
        """站点删除时联动软删除代理配置
        
        Returns:
            软删除的代理数量（0 或 1）
        """
        from app.models.site_pipeline import Site
        
        site = await Site.get_or_none(id=site_id)
        if not site or site.proxy_config_id <= 0:
            return 0
        
        proxy = await HubStudioProxyConfig.get_or_none(
            id=site.proxy_config_id,
            is_deleted=False
        )
        if not proxy:
            return 0
        
        proxy.is_deleted = True
        proxy.deleted_at = datetime.now()
        await proxy.save(update_fields=['is_deleted', 'deleted_at'])
        
        logger.info(
            f"站点删除联动：已软删除代理配置 proxy_id={proxy.id}, "
            f"host={proxy.proxy_host}:{proxy.proxy_port}, site_id={site_id}"
        )
        return 1


# 单例实例
hubstudio_proxy_controller = HubStudioProxyController()
# 回收站统一入口使用的别名
proxy_controller = hubstudio_proxy_controller
