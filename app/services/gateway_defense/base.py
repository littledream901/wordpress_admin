"""
网关防御服务基类
"""
from abc import ABC, abstractmethod
from typing import Dict, Any


class GatewayDefenseService(ABC):
    """网关防御服务基类"""
    
    @abstractmethod
    async def deploy(self, site, gateway_url: str, **kwargs) -> Dict[str, Any]:
        """
        部署网关防御
        
        Args:
            site: 站点对象
            gateway_url: 网关地址
            **kwargs: 其他参数（site_key, site_secret, fail_mode, sdk_inject等）
            
        Returns:
            {'ok': bool, 'error': str, ...}
        """
        pass
    
    @abstractmethod
    async def undeploy(self, site) -> Dict[str, Any]:
        """
        卸载网关防御
        
        Args:
            site: 站点对象
            
        Returns:
            {'ok': bool, 'error': str, ...}
        """
        pass
    
    @abstractmethod
    async def check_status(self, site) -> Dict[str, Any]:
        """
        检查部署状态
        
        Args:
            site: 站点对象
            
        Returns:
            {'ok': bool, 'status': str, ...}
        """
        pass
