#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloudflare Worker 自动部署脚本

用于自动部署 Fangyu Defense Worker 到 Cloudflare，支持：
- Worker 脚本上传
- 环境变量配置
- 自定义域名绑定
- 路由规则配置
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Windows 终端编码修复
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


class Colors:
    """ANSI 颜色代码常量"""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'


class Logger:
    """控制台日志输出工具类（带颜色标记）"""
    
    @staticmethod
    def step(msg: str) -> None:
        """输出步骤信息（蓝色）"""
        print(f"{Colors.BLUE}[步骤]{Colors.END} {msg}")

    @staticmethod
    def success(msg: str) -> None:
        """输出成功信息（绿色）"""
        print(f"{Colors.GREEN}[成功]{Colors.END} {msg}")

    @staticmethod
    def warning(msg: str) -> None:
        """输出警告信息（黄色）"""
        print(f"{Colors.YELLOW}[警告]{Colors.END} {msg}")

    @staticmethod
    def error(msg: str) -> None:
        """输出错误信息（红色）"""
        print(f"{Colors.RED}[错误]{Colors.END} {msg}")


class CloudflareAPIClient:
    """Cloudflare API 客户端"""
    
    BASE_URL = "https://api.cloudflare.com/client/v4"
    
    def __init__(self, api_token: str, account_id: str):
        """
        初始化 Cloudflare API 客户端。
        
        Args:
            api_token: Cloudflare API Token（需要 Workers Scripts:Edit 权限）
            account_id: Cloudflare Account ID
        """
        self.api_token = api_token
        self.account_id = account_id
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json',
        })
    
    def _request(self, method: str, path: str, **kwargs) -> Dict:
        """
        发送 API 请求。
        
        Args:
            method: HTTP 方法
            path: API 路径
            **kwargs: requests 参数
            
        Returns:
            API 响应数据
            
        Raises:
            requests.exceptions.RequestException: 请求失败
        """
        url = f"{self.BASE_URL}{path}"
        response = self.session.request(method, url, **kwargs)
        response.raise_for_status()
        
        data = response.json()
        if not data.get('success'):
            errors = data.get('errors', [])
            error_msg = '; '.join([f"{e.get('code')}: {e.get('message')}" for e in errors])
            raise RuntimeError(f"API 调用失败: {error_msg}")
        
        return data.get('result', {})
    
    def list_workers(self) -> List[Dict]:
        """列出所有 Worker 脚本"""
        return self._request('GET', f'/accounts/{self.account_id}/workers/scripts')
    
    def get_worker(self, script_name: str) -> Optional[Dict]:
        """
        获取 Worker 脚本信息
        
        Args:
            script_name: Worker 名称
            
        Returns:
            Worker 信息，如果不存在返回 None
        """
        try:
            return self._request('GET', f'/accounts/{self.account_id}/workers/scripts/{script_name}')
        except requests.exceptions.HTTPError as e:
            # 404 表示 Worker 不存在
            if e.response.status_code == 404:
                return None
            raise
        except (ValueError, RuntimeError):
            # JSON 解析失败或 API 调用失败，可能是 Worker 不存在
            return None
    
    def upload_worker(self, script_name: str, script_content: str, env_vars: Optional[Dict[str, str]] = None) -> Dict:
        """
        上传 Worker 脚本
        
        Args:
            script_name: Worker 名称
            script_content: Worker 脚本内容
            env_vars: 环境变量字典（可选）
            
        Returns:
            上传响应数据
            
        Raises:
            RuntimeError: 上传失败时抛出
        """
        # 按照 Cloudflare 官方示例构建 multipart/form-data
        # 参考: https://github.com/cloudflare/cloudflare-python/blob/main/examples/workers/script_upload.py
        script_file_name = f'{script_name}.js'
        
        # 构建 metadata，包含 bindings（环境变量）
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
        
        # files 必须是列表格式，每个元素是 tuple: (field_name, (filename, content, content_type))
        # 对于 ES Module，Content-Type 必须是 application/javascript+module
        files = [
            ('metadata', (None, json.dumps(metadata), 'application/json')),
            (script_file_name, (script_file_name, bytes(script_content, 'utf-8'), 'application/javascript+module')),
        ]
        
        headers = {
            'Authorization': f'Bearer {self.api_token}',
        }
        
        url = f"{self.BASE_URL}/accounts/{self.account_id}/workers/scripts/{script_name}"
        
        # 不使用 session，直接用 requests.put
        response = requests.put(url, headers=headers, files=files)
        
        # 检查响应
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
    
    def set_worker_env_vars(self, script_name: str, env_vars: Dict[str, str]) -> Dict:
        """
        设置 Worker 环境变量。
        
        Args:
            script_name: Worker 名称
            env_vars: 环境变量字典
            
        Returns:
            API 响应
        """
        bindings = [
            {
                'type': 'plain_text',
                'name': key,
                'text': value
            }
            for key, value in env_vars.items()
        ]
        
        return self._request(
            'PATCH',
            f'/accounts/{self.account_id}/workers/scripts/{script_name}/settings',
            json={'bindings': bindings}
        )
    
    def add_worker_route(self, zone_id: str, pattern: str, script_name: str) -> Dict:
        """
        添加 Worker 路由。
        
        Args:
            zone_id: Cloudflare Zone ID（域名）
            pattern: 路由模式（如 example.com/*）
            script_name: Worker 名称
            
        Returns:
            API 响应
        """
        return self._request(
            'POST',
            f'/zones/{zone_id}/workers/routes',
            json={
                'pattern': pattern,
                'script': script_name
            }
        )
    
    def list_worker_routes(self, zone_id: str) -> List[Dict]:
        """列出 Worker 路由"""
        return self._request('GET', f'/zones/{zone_id}/workers/routes')
    
    def delete_worker_route(self, zone_id: str, route_id: str) -> None:
        """删除 Worker 路由"""
        self._request('DELETE', f'/zones/{zone_id}/workers/routes/{route_id}')
    
    def list_zones(self) -> List[Dict]:
        """列出所有 Zone（域名）"""
        return self._request('GET', '/zones')
    
    def find_zone_by_domain(self, domain: str) -> Optional[str]:
        """
        根据域名查找 Zone ID。
        
        Args:
            domain: 域名（如 example.com）
            
        Returns:
            Zone ID，未找到返回 None
        """
        zones = self.list_zones()
        
        # 移除域名中的协议、路径等
        clean_domain = domain.lower().strip()
        clean_domain = clean_domain.replace('https://', '').replace('http://', '')
        clean_domain = clean_domain.split('/')[0]  # 移除路径
        clean_domain = clean_domain.split(':')[0]  # 移除端口
        
        # 查找精确匹配
        for zone in zones:
            if zone.get('name', '').lower() == clean_domain:
                return zone.get('id')
        
        # 查找父域名（如 shop.example.com → example.com）
        if '.' in clean_domain:
            parts = clean_domain.split('.')
            if len(parts) > 2:
                # 尝试查找父域名
                parent_domain = '.'.join(parts[-2:])
                for zone in zones:
                    if zone.get('name', '').lower() == parent_domain:
                        return zone.get('id')
        
        return None


class CloudflareWorkerDeployer:
    """Cloudflare Worker 部署器"""
    
    def __init__(self, api_client: CloudflareAPIClient):
        self.api_client = api_client
    
    def _resolve_zone_id(self, zone_id: Optional[str], route_pattern: Optional[str]) -> Optional[str]:
        """
        解析 Zone ID。
        
        如果 zone_id 为 None 但 route_pattern 包含域名，尝试自动查找。
        
        Args:
            zone_id: 用户提供的 Zone ID
            route_pattern: 路由模式（可能包含域名）
            
        Returns:
            解析后的 Zone ID
        """
        if zone_id:
            return zone_id
        
        if not route_pattern:
            return None
        
        # 从路由模式中提取域名
        # 支持格式: example.com/*, *.example.com/*, https://example.com/*
        domain = route_pattern.split('/')[0]
        domain = domain.replace('*', '').replace('.', '.').strip('.')
        
        if not domain or domain == '*':
            return None
        
        Logger.step(f"从路由模式提取域名: {domain}")
        Logger.step("自动查找 Zone ID...")
        
        found_zone_id = self.api_client.find_zone_by_domain(domain)
        if found_zone_id:
            Logger.success(f"[OK] 找到 Zone ID: {found_zone_id}")
            return found_zone_id
        else:
            Logger.warning(f"未找到域名 {domain} 对应的 Zone")
            return None
    
    def deploy(
        self,
        script_name: str,
        script_path: str,
        gateway_url: str,
        site_key: str,
        site_secret: str,
        zone_id: Optional[str] = None,
        route_pattern: Optional[str] = None,
        fail_mode: str = 'open',
        sdk_inject: bool = True
    ) -> bool:
        """
        部署 Worker 到 Cloudflare。
        
        Args:
            script_name: Worker 名称
            script_path: Worker 脚本文件路径
            gateway_url: Fangyu 网关 URL
            site_key: Fangyu 站点密钥（格式：site_xxxxxxxx）
            site_secret: Fangyu 站点签名密钥
            zone_id: Cloudflare Zone ID（可选，用于绑定路由）
            route_pattern: 路由模式（可选）
            fail_mode: 失败模式（open/closed）
            sdk_inject: 是否注入 SDK
            
        Returns:
            True 表示成功，False 表示失败
        """
        try:
            Logger.step("=" * 80)
            Logger.step(f"开始部署 Cloudflare Worker: {script_name}")
            Logger.step("=" * 80)
            print()
            
            # 1. 读取 Worker 脚本
            Logger.step("读取 Worker 脚本...")
            script_content = self._read_script(script_path)
            Logger.success(f"[OK] 脚本大小: {len(script_content):,} 字节")
            
            # 2. 检查是否已存在
            Logger.step("检查 Worker 是否已存在...")
            existing = self.api_client.get_worker(script_name)
            if existing:
                Logger.warning(f"Worker '{script_name}' 已存在，将更新")
            else:
                Logger.success(f"Worker '{script_name}' 不存在，将创建新 Worker")
            
            # 3. 准备环境变量
            Logger.step("准备环境变量...")
            env_vars = {
                'FANGYU_GATEWAY_URL': gateway_url,
                'FANGYU_SITE_KEY': site_key,
                'FANGYU_SITE_SECRET': site_secret,
                'FANGYU_FAIL_MODE': fail_mode,
                'FANGYU_SDK_INJECT': 'true' if sdk_inject else 'false',
            }
            Logger.success(f"[OK] 环境变量已准备 ({len(env_vars)} 个)")
            
            # 4. 上传 Worker 脚本（包含环境变量）
            Logger.step("上传 Worker 脚本...")
            self.api_client.upload_worker(script_name, script_content, env_vars)
            Logger.success(f"[OK] Worker 脚本已上传")
            
            # 5. 解析 Zone ID
            resolved_zone_id = self._resolve_zone_id(zone_id, route_pattern)
            
            # 6. 配置路由（如果可以解析）
            if resolved_zone_id and route_pattern:
                Logger.step("配置 Worker 路由...")
                self._configure_route(resolved_zone_id, route_pattern, script_name)
            elif route_pattern and not resolved_zone_id:
                Logger.warning("⚠️ 未提供 Zone ID 且无法自动查找，跳过路由配置")
            
            print()
            Logger.success("=" * 80)
            Logger.success(f"✅ Worker '{script_name}' 部署成功！")
            Logger.success("=" * 80)
            print()
            
            self._print_next_steps(script_name, zone_id, route_pattern)
            
            return True
            
        except FileNotFoundError as e:
            Logger.error(f"文件未找到: {e}")
            return False
        except requests.exceptions.RequestException as e:
            Logger.error(f"API 请求失败: {e}")
            return False
        except Exception as e:
            Logger.error(f"部署失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _read_script(self, script_path: str) -> str:
        """读取 Worker 脚本文件"""
        path = Path(script_path)
        if not path.exists():
            raise FileNotFoundError(f"脚本文件不存在: {script_path}")
        
        content = path.read_text(encoding='utf-8')
        
        # 验证基本语法（简单检查）
        if 'export default' not in content:
            raise ValueError("Worker 脚本必须包含 'export default' 导出")
        
        if 'async fetch' not in content:
            raise ValueError("Worker 脚本必须包含 'async fetch' 方法")
        
        return content
    
    def _configure_route(self, zone_id: str, pattern: str, script_name: str) -> None:
        """配置 Worker 路由"""
        # 检查是否已存在相同的路由
        existing_routes = self.api_client.list_worker_routes(zone_id)
        
        for route in existing_routes:
            if route.get('pattern') == pattern:
                if route.get('script') == script_name:
                    Logger.success(f"[OK] 路由已存在: {pattern}")
                    return
                else:
                    Logger.warning(f"路由 {pattern} 已绑定到其他 Worker: {route.get('script')}")
                    Logger.warning("删除旧路由...")
                    self.api_client.delete_worker_route(zone_id, route['id'])
        
        # 添加新路由
        self.api_client.add_worker_route(zone_id, pattern, script_name)
        Logger.success(f"[OK] 路由已配置: {pattern}")
    
    def _print_next_steps(self, script_name: str, zone_id: Optional[str], route_pattern: Optional[str]) -> None:
        """打印后续步骤"""
        print("后续步骤:")
        print()
        
        if not zone_id or not route_pattern:
            print("1. 在 Cloudflare Dashboard 中配置路由:")
            print(f"   https://dash.cloudflare.com/?to=/:account/workers/{script_name}")
            print()
            print("2. 添加路由规则，例如:")
            print("   - example.com/*")
            print("   - *.example.com/*")
            print()
        
        print("3. 验证 Worker 是否正常工作:")
        print("   - 访问你的网站")
        print("   - 打开浏览器开发者工具")
        print("   - 检查 Network 标签中的请求")
        print("   - 确认 HTML 中是否注入了 Fangyu SDK")
        print()
        
        print("4. 查看 Worker 日志:")
        print(f"   wrangler tail {script_name}")
        print()


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description='Cloudflare Worker 自动部署工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本部署（不绑定路由）
  python cloudflare_worker_deployer.py \\
    --api-token YOUR_CF_API_TOKEN \\
    --account-id YOUR_ACCOUNT_ID \\
    --script-name fangyu-defense \\
    --script-path ../adapters/shopify/cloudflare_worker/worker.js \\
    --gateway-url https://gateway.example.com \\
    --site-id site_xxxxxxxx \\
    --app-id 1 \\
    --app-secret your_secret_here

  # 完整部署（包含路由）
  python cloudflare_worker_deployer.py \\
    --api-token YOUR_CF_API_TOKEN \\
    --account-id YOUR_ACCOUNT_ID \\
    --script-name fangyu-defense \\
    --script-path ../adapters/shopify/cloudflare_worker/worker.js \\
    --gateway-url https://gateway.example.com \\
    --site-id site_xxxxxxxx \\
    --app-id 1 \\
    --app-secret your_secret_here \\
    --zone-id YOUR_ZONE_ID \\
    --route-pattern "example.com/*"

环境变量:
  CF_API_TOKEN    : Cloudflare API Token
  CF_ACCOUNT_ID   : Cloudflare Account ID
  CF_ZONE_ID      : Cloudflare Zone ID
        """
    )
    
    # Cloudflare 认证
    parser.add_argument('--api-token', required=True,
                        help='Cloudflare API Token（需要 Workers Scripts:Edit 权限）')
    parser.add_argument('--account-id', required=True,
                        help='Cloudflare Account ID')
    
    # Worker 配置
    parser.add_argument('--script-name', required=True,
                        help='Worker 名称（如 fangyu-defense）')
    parser.add_argument('--script-path', required=True,
                        help='Worker 脚本文件路径')
    
    # Fangyu 配置
    parser.add_argument('--gateway-url', required=True,
                        help='Fangyu 网关 URL（如 https://gateway.example.com）')
    parser.add_argument('--site-key', required=True,
                        help='Fangyu 站点密钥（格式：site_xxxxxxxx）')
    parser.add_argument('--site-secret', required=True,
                        help='Fangyu 站点签名密钥')
    
    # 路由配置（可选）
    parser.add_argument('--zone-id',
                        help='Cloudflare Zone ID（用于配置路由）')
    parser.add_argument('--route-pattern',
                        help='路由模式（如 example.com/*）')
    
    # 高级选项
    parser.add_argument('--fail-mode', choices=['open', 'closed'], default='open',
                        help='失败模式：open（网关不可达时放行）或 closed（拒绝）')
    parser.add_argument('--no-sdk-inject', action='store_true',
                        help='禁用 SDK 注入')
    
    return parser


def main() -> int:
    """主函数"""
    parser = build_parser()
    args = parser.parse_args()
    
    try:
        # 初始化 API 客户端
        api_client = CloudflareAPIClient(args.api_token, args.account_id)
        
        # 初始化部署器
        deployer = CloudflareWorkerDeployer(api_client)
        
        # 执行部署
        success = deployer.deploy(
            script_name=args.script_name,
            script_path=args.script_path,
            gateway_url=args.gateway_url,
            site_key=args.site_key,
            site_secret=args.site_secret,
            zone_id=args.zone_id,
            route_pattern=args.route_pattern,
            fail_mode=args.fail_mode,
            sdk_inject=not args.no_sdk_inject
        )
        
        return 0 if success else 1
        
    except KeyboardInterrupt:
        Logger.warning("\n用户中断操作")
        return 130
    except Exception as e:
        Logger.error(f"发生错误: {e}")
        return 1


# ============================================================================
# 内置配置（用于快速测试，生产环境请使用命令行参数）
# ============================================================================

if __name__ == '__main__':
    # 检查是否有命令行参数
    if len(sys.argv) > 1:
        # 使用命令行参数
        sys.exit(main())
    else:
        # 使用内置配置进行快速测试
        print("=" * 80)
        Logger.step("使用内置配置进行快速部署测试")
        print("=" * 80)
        print()
        
        # ========== 配置区 ==========
        # Cloudflare 凭证
        CF_API_TOKEN = "cfut_UKNOKoJXqxwWcHS1ypApN3t0sPzgX9qhCjPYjaK3f84c00ca"          # Cloudflare API Token
        CF_ACCOUNT_ID = "7e75eb4c52144e73340e35390e7ecb22"           # Cloudflare Account ID
        CF_ZONE_ID = None                           # Cloudflare Zone ID (可选，留空自动查找)
        
        # Worker 配置
        WORKER_NAME = "fangyu-defense"
        WORKER_SCRIPT_PATH = r"e:\Python\evercookie-defense-system\Evercookie Defense System V2\adapters\shopify\cloudflare_worker\worker.js"
        
        # Fangyu 配置
        FANGYU_GATEWAY_URL = "https://gateway.foxfingerlab.com"
        FANGYU_SITE_KEY = "site_eba8689a"
        FANGYU_SITE_SECRET = "bd5f8a076002101ff410fd127dd5d5e71452c00e9aa479bf"
        
        # 路由配置（可选，包含域名会自动查找 Zone ID）
        ROUTE_PATTERN = "bgifkrbt.shop/*"             # 格式: domain.com/* 或 *.domain.com/*
        
        # 高级选项
        FAIL_MODE = "open"                          # open 或 closed
        SDK_INJECT = True                           # True 或 False
        # ============================
        
        # 验证必需配置
        if CF_API_TOKEN == "YOUR_CF_API_TOKEN" or CF_ACCOUNT_ID == "YOUR_ACCOUNT_ID":
            Logger.error("请先配置 CF_API_TOKEN 和 CF_ACCOUNT_ID")
            Logger.error("在脚本末尾的配置区修改这些值")
            sys.exit(1)
        
        try:
            # 初始化 API 客户端
            api_client = CloudflareAPIClient(CF_API_TOKEN, CF_ACCOUNT_ID)
            
            # 初始化部署器
            deployer = CloudflareWorkerDeployer(api_client)
            
            # 执行部署
            zone_id = CF_ZONE_ID if CF_ZONE_ID else None
            
            success = deployer.deploy(
                script_name=WORKER_NAME,
                script_path=WORKER_SCRIPT_PATH,
                gateway_url=FANGYU_GATEWAY_URL,
                site_key=FANGYU_SITE_KEY,
                site_secret=FANGYU_SITE_SECRET,
                zone_id=zone_id,
                route_pattern=ROUTE_PATTERN,  # 直接传递，让脚本自动查找 Zone ID
                fail_mode=FAIL_MODE,
                sdk_inject=SDK_INJECT
            )
            
            sys.exit(0 if success else 1)
            
        except KeyboardInterrupt:
            Logger.warning("\n用户中断操作")
            sys.exit(130)
        except Exception as e:
            Logger.error(f"发生错误: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
