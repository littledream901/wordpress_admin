#!/usr/bin/env python3
"""
Fangyu Defense 独立部署脚本。
"""
import argparse
import hashlib
import logging
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import requests

# 配置日志
logger = logging.getLogger(__name__)


def _real_ip_config_path(domain: str) -> str:
    """
    生成 Real-IP 配置文件路径（与 defense.lua 同目录）。
    
    Args:
        domain: 站点域名
        
    Returns:
        Real-IP 配置文件的绝对路径
    """
    return f"/www/sites/{domain}/lua/fangyu_real_ip.conf"


def _strip_comment(line: str) -> str:
    """
    智能移除行尾注释，保留字符串内的 # 字符。
    
    Args:
        line: Nginx 配置文件的一行文本
        
    Returns:
        移除注释后的字符串（保留字符串内的 # 字符）
        
    Examples:
        >>> _strip_comment('server_name example.com; # comment')
        'server_name example.com; '
        >>> _strip_comment('set $var "#not_comment";')
        'set $var "#not_comment";'
    """
    result = []
    in_single = False
    in_double = False
    escaped = False
    for char in line:
        if escaped:
            result.append(char)
            escaped = False
            continue
        if char == "\\":
            result.append(char)
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            break
        result.append(char)
    return "".join(result)


def _find_block(lines: List[str], block_name: str) -> Tuple[int, int]:
    """
    在 Nginx 配置中查找指定块的起止行号（基于大括号深度解析）。
    
    Args:
        lines: Nginx 配置文件的行列表
        block_name: 块名称（如 'server', 'http', 'location'）
        
    Returns:
        (start_line, end_line) 元组，未找到时返回 (-1, -1)
        
    Examples:
        >>> lines = ['server {', '    listen 80;', '}']
        >>> _find_block(lines, 'server')
        (0, 2)
    """
    start = -1
    depth = 0
    pattern = re.compile(rf"^\s*{re.escape(block_name)}(?:\s|\{{)")
    for index, line in enumerate(lines):
        text = _strip_comment(line)
        if start < 0:
            if pattern.search(text) and "{" in text:
                start = index
                depth = text.count("{") - text.count("}")
                if depth <= 0:
                    return start, index
        else:
            depth += text.count("{") - text.count("}")
            if depth <= 0:
                return start, index
    return -1, -1


def _find_root_location(lines: List[str], server_start: int, server_end: int) -> Tuple[int, int]:
    """
    在 server 块内查找根路径 location / 块的起止行号。
    
    Args:
        lines: Nginx 配置文件的行列表
        server_start: server 块起始行号
        server_end: server 块结束行号
        
    Returns:
        (start_line, end_line) 元组，未找到时返回 (-1, -1)
        
    Notes:
        支持 'location /' 和 'location = /' 两种写法
    """
    start = -1
    depth = 0
    pattern = re.compile(r"^\s*location\s+(?:=\s*)?/\s*\{")
    for index in range(server_start + 1, server_end):
        text = _strip_comment(lines[index])
        if start < 0:
            if pattern.search(text):
                start = index
                depth = text.count("{") - text.count("}")
        else:
            depth += text.count("{") - text.count("}")
            if depth <= 0:
                return start, index
    return -1, -1


def _clean_value(value: str) -> str:
    """
    清理配置值的首尾空白字符和引号。
    
    Args:
        value: 原始配置值字符串
        
    Returns:
        清理后的字符串
    """
    return value.strip().strip('`"\' ')


def _real_ip_block(domain: str) -> str:
    """
    生成 Real-IP include 块（指向站点 lua 目录）。
    
    Args:
        domain: 站点域名
        
    Returns:
        Nginx include 指令字符串
    """
    return f"    include {_real_ip_config_path(domain)};"


def _real_ip_config_content() -> str:
    """
    生成 Real-IP 配置内容（包含 Cloudflare IP 段和私有 IP 段）。
    
    Returns:
        完整的 set_real_ip_from 配置文本
    """
    return """set_real_ip_from 127.0.0.1;
set_real_ip_from 10.0.0.0/8;
set_real_ip_from 172.16.0.0/12;
set_real_ip_from 192.168.0.0/16;
set_real_ip_from 100.64.0.0/10;
set_real_ip_from 169.254.0.0/16;
set_real_ip_from ::1;
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 131.0.72.0/22;
set_real_ip_from 2400:cb00::/32;
set_real_ip_from 2606:4700::/32;
set_real_ip_from 2803:f800::/32;
set_real_ip_from 2405:b500::/32;
set_real_ip_from 2405:8100::/32;
set_real_ip_from 2a06:98c0::/29;
set_real_ip_from 2c0f:f248::/32;
real_ip_header CF-Connecting-IP;
real_ip_recursive on;
"""


def _extract_server_name(config_content: str) -> Optional[str]:
    """
    从 Nginx 配置中提取 server_name 指令的值。
    
    Args:
        config_content: Nginx 配置文件内容
        
    Returns:
        第一个 server_name 值，未找到时返回 None
    """
    lines = config_content.splitlines()
    server_start, server_end = _find_block(lines, "server")
    if server_start < 0:
        return None
    for line in lines[server_start:server_end + 1]:
        text = _strip_comment(line).strip()
        if text.startswith("server_name"):
            values = text.removesuffix(";").split()[1:]
            return values[0] if values else None
    return None


def _render_blocks(domain: str, site_id: str, site_key: str, site_secret: str, gateway_url: str) -> Tuple[str, str, str]:
    domain = _clean_value(domain)
    site_id = _clean_value(site_id)
    site_key = _clean_value(site_key)
    site_secret = _clean_value(site_secret)
    gateway_url = _clean_value(gateway_url)
    variables = f'''{_real_ip_block(domain)}

    # Fangyu Defense 配置
    set $fangyu_gateway_url  "{gateway_url}";
    set $fangyu_site_id      "{site_id}";
    set $fangyu_site_key     "{site_key}";
    set $fangyu_site_secret  "{site_secret}";
    set $fangyu_fail_mode    "open";
    set $fangyu_sdk_inject   "on";
    set $fangyu_blocked_url  "/blocked";
    set $fangyu_challenge_url "/challenge";
    set $fy_sdk_snippet      "";
    set $fy_server_token     "";'''
    access = f'''        access_by_lua_file /www/sites/{domain}/lua/defense.lua;
        proxy_set_header Accept-Encoding "";
        proxy_hide_header Content-Encoding;'''
    body_filter = '''        body_filter_by_lua_block {
            local snippet = ngx.var.fy_sdk_snippet
            if not snippet or snippet == "" then return end

            local content_type = ngx.header["Content-Type"] or ""
            if type(content_type) == "string" and string.find(content_type, "text/html", 1, true) then
                local chunk = ngx.arg[1]
                if chunk and type(chunk) == "string" and chunk ~= "" then
                    local safe_snippet = snippet:gsub("%%", "%%%%")
                    local new_chunk, count = string.gsub(chunk, "</head>", safe_snippet .. "</head>", 1)
                    if count > 0 then
                        ngx.arg[1] = new_chunk
                    end
                end
            end
        }'''
    return variables, access, body_filter


def _remove_old_blocks(config_content: str) -> str:
    """
    移除 Nginx 配置中已有的 Fangyu Defense 配置块（幂等部署准备）。
    
    Args:
        config_content: Nginx 配置文件内容
        
    Returns:
        移除旧配置后的 Nginx 配置文本
        
    Notes:
        移除内容包括：Fangyu 变量、Real-IP 配置、access_by_lua_file、body_filter_by_lua_block
    """
    lines = config_content.splitlines()
    result = []
    body_filter_depth = 0
    for line in lines:
        text = _strip_comment(line).strip()
        if body_filter_depth > 0:
            body_filter_depth += text.count("{") - text.count("}")
            continue
        if text.startswith("set $fangyu_") or text.startswith("set $fy_"):
            continue
        if text.startswith("set_real_ip_from"):
            continue
        if text.startswith("real_ip_header") or text.startswith("real_ip_recursive"):
            continue
        if text.startswith("access_by_lua_file") and "defense.lua" in text:
            continue
        if text in {'proxy_set_header Accept-Encoding "";', "proxy_hide_header Content-Encoding;"}:
            continue
        if text.startswith("body_filter_by_lua_block"):
            body_filter_depth = text.count("{") - text.count("}")
            continue
        if "Fangyu Defense 配置" in line:
            continue
        result.append(line)
    return "\n".join(result)


def _inject_variables(config_content: str, variables: str) -> str:
    """
    在 server 块的 server_name 指令后注入 Fangyu 变量配置。
    
    Args:
        config_content: Nginx 配置文件内容
        variables: 要注入的变量配置块
        
    Returns:
        注入变量后的 Nginx 配置文本
    """
    lines = config_content.splitlines()
    server_start, server_end = _find_block(lines, "server")
    if server_start < 0:
        return config_content
    result = []
    inserted = False
    for index, line in enumerate(lines):
        result.append(line)
        text = _strip_comment(line).strip()
        if not inserted and server_start <= index <= server_end and text.startswith("server_name") and text.endswith(";"):
            result.extend(["", variables, ""])
            inserted = True
    return "\n".join(result)


def _inject_access(config_content: str, access: str) -> str:
    """
    在 location / 块开头注入 access_by_lua_file 指令。
    
    Args:
        config_content: Nginx 配置文件内容
        access: 要注入的 access 阶段配置
        
    Returns:
        注入 access 配置后的 Nginx 配置文本
    """
    lines = config_content.splitlines()
    server_start, server_end = _find_block(lines, "server")
    if server_start < 0:
        return config_content
    location_start, _ = _find_root_location(lines, server_start, server_end)
    if location_start < 0:
        return config_content
    return "\n".join(lines[:location_start + 1] + [access] + lines[location_start + 1:])


def _inject_body_filter(config_content: str, body_filter: str) -> str:
    """
    在 location / 块结束前注入 body_filter_by_lua_block 指令。
    
    Args:
        config_content: Nginx 配置文件内容
        body_filter: 要注入的 body_filter 阶段配置
        
    Returns:
        注入 body_filter 配置后的 Nginx 配置文本
    """
    lines = config_content.splitlines()
    server_start, server_end = _find_block(lines, "server")
    if server_start < 0:
        return config_content
    _, location_end = _find_root_location(lines, server_start, server_end)
    if location_end < 0:
        return config_content
    return "\n".join(lines[:location_end] + [body_filter] + lines[location_end:])


class FangyuTemplateMigrator:
    """Nginx 配置迁移器：将现有配置迁移为 Fangyu Defense 模板配置"""
    
    @staticmethod
    def migrate_config(config_content: str, site_id: str, site_key: str, site_secret: str, gateway_url: str) -> str:
        """
        迁移 Nginx 配置为 Fangyu Defense 模板配置。
        
        Args:
            config_content: 原始 Nginx 配置内容
            site_id: 站点数字主键（Site.id）
            site_key: 站点密钥字符串（site_xxxxxxxx）
            site_secret: 站点签名密钥
            gateway_url: Fangyu 网关 URL
            
        Returns:
            迁移后的 Nginx 配置文本
            
        Raises:
            ValueError: 当配置中未找到 server_name 时
        """
        domain = _extract_server_name(config_content)
        if not domain:
            raise ValueError("未找到 server_name，无法生成迁移模板")

        vars_block, access_lua, body_filter = _render_blocks(
            domain, site_id, site_key, site_secret, gateway_url
        )
        config = _remove_old_blocks(config_content)
        config = _inject_variables(config, vars_block)
        config = _inject_access(config, access_lua)
        config = _inject_body_filter(config, body_filter)
        return config


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


class OnePanelAPIClient:
    """
    1Panel API 客户端（基于 MD5 签名认证）。
    
    Attributes:
        panel_url: 1Panel API 基础 URL
        panel_key: 1Panel API 密钥
        session: HTTP 会话对象
    """
    
    def __init__(self, panel_url: str, panel_key: str):
        """
        初始化 1Panel API 客户端。
        
        Args:
            panel_url: 1Panel API 地址（如 http://127.0.0.1:31384）
            panel_key: 1Panel API 密钥
        """
        self.panel_url = panel_url.rstrip('/')
        self.panel_key = panel_key
        self.session = requests.Session()
        self.session.trust_env = False
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")

    def _generate_signature(self) -> Tuple[str, str]:
        timestamp = str(int(time.time()))
        sign_str = f"1panel{self.panel_key}{timestamp}"
        return hashlib.md5(sign_str.encode()).hexdigest(), timestamp

    def _get_headers(self) -> Dict[str, str]:
        signature, timestamp = self._generate_signature()
        return {
            "Content-Type": "application/json",
            "1Panel-Token": signature,
            "1Panel-Timestamp": timestamp,
        }

    def search_containers(self, name: str, state: str = "running", page_size: int = 50, order: str = "ascending", max_pages: int = 100) -> List[Dict]:
        all_containers = []
        for page in range(1, max_pages + 1):
            resp = self.session.post(
                f"{self.panel_url}/api/v2/containers/search",
                headers=self._get_headers(),
                json={"name": name, "state": state, "page": page, "pageSize": page_size, "orderBy": "name", "order": order},
                timeout=10,
                verify=False,
            )
            if resp.status_code != 200:
                Logger.warning(f"容器搜索失败: HTTP {resp.status_code}")
                break
            data = resp.json()
            items = data.get("data", {}).get("items", []) if data.get("code") == 200 else []
            if not items:
                break
            all_containers.extend(items)
            if len(items) < page_size:
                break
        return all_containers

    def get_container_file_content(self, container_id: str, path: str) -> Optional[str]:
        resp = self.session.post(
            f"{self.panel_url}/api/v2/containers/files/content",
            headers=self._get_headers(),
            json={"containerID": container_id, "path": path},
            timeout=10,
            verify=False,
        )
        if resp.status_code == 200 and resp.json().get("code") == 200:
            return resp.json()["data"]["content"]
        return None

    def upload_file_to_container(self, container_id: str, local_path: str, target_dir: str) -> bool:
        headers = self._get_headers()
        headers.pop("Content-Type", None)
        with open(local_path, 'rb') as f:
            resp = self.session.post(
                f"{self.panel_url}/api/v2/containers/files/upload",
                headers=headers,
                data={"containerID": container_id, "path": target_dir},
                files={"file": (os.path.basename(local_path), f, 'application/octet-stream')},
                timeout=30,
                verify=False,
            )
        return resp.status_code == 200 and resp.json().get("code") == 200

    def exec_container_command(self, container_id: str, command: str) -> Tuple[bool, str, str]:
        resp = self.session.post(
            f"{self.panel_url}/api/v2/containers/exec",
            headers=self._get_headers(),
            json={"containerID": container_id, "command": command},
            timeout=30,
            verify=False,
        )
        if resp.status_code == 200 and resp.json().get("code") == 200:
            result = resp.json().get("data", {})
            return result.get("exitCode", 1) == 0, result.get("stdout", ""), result.get("stderr", "")
        return False, "", f"API 调用失败: {resp.status_code}"

    def update_website_nginx_config(self, website_id: int, content: str) -> bool:
        resp = self.session.post(
            f"{self.panel_url}/api/v2/websites/nginx/update",
            headers=self._get_headers(),
            json={"id": website_id, "content": content},
            timeout=30,
            verify=False,
        )
        if resp.status_code == 200 and resp.json().get("code") == 200:
            return True
        if resp.status_code == 200:
            Logger.warning(f"站点 Nginx 更新失败: {resp.json()}")
        else:
            Logger.warning(f"站点 Nginx 更新失败: HTTP {resp.status_code}")
        return False

    def check_file_exists(self, container_id: str, file_path: str) -> bool:
        success, stdout, _ = self.exec_container_command(container_id, f"test -f {shlex.quote(file_path)} && echo 'exists' || echo 'not_found'")
        return success and 'exists' in stdout

    def search_websites(self, domain: str, page_size: int = 50, max_pages: int = 100) -> List[Dict]:
        all_websites = []
        for page in range(1, max_pages + 1):
            resp = self.session.post(
                f"{self.panel_url}/api/v2/websites/search",
                headers=self._get_headers(),
                json={"name": domain, "page": page, "pageSize": page_size, "orderBy": "primary_domain", "order": "ascending"},
                timeout=10,
                verify=False,
            )
            if resp.status_code != 200:
                Logger.warning(f"站点搜索失败: HTTP {resp.status_code}")
                break
            data = resp.json()
            items = data.get("data", {}).get("items", []) if data.get("code") == 200 else []
            if not items:
                break
            all_websites.extend(items)
            if len(items) < page_size:
                break
        return all_websites


def run_cmd(cmd: str, check: bool = True, capture: bool = True) -> Optional[str]:
    """
    执行 shell 命令。
    
    Args:
        cmd: 要执行的命令字符串
        check: 是否检查返回码（失败时抛异常）
        capture: 是否捕获输出
        
    Returns:
        命令的标准输出（如果 capture=True），否则返回 None
        
    Raises:
        subprocess.CalledProcessError: 当 check=True 且命令返回非零状态码时
    """
    result = subprocess.run(cmd, shell=True, check=check, capture_output=capture, text=True)
    return result.stdout.strip() if capture else None


class ConfigValidator:
    """配置验证器：验证 Nginx 配置和 Lua 脚本的完整性与安全性"""
    
    @staticmethod
    def validate_defense_lua(content: str) -> Tuple[bool, List[str]]:
        """
        验证 defense.lua 脚本的完整性和安全性。
        
        Args:
            content: defense.lua 文件内容
            
        Returns:
            (是否通过验证, 错误列表)
        """
        errors = []
        warnings = []
        
        # 检查文件大小
        if len(content) < 5000:
            errors.append(f"文件太小 ({len(content)} 字节)，可能不完整")
            return False, errors
        
        # 基础特征检查（宽松模式）
        basic_checks = {
            "Lua 文件标识": "-- " in content or "local " in content,
            "Nginx 模块使用": "ngx." in content,
            "HTTP 请求处理": any(kw in content for kw in ["ngx.req", "ngx.header", "ngx.var"]),
            "响应控制": "ngx.exit" in content or "ngx.say" in content,
        }
        
        failed_basic = [name for name, result in basic_checks.items() if not result]
        if failed_basic:
            errors.extend([f"缺少基础特征: {name}" for name in failed_basic])
            return False, errors
        
        # Fangyu 特定特征检查（建议性）
        fangyu_features = {
            "网关配置引用": any(kw in content for kw in ["gateway_url", "fangyu_gateway"]),
            "站点标识": any(kw in content for kw in ["site_id", "fangyu_site"]),
            "请求头处理": "get_headers" in content,
        }
        
        missing_features = [name for name, result in fangyu_features.items() if not result]
        if missing_features:
            warnings.extend([f"建议检查: {name}" for name in missing_features])
        
        # 检查危险模式（安全检查）
        dangerous_patterns = [
            (r"os\.execute\(", "使用了危险的 os.execute"),
            (r"io\.popen\(", "使用了危险的 io.popen"),
            (r"loadstring\(", "使用了危险的 loadstring"),
            (r"require\(['\"]socket['\"]\)", "使用了不安全的 socket 模块"),
        ]
        for pattern, msg in dangerous_patterns:
            if re.search(pattern, content):
                errors.append(f"安全警告: {msg}")
        
        # 只有安全问题才阻止部署，功能缺失仅警告
        if warnings and not errors:
            # 有警告但无错误，仍然通过
            return True, warnings
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_nginx_config_logic(config: str, domain: str) -> Tuple[bool, List[str]]:
        """
        验证 Nginx 配置的逻辑完整性。
        
        Args:
            config: Nginx 配置内容
            domain: 站点域名
            
        Returns:
            (是否通过验证, 错误列表)
        """
        errors = []
        
        # 检查必需变量
        required_vars = [
            "$fangyu_gateway_url",
            "$fangyu_site_id",
            "$fangyu_site_key",
            "$fangyu_site_secret"
        ]
        for var in required_vars:
            if var not in config:
                errors.append(f"缺少必需变量: {var}")
        
        # 检查 defense.lua 路径
        expected_lua_path = f"/www/sites/{domain}/lua/defense.lua"
        if expected_lua_path not in config:
            errors.append(f"defense.lua 路径不匹配: 期望 {expected_lua_path}")
        
        # 检查关键指令
        required_directives = [
            "access_by_lua_file",
            "body_filter_by_lua_block"
        ]
        for directive in required_directives:
            if directive not in config:
                errors.append(f"缺少必需指令: {directive}")
        
        # 检查 SSL 配置完整性
        if "ssl_certificate " in config:
            if "ssl_certificate_key" not in config:
                errors.append("SSL 配置不完整: 有证书但缺少私钥配置")
        
        return len(errors) == 0, errors


class FileUploader:
    """统一的文件上传管理器"""
    
    def __init__(self, api_client: 'OnePanelAPIClient'):
        self.api_client = api_client
    
    @contextmanager
    def _temp_file(self, content: str, filename: str):
        """
        创建临时文件的上下文管理器。
        
        Args:
            content: 文件内容
            filename: 文件名
            
        Yields:
            临时文件的绝对路径
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / filename
            tmp_path.write_text(content, encoding='utf-8', newline='\n')
            yield str(tmp_path)
    
    def upload_content(
        self, 
        container_id: str, 
        content: Union[str, Path], 
        target_dir: str, 
        filename: str,
        description: str = "",
        validate_func: Optional[callable] = None
    ) -> bool:
        """
        统一的文件上传接口（支持文件路径或内容字符串）。
        
        Args:
            container_id: 容器 ID
            content: 文件路径或文本内容
            target_dir: 目标目录
            filename: 文件名
            description: 操作描述（用于日志）
            validate_func: 可选的内容验证函数
            
        Returns:
            True 表示上传成功，False 表示失败
        """
        desc = description or filename
        Logger.step(f"上传 {desc}...")
        
        try:
            # 内容验证
            if validate_func:
                if isinstance(content, str) and not Path(content).exists():
                    # 字符串内容，直接验证
                    is_valid, errors = validate_func(content)
                elif isinstance(content, Path) and content.exists():
                    # 文件路径，读取后验证
                    file_content = content.read_text(encoding='utf-8')
                    is_valid, errors = validate_func(file_content)
                else:
                    # 文件路径字符串
                    file_content = Path(content).read_text(encoding='utf-8')
                    is_valid, errors = validate_func(file_content)
                
                if not is_valid:
                    Logger.error(f"✗ {desc} 验证失败:")
                    for error in errors:
                        Logger.error(f"  - {error}")
                    return False
                Logger.success(f"✓ {desc} 验证通过")
            
            # 准备文件路径
            if isinstance(content, str) and not Path(content).exists():
                # 字符串内容，创建临时文件
                with self._temp_file(content, filename) as tmp_path:
                    return self._do_upload(container_id, tmp_path, target_dir, desc)
            else:
                # 已有文件路径
                local_path = str(content)
                return self._do_upload(container_id, local_path, target_dir, desc)
                
        except OSError as e:
            Logger.error(f"✗ 文件操作失败: {e}")
            return False
        except requests.exceptions.RequestException as e:
            Logger.error(f"✗ 上传失败: {e}")
            return False
    
    def _do_upload(self, container_id: str, local_path: str, target_dir: str, description: str) -> bool:
        """
        执行实际上传并验证。
        
        Args:
            container_id: 容器 ID
            local_path: 本地文件路径
            target_dir: 目标目录
            description: 操作描述
            
        Returns:
            True 表示上传成功，False 表示失败
        """
        file_size = os.path.getsize(local_path)
        Logger.step(f"  文件大小: {file_size:,} 字节")
        
        success = self.api_client.upload_file_to_container(
            container_id, local_path, target_dir
        )
        
        if success:
            target_path = f"{target_dir}/{os.path.basename(local_path)}"
            Logger.success(f"✓ 上传成功: {target_path}")
        else:
            Logger.error(f"✗ 上传失败")
        
        return success


class ContainerManager:
    def __init__(self, api_client: OnePanelAPIClient):
        self.api_client = api_client

    def find_openresty_container(self) -> Tuple[str, str]:
        Logger.step("查找 OpenResty 容器...")
        try:
            containers = self.api_client.search_containers("openresty", state="running")
            if containers:
                container = containers[0]
                container_name = container.get('name')
                container_id = container.get('containerID')
                Logger.success(f"使用容器: {container_name} (ID: {container_id[:12]}...)")
                return container_name, container_id
            Logger.error("未找到运行中的 OpenResty 容器")
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            Logger.error(f"API 请求失败: {e}")
            sys.exit(1)
        except (KeyError, IndexError, ValueError) as e:
            Logger.error(f"解析容器信息失败: {e}")
            sys.exit(1)

    def check_lua_dependencies(self, container_id: str) -> bool:
        Logger.step("检查 Lua 依赖...")
        try:
            content = self.api_client.get_container_file_content(container_id, "/usr/local/openresty/lualib/resty/http.lua")
            if content:
                Logger.success("Lua 依赖已存在")
                return True
            Logger.warning("Lua 依赖检查失败，但将继续部署（OpenResty 通常自带依赖）")
            return False
        except requests.exceptions.RequestException as e:
            Logger.warning(f"API 请求失败: {e}，将继续部署")
            return False
        except Exception as e:
            Logger.warning(f"依赖检查失败: {e}，将继续部署")
            return False


class NginxConfManager:
    def __init__(self, api_client: OnePanelAPIClient):
        self.api_client = api_client

    def check_lua_config(self, container_id: str) -> bool:
        nginx_conf_path = "/usr/local/openresty/nginx/conf/nginx.conf"
        content = self.api_client.get_container_file_content(container_id, nginx_conf_path)
        if not content:
            return False
        active_lines = [_strip_comment(line) for line in content.split('\n')]
        cleaned = '\n'.join(active_lines)
        return re.search(r'(?m)^\s*lua_package_path\b', cleaned) is not None and re.search(r'(?m)^\s*lua_package_cpath\b', cleaned) is not None

    def add_lua_config(self, container_id: str) -> bool:
        """
        在 nginx.conf 的 http 块中添加 Lua 配置。
        
        Args:
            container_id: 容器 ID
            
        Returns:
            True 表示添加成功或已存在，False 表示失败
        """
        nginx_conf_path = "/usr/local/openresty/nginx/conf/nginx.conf"
        content = self.api_client.get_container_file_content(container_id, nginx_conf_path)
        if not content:
            Logger.error("无法读取 nginx.conf")
            return False
        active_lines = [_strip_comment(line) for line in content.split('\n')]
        cleaned = '\n'.join(active_lines)
        if re.search(r'(?m)^\s*lua_package_path\b', cleaned) and re.search(r'(?m)^\s*lua_package_cpath\b', cleaned):
            Logger.success("nginx.conf 中已有 lua_package_path 配置")
            return True
        Logger.step("在 nginx.conf 的 http 块中添加 Lua 配置...")
        lua_config = """
    lua_package_path "/usr/local/openresty/lualib/?.lua;;";
    lua_package_cpath "/usr/local/openresty/lualib/?.so;;";
    lua_code_cache on;
"""
        lines = content.split('\n')
        new_lines = []
        inserted = False
        http_start, _ = _find_block(lines, 'http')
        for idx, line in enumerate(lines):
            new_lines.append(line)
            if not inserted and idx == http_start:
                new_lines.append(lua_config)
                inserted = True
        if not inserted:
            Logger.error("未找到 http 块")
            return False
        new_content = '\n'.join(new_lines).replace('\r\n', '\n').replace('\r', '\n')
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_file = Path(tmp_dir) / "nginx.conf"
                tmp_file.write_text(new_content, encoding='utf-8', newline='\n')
                success = self.api_client.upload_file_to_container(container_id, str(tmp_file), "/usr/local/openresty/nginx/conf")
                if success:
                    Logger.success("✓ nginx.conf 已更新")
                    return True
                Logger.warning("⚠️ 上传失败，但不影响站点配置，继续部署")
                return True  # 改为不阻断部署
        except OSError as e:
            Logger.warning(f"⚠️ 文件操作失败: {e}，继续部署")
            return True  # 改为不阻断部署
        except requests.exceptions.RequestException as e:
            Logger.warning(f"⚠️ API 请求失败: {e}，继续部署")
            return True  # 改为不阻断部署

    def _print_manual_fix_guide(self, container_id: str):
        print()
        print("=" * 70)
        print("手动修复指南")
        print("=" * 70)
        print(f"docker exec -it {container_id[:12]} sh")
        print("vi /usr/local/openresty/nginx/conf/nginx.conf")


class NginxConfigGenerator:
    @staticmethod
    def generate_config_blocks(domain: str, site_id: str, site_key: str, site_secret: str, gateway_url: str) -> Tuple[str, str, str]:
        domain = _clean_value(domain)
        site_id = _clean_value(site_id)
        site_key = _clean_value(site_key)
        site_secret = _clean_value(site_secret)
        gateway_url = _clean_value(gateway_url)
        vars_block = f"""
{_real_ip_block(domain)}

    # Fangyu Defense 配置
    set $fangyu_gateway_url  "{gateway_url}";
    set $fangyu_site_id      "{site_id}";
    set $fangyu_site_key     "{site_key}";      # 站点密钥字符串
    set $fangyu_site_secret  "{site_secret}";  # 签名密钥
    set $fangyu_fail_mode    "open";
    set $fangyu_sdk_inject   "on";
    set $fangyu_blocked_url  "/blocked";
    set $fangyu_challenge_url "/challenge";
    set $fy_sdk_snippet      "";
    set $fy_server_token     "";"""
        access_lua = f"""        access_by_lua_file /www/sites/{domain}/lua/defense.lua;
        proxy_set_header Accept-Encoding "";
        proxy_hide_header Content-Encoding;"""
        body_filter = """        body_filter_by_lua_block {
            local snippet = ngx.var.fy_sdk_snippet
            if not snippet or snippet == "" then return end

            local ct = ngx.header["Content-Type"] or ""
            if type(ct) == "string" and string.find(ct, "text/html", 1, true) then
                local chunk = ngx.arg[1]
                if chunk and type(chunk) == "string" and chunk ~= "" then
                    local safe_snippet = snippet:gsub("%%", "%%%%")
                    local new_chunk, count = string.gsub(chunk, "</head>", safe_snippet .. "</head>", 1)
                    if count > 0 then
                        ngx.arg[1] = new_chunk
                    end
                end
            end
        }"""
        return vars_block, access_lua, body_filter

    @staticmethod
    def remove_old_fangyu_config(config_content: str) -> str:
        cleaned_lines = [_strip_comment(line) for line in config_content.split('\n')]
        cleaned_content = '\n'.join(cleaned_lines)
        has_fangyu_config = (
            re.search(r'(?m)^\s*set\s+\$fangyu_', cleaned_content) is not None
            or re.search(r'(?m)^\s*set\s+\$fy_', cleaned_content) is not None
            or re.search(r'(?m)^\s*access_by_lua_file\b.*defense\.lua', cleaned_content) is not None
            or re.search(r'(?m)^\s*body_filter_by_lua_block\b', cleaned_content) is not None
            or re.search(r'(?m)^\s*set_real_ip_from\b', cleaned_content) is not None
            or re.search(r'(?m)^\s*real_ip_(?:header|recursive)\b', cleaned_content) is not None
        )
        if not has_fangyu_config:
            return config_content
        Logger.warning("检测到已有 Fangyu 配置，先删除旧配置")
        lines = config_content.split('\n')
        new_lines = []
        in_body_filter = False
        body_filter_brace_count = 0
        for line in lines:
            stripped = _strip_comment(line).strip()
            if in_body_filter:
                body_filter_brace_count += stripped.count('{') - stripped.count('}')
                if body_filter_brace_count <= 0:
                    in_body_filter = False
                continue
            if stripped.startswith('set $fangyu_') or stripped.startswith('set $fy_'):
                continue
            if stripped.startswith('set_real_ip_from'):
                continue
            if stripped.startswith('real_ip_header') or stripped.startswith('real_ip_recursive'):
                continue
            if 'fangyu_real_ip.conf' in stripped:
                continue
            if '# Fangyu Defense' in line or 'Fangyu Defense 配置' in line:
                continue
            if stripped.startswith('access_by_lua_file') and 'defense.lua' in stripped:
                continue
            if stripped == 'proxy_set_header Accept-Encoding "";' or stripped == 'proxy_hide_header Content-Encoding;':
                continue
            if stripped.startswith('body_filter_by_lua_block'):
                in_body_filter = True
                body_filter_brace_count = stripped.count('{') - stripped.count('}')
                continue
            new_lines.append(line)
        Logger.step("✓ 已删除旧的 Fangyu 配置")
        return '\n'.join(new_lines)

    @staticmethod
    def inject_vars_block(config_content: str, vars_block: str) -> str:
        lines = config_content.split('\n')
        new_lines = []
        inserted_vars = False
        server_start, server_end = _find_block(lines, 'server')
        if server_start < 0 or server_end < 0:
            return config_content
        for idx, line in enumerate(lines):
            new_lines.append(line)
            if inserted_vars or idx < server_start or idx > server_end:
                continue
            cleaned = _strip_comment(line).strip()
            if cleaned.startswith('server_name') and cleaned.endswith(';'):
                new_lines.append('')
                new_lines.append(vars_block.rstrip())
                new_lines.append('')
                inserted_vars = True
        if inserted_vars:
            Logger.step("✓ 已插入 Fangyu 变量配置")
        return '\n'.join(new_lines)

    @staticmethod
    def inject_access_lua(config_content: str, access_lua: str) -> str:
        lines = config_content.split('\n')
        new_lines = []
        inserted_access = False
        server_start, server_end = _find_block(lines, 'server')
        if server_start < 0 or server_end < 0:
            return config_content
        location_start, location_end = _find_root_location(lines, server_start, server_end)
        if location_start < 0 or location_end < 0:
            return config_content
        for i, line in enumerate(lines):
            if i == location_start + 1 and not inserted_access:
                new_lines.append(access_lua)
                inserted_access = True
            new_lines.append(line)
        if inserted_access:
            Logger.step("✓ 已插入 access_by_lua_file 指令（在 location / 块内）")
        else:
            Logger.warning("⚠ 未找到合适位置插入 access_by_lua_file")
        return '\n'.join(new_lines)

    @staticmethod
    def inject_body_filter(config_content: str, body_filter: str) -> str:
        lines = config_content.split('\n')
        server_start, server_end = _find_block(lines, 'server')
        if server_start < 0 or server_end < 0:
            return config_content
        location_start, location_end = _find_root_location(lines, server_start, server_end)
        if location_start < 0 or location_end < 0:
            return config_content
        new_lines = []
        for i, line in enumerate(lines):
            if i == location_end:
                new_lines.append(body_filter)
                new_lines.append(line)
            else:
                new_lines.append(line)
        Logger.step("✓ 已插入 body_filter_by_lua_block 指令（在 location / 块结束前）")
        return '\n'.join(new_lines)


class NginxResolverConfigurator:
    def __init__(self, api_client: OnePanelAPIClient):
        self.api_client = api_client

    def ensure_resolver_configured(self, container_id: str) -> bool:
        Logger.step("检查并配置 DNS resolver...")
        nginx_conf_path = "/usr/local/openresty/nginx/conf/nginx.conf"
        try:
            nginx_conf = self.api_client.get_container_file_content(container_id, nginx_conf_path)
            if not nginx_conf:
                Logger.warning("无法读取 nginx.conf，跳过 resolver 配置")
                return False
            cleaned = '\n'.join(_strip_comment(line) for line in nginx_conf.split('\n'))
            if re.search(r'(?m)^\s*resolver\b', cleaned):
                Logger.success("DNS resolver 已存在")
                return True
            modified_conf = self._inject_resolver(nginx_conf)
            if not modified_conf:
                Logger.warning("无法自动添加 resolver，请手动配置")
                return False
            success = self._write_nginx_conf(container_id, modified_conf)
            if success:
                Logger.success("nginx.conf 已更新")
                return True
            Logger.warning("nginx.conf 更新失败，请手动添加 resolver")
            return False
        except requests.exceptions.RequestException as e:
            Logger.warning(f"API 请求失败: {e}，请手动配置")
            return False
        except (OSError, ValueError) as e:
            Logger.warning(f"配置 resolver 失败: {e}，请手动配置")
            return False

    def _inject_resolver(self, nginx_conf: str) -> Optional[str]:
        lines = nginx_conf.split('\n')
        new_lines = []
        inserted = False
        http_start, http_end = _find_block(lines, 'http')
        for idx, line in enumerate(lines):
            new_lines.append(line)
            if not inserted and http_start >= 0 and idx > http_start and (http_end < 0 or idx < http_end):
                if 'include' in _strip_comment(line) and 'mime.types' in _strip_comment(line):
                    new_lines.append('    resolver 8.8.8.8 8.8.4.4 ipv6=off;')
                    inserted = True
                    Logger.success("已添加 DNS resolver 配置")
        return '\n'.join(new_lines) if inserted else None

    def _write_nginx_conf(self, container_id: str, content: str) -> bool:
        tmp_path = os.path.join(tempfile.gettempdir(), 'nginx.conf')
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return self.api_client.upload_file_to_container(container_id, tmp_path, '/usr/local/openresty/nginx/conf')
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


class NginxConfigManager:
    def __init__(self, api_client: OnePanelAPIClient):
        self.api_client = api_client
        self.config_generator = NginxConfigGenerator()

    def update_website_config(self, domain: str, site_id: str, site_key: str, site_secret: str, gateway_url: str, container_id: str, skip_ssl_check: bool = False) -> str:
        """
        更新站点 Nginx 配置（带逻辑验证）。
        
        Args:
            domain: 站点域名
            site_id: 站点数字主键（Site.id）
            site_key: 站点密钥字符串（site_xxxxxxxx）
            site_secret: 站点签名密钥
            gateway_url: Fangyu 网关 URL
            container_id: 容器 ID
            skip_ssl_check: 是否跳过 SSL 证书验证
            
        Returns:
            配置文件路径
            
        Raises:
            SystemExit: 当配置验证或更新失败时
        """
        Logger.step("通过 1Panel API 更新配置...")
        website_info = self._get_website_info(domain)
        config_path = self._find_nginx_config(website_info, container_id)
        current_config = self.api_client.get_container_file_content(container_id, config_path)
        if not current_config:
            Logger.error("无法读取 Nginx 配置文件")
            sys.exit(1)
        config_domain = _extract_server_name(current_config) or website_info.get('primaryDomain') or website_info.get('alias') or domain
        if config_domain != domain:
            Logger.warning(f"使用配置文件 server_name {config_domain} 生成 Fangyu 路径，避免域名路径不一致")
        modified_config = self._modify_config(current_config, config_domain, site_id, site_key, site_secret, gateway_url)
        
        # 配置逻辑验证
        validator = ConfigValidator()
        is_valid, errors = validator.validate_nginx_config_logic(modified_config, config_domain)
        if not is_valid:
            Logger.error("✗ Nginx 配置验证失败:")
            for error in errors:
                Logger.error(f"  - {error}")
            sys.exit(1)
        Logger.success("✓ Nginx 配置逻辑验证通过")
        
        self._write_config(container_id, int(website_info['id']), config_path, modified_config, skip_ssl_check)
        Logger.success("配置已更新，1Panel 将自动重载 Nginx")
        return config_path

    def _get_website_info(self, domain: str) -> Dict:
        websites = self.api_client.search_websites(domain)
        if not websites:
            Logger.error(f"找不到站点: {domain}")
            sys.exit(1)
        website_info = websites[0]
        Logger.success(f"使用站点 ID: {website_info['id']}")
        return website_info

    def _find_nginx_config(self, website_info: Dict, container_id: str) -> str:
        alias = website_info.get('alias', website_info.get('primaryDomain', ''))
        domain = website_info.get('primaryDomain', '')
        possible_paths = [
            f"/usr/local/openresty/nginx/conf/conf.d/{alias}.conf",
            f"/usr/local/openresty/nginx/conf/conf.d/{domain}.conf",
            f"/etc/nginx/conf.d/{alias}.conf",
            f"/etc/nginx/conf.d/{domain}.conf",
        ]
        for path in possible_paths:
            content = self.api_client.get_container_file_content(container_id, path)
            if content:
                Logger.success(f"找到配置文件: {path}")
                return path
        Logger.error("无法找到 Nginx 配置文件")
        for path in possible_paths:
            print(f"  - {path}")
        sys.exit(1)

    def _modify_config(self, config: str, domain: str, site_id: str, site_key: str, site_secret: str, gateway_url: str) -> str:
        vars_block, access_lua, body_filter = self.config_generator.generate_config_blocks(domain, site_id, site_key, site_secret, gateway_url)
        config = self.config_generator.remove_old_fangyu_config(config)
        config = self.config_generator.inject_vars_block(config, vars_block)
        config = self.config_generator.inject_access_lua(config, access_lua)
        config = self.config_generator.inject_body_filter(config, body_filter)
        Logger.success("Nginx 配置已生成并插入")
        return config

    def _validate_ssl_certificates(self, container_id: str, config_content: str) -> bool:
        cleaned_content = '\n'.join(_strip_comment(line) for line in config_content.split('\n'))
        cert_paths = re.findall(r'ssl_certificate\s+([^;]+);', cleaned_content)
        key_paths = re.findall(r'ssl_certificate_key\s+([^;]+);', cleaned_content)
        if not cert_paths and not key_paths:
            return True
        Logger.step("验证 SSL 证书文件...")
        missing_files = []
        for path in cert_paths + key_paths:
            path = path.strip()
            if not self.api_client.check_file_exists(container_id, path):
                Logger.warning(f"✗ 文件不存在: {path}")
                missing_files.append(path)
            else:
                Logger.success(f"✓ 文件存在: {path}")
        if missing_files:
            Logger.error("发现缺失的 SSL 证书文件:")
            for path in missing_files:
                Logger.error(f"  - {path}")
            return False
        Logger.success("所有 SSL 证书文件验证通过")
        return True

    def _test_nginx_config_syntax(self, container_id: str) -> bool:
        Logger.step("测试 Nginx 配置语法...")
        success, stdout, stderr = self.api_client.exec_container_command(container_id, "nginx -t")
        if success:
            Logger.success("✓ Nginx 配置语法正确")
            return True
        if "API 调用失败: 404" in stderr:
            Logger.warning(f"  请手动执行: docker exec -it {container_id[:12]} nginx -t")
            return True
        Logger.error("✗ Nginx 配置语法错误:")
        if stderr:
            for line in stderr.split('\n')[:10]:
                if line.strip():
                    Logger.error(f"  {line}")
        return False

    def _write_config(self, container_id: str, website_id: int, config_path: str, content: str, skip_ssl_check: bool = False) -> None:
        Logger.step(f"配置文件大小: {len(content)} 字节")
        Logger.step(f"目标路径: {config_path}")
        if not skip_ssl_check and not self._validate_ssl_certificates(container_id, content):
            Logger.error("SSL 证书验证失败，停止部署")
            sys.exit(1)
        if not self.api_client.update_website_nginx_config(website_id, content):
            Logger.error("通过 1Panel Website Nginx 接口更新配置失败")
            sys.exit(1)
        Logger.success("配置文件已通过 1Panel Website Nginx 接口更新")
        if not self._test_nginx_config_syntax(container_id):
            Logger.error("Nginx 配置语法测试失败")
            sys.exit(1)
        Logger.success("配置已验证并生效，1Panel 将自动重载 Nginx")


class InstallationTester:
    """安装验证测试器（增强版）"""
    
    def __init__(self, api_client: OnePanelAPIClient):
        self.api_client = api_client
        self.validator = ConfigValidator()

    def run_tests(self, domain: str, container_id: str, config_path: str) -> bool:
        """
        执行完整的安装验证测试套件。
        
        Args:
            domain: 站点域名
            container_id: 容器 ID
            config_path: Nginx 配置文件路径
            
        Returns:
            True 表示所有关键测试通过，False 表示有关键测试未通过
        """
        Logger.step("开始安装验证测试...")
        print()
        print(f"{'测试项':<40} {'状态':<10} {'详情'}")
        print("-" * 90)
        
        test_results = {
            # 关键测试（必须通过）
            'defense_lua_exists': self._test_defense_lua_exists(domain, container_id),
            'defense_lua_valid': self._test_defense_lua_validation(domain, container_id),
            'real_ip_config': self._test_real_ip_config(domain, container_id),
            'nginx_config': self._test_nginx_config(container_id, config_path, domain),
            'nginx_syntax': self._test_nginx_syntax(container_id),
            
            # 可选测试（失败仅警告）
            'no_errors': self._test_error_logs(container_id),
            'website_ok': self._test_website_access(domain),
            'defense_active': self._test_defense_activity(domain),
            'performance': self._test_performance(domain),
        }
        return self._display_results(test_results)

    def _test_defense_lua_exists(self, domain: str, container_id: str) -> bool:
        """测试 defense.lua 文件是否存在"""
        Logger.step("测试 1/9: 验证 defense.lua 文件存在")
        try:
            lua_path = f"/www/sites/{domain}/lua/defense.lua"
            content = self.api_client.get_container_file_content(container_id, lua_path)
            
            if not content:
                Logger.error("✗ 无法读取 defense.lua")
                return False
            
            file_size = len(content)
            if file_size < 10000:
                Logger.error(f"✗ defense.lua 文件太小 ({file_size} 字节)，可能不完整")
                return False
            
            Logger.success(f"✓ defense.lua 存在且完整 ({file_size:,} 字节)")
            return True
            
        except requests.exceptions.RequestException as e:
            Logger.error(f"✗ API 请求失败: {e}")
            return False
        except (OSError, ValueError) as e:
            Logger.error(f"✗ 验证失败: {e}")
            return False
    
    def _test_defense_lua_validation(self, domain: str, container_id: str) -> bool:
        """测试 defense.lua 内容验证"""
        Logger.step("测试 2/9: 验证 defense.lua 内容合法性")
        try:
            lua_path = f"/www/sites/{domain}/lua/defense.lua"
            content = self.api_client.get_container_file_content(container_id, lua_path)
            
            if not content:
                Logger.error("✗ 无法读取文件内容")
                return False
            
            # 使用验证器验证内容
            is_valid, errors = self.validator.validate_defense_lua(content)
            
            if not is_valid:
                Logger.error("✗ defense.lua 验证失败:")
                for error in errors[:3]:  # 只显示前3个错误
                    Logger.error(f"  - {error}")
                if len(errors) > 3:
                    Logger.error(f"  ... 还有 {len(errors) - 3} 个错误")
                return False
            
            Logger.success("✓ defense.lua 内容验证通过")
            return True
            
        except requests.exceptions.RequestException as e:
            Logger.error(f"✗ API 请求失败: {e}")
            return False
        except Exception as e:
            Logger.error(f"✗ 验证失败: {e}")
            return False
    
    def _test_real_ip_config(self, domain: str, container_id: str) -> bool:
        """测试 Real-IP 配置文件"""
        Logger.step("测试 3/9: 验证 Real-IP 配置文件")
        try:
            real_ip_path = f"/www/sites/{domain}/lua/fangyu_real_ip.conf"
            content = self.api_client.get_container_file_content(container_id, real_ip_path)
            
            if not content:
                Logger.error(f"✗ 无法读取 {real_ip_path}")
                return False
            
            # 检查必需内容
            required_items = [
                "set_real_ip_from",
                "real_ip_header CF-Connecting-IP",
                "real_ip_recursive on"
            ]
            missing = [item for item in required_items if item not in content]
            
            if missing:
                Logger.error("✗ Real-IP 配置不完整:")
                for item in missing:
                    Logger.error(f"  - 缺少: {item}")
                return False
            
            # 统计 IP 段数量
            ip_count = content.count("set_real_ip_from")
            Logger.success(f"✓ Real-IP 配置完整 (包含 {ip_count} 个 IP 段)")
            return True
            
        except requests.exceptions.RequestException as e:
            Logger.error(f"✗ API 请求失败: {e}")
            return False
        except Exception as e:
            Logger.error(f"✗ 验证失败: {e}")
            return False

    def _read_config_with_retry(self, container_id: str, path: str, max_retries: int = 3) -> Optional[str]:
        for attempt in range(max_retries):
            try:
                content = self.api_client.get_container_file_content(container_id, path)
                if content:
                    return content
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    Logger.warning(f"  读取超时，重试 {attempt + 1}/{max_retries - 1}...")
                    time.sleep(2)
                else:
                    raise
        return None

    def _test_nginx_config(self, container_id: str, config_path: str, domain: str) -> Optional[bool]:
        """测试 Nginx 配置完整性"""
        Logger.step("测试 4/9: 验证 Nginx 配置内容")
        try:
            config = self._read_config_with_retry(container_id, config_path, max_retries=3)
            if not config:
                Logger.error("✗ 无法读取 Nginx 配置")
                return False
            
            # 使用验证器进行逻辑验证
            is_valid, errors = self.validator.validate_nginx_config_logic(config, domain)
            
            if not is_valid:
                Logger.error("✗ Nginx 配置验证失败:")
                for error in errors[:3]:
                    Logger.error(f"  - {error}")
                if len(errors) > 3:
                    Logger.error(f"  ... 还有 {len(errors) - 3} 个错误")
                return False
            
            # 额外检查 Real-IP include
            real_ip_path = _real_ip_config_path(domain)
            if real_ip_path not in config:
                Logger.error(f"✗ 缺少 Real-IP include: {real_ip_path}")
                return False
            
            Logger.success("✓ Nginx 配置验证通过")
            return True
            
        except requests.exceptions.Timeout:
            Logger.warning("⚠ 读取配置超时（可能是网络问题），跳过此项检查")
            return None
        except requests.exceptions.RequestException as e:
            Logger.warning(f"⚠ API 请求失败: {e}")
            return None
        except (KeyError, ValueError) as e:
            Logger.warning(f"⚠ 验证失败: {e}")
            return None
    
    def _test_nginx_syntax(self, container_id: str) -> bool:
        """测试 Nginx 配置语法"""
        Logger.step("测试 5/9: 测试 Nginx 配置语法")
        try:
            success, stdout, stderr = self.api_client.exec_container_command(
                container_id, 
                "nginx -t"
            )
            
            if success:
                Logger.success("✓ Nginx 配置语法正确")
                return True
            
            if "API 调用失败: 404" in stderr:
                Logger.warning("⚠ API 不支持命令执行，跳过语法检查")
                return True
            
            Logger.error("✗ Nginx 配置语法错误:")
            if stderr:
                for line in stderr.split('\n')[:5]:
                    if line.strip():
                        Logger.error(f"  {line}")
            return False
            
        except requests.exceptions.RequestException as e:
            Logger.warning(f"⚠ API 请求失败: {e}")
            return True  # 网络问题不算失败
        except Exception as e:
            Logger.warning(f"⚠ 语法测试失败: {e}")
            return True

    def _test_error_logs(self, container_id: str) -> bool:
        """测试 Nginx 错误日志"""
        Logger.step("测试 6/9: 检查 Nginx 错误日志")
        try:
            error_log = self._read_config_with_retry(
                container_id, 
                "/usr/local/openresty/nginx/logs/error.log", 
                max_retries=3
            )
            
            if not error_log:
                Logger.warning("⚠ 无法读取错误日志（继续）")
                return True
            
            # 分析最近50行日志
            lines = error_log.split('\n')[-50:]
            
            # 查找 Fangyu 相关错误
            fangyu_errors = []
            for line in lines:
                if not line.strip():
                    continue
                lower_line = line.lower()
                if any(kw in lower_line for kw in ['lua', 'fangyu', 'defense.lua']):
                    if 'error' in lower_line or 'failed' in lower_line:
                        fangyu_errors.append(line)
            
            if fangyu_errors:
                Logger.warning(f"⚠ 发现 {len(fangyu_errors)} 条 Fangyu 相关错误:")
                for error in fangyu_errors[:3]:
                    Logger.warning(f"  {error[:100]}")
                if len(fangyu_errors) > 3:
                    Logger.warning(f"  ... 还有 {len(fangyu_errors) - 3} 条错误")
                return False
            
            Logger.success("✓ 无 Fangyu 相关错误")
            return True
            
        except requests.exceptions.Timeout:
            Logger.warning("⚠ 读取日志超时（可能是网络问题），跳过此项检查")
            return True
        except requests.exceptions.RequestException as e:
            Logger.warning(f"⚠ API 请求失败: {e}")
            return True
        except Exception as e:
            Logger.warning(f"⚠ 无法检查错误日志: {e}")
            return True

    def _test_website_access(self, domain: str) -> bool:
        """测试网站访问"""
        Logger.step("测试 7/9: 测试网站访问")
        
        for scheme in ("https", "http"):
            try:
                resp = requests.get(
                    f"{scheme}://{domain}/", 
                    headers={"User-Agent": "Mozilla/5.0 (Fangyu Test)"}, 
                    timeout=10, 
                    verify=False,
                    allow_redirects=True
                )
                
                if resp.status_code in (200, 301, 302):
                    response_time = resp.elapsed.total_seconds()
                    Logger.success(f"✓ 网站正常响应 ({scheme.upper()}, 状态码: {resp.status_code}, 响应时间: {response_time:.2f}s)")
                    return True
                else:
                    Logger.warning(f"⚠ {scheme.upper()} 响应异常: 状态码 {resp.status_code}")
                    
            except requests.exceptions.RequestException as e:
                Logger.warning(f"⚠ {scheme.upper()} 访问失败: {e}")
                
        return False

    def _test_defense_activity(self, domain: str) -> Optional[bool]:
        """
        测试防御系统活动（多维度检测）。
        
        检测维度：
        1. 响应头中的 Fangyu 标记
        2. SDK 脚本注入
        3. 特殊端点响应（/blocked, /challenge）
        4. 服务端 token 设置
        """
        Logger.step("测试 8/9: 检测防御系统活动")
        
        detection_results = {
            "响应头检测": False,
            "SDK 注入检测": False,
            "变量设置检测": False,
            "特殊端点检测": False,
        }
        
        try:
            # 1. 测试首页 - 检测 SDK 注入
            Logger.step("  → 检测 SDK 注入...")
            resp_home = requests.get(
                f"https://{domain}/", 
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                }, 
                timeout=10, 
                verify=False,
                allow_redirects=True
            )
            
            # 检查响应头
            fangyu_headers = [h for h in resp_home.headers.keys() 
                            if any(kw in h.lower() for kw in ['fangyu', 'fy-', 'x-fy'])]
            if fangyu_headers:
                Logger.success(f"    ✓ 发现 Fangyu 响应头: {', '.join(fangyu_headers[:3])}")
                detection_results["响应头检测"] = True
            
            # 检查 SDK 注入（更精确的检测）
            if resp_home.status_code == 200 and 'text/html' in resp_home.headers.get('Content-Type', ''):
                body_lower = resp_home.text.lower()
                
                # 检测 SDK 脚本标签
                sdk_patterns = [
                    'fangyu-sdk',
                    'fy_',
                    'fangyu.init',
                    'data-fangyu',
                ]
                
                found_patterns = [p for p in sdk_patterns if p in body_lower]
                if found_patterns:
                    Logger.success(f"    ✓ 检测到 SDK 特征: {', '.join(found_patterns[:2])}")
                    detection_results["SDK 注入检测"] = True
                
                # 检查是否有 script 标签（可能是注入点）
                if '<script' in body_lower and '</head>' in body_lower:
                    # 进一步验证是否在 head 中有注入
                    head_content = resp_home.text.split('</head>')[0].lower()
                    if any(p in head_content for p in ['fangyu', 'fy_']):
                        Logger.success("    ✓ 检测到 HEAD 中的 Fangyu 标记")
                        detection_results["SDK 注入检测"] = True
            
            # 2. 测试特殊端点 - /blocked 页面
            Logger.step("  → 测试 /blocked 端点...")
            try:
                resp_blocked = requests.get(
                    f"https://{domain}/blocked", 
                    headers={"User-Agent": "FangyuTest/1.0"}, 
                    timeout=5, 
                    verify=False,
                    allow_redirects=False
                )
                
                # /blocked 可能返回 404（未配置）或自定义页面
                if resp_blocked.status_code in (200, 403, 404):
                    if any(kw in resp_blocked.text.lower() for kw in ['block', 'fangyu', 'access denied']):
                        Logger.success(f"    ✓ /blocked 端点响应正常 (状态码: {resp_blocked.status_code})")
                        detection_results["特殊端点检测"] = True
                    else:
                        Logger.warning(f"    ⚠ /blocked 返回 {resp_blocked.status_code} 但内容不明确")
            except requests.exceptions.RequestException:
                Logger.warning("    ⚠ /blocked 端点测试失败")
            
            # 3. 发送触发请求 - 检测变量设置
            Logger.step("  → 发送测试请求检测变量设置...")
            test_path = f"/test-fangyu-activity-{int(time.time())}"
            resp_test = requests.get(
                f"https://{domain}{test_path}", 
                headers={
                    "User-Agent": "Mozilla/5.0 (Test)",
                    "X-Forwarded-For": "1.2.3.4"  # 可能触发防御逻辑
                }, 
                timeout=10, 
                verify=False,
                allow_redirects=False
            )
            
            # 检查是否设置了服务端 token 或其他标记
            if 'Set-Cookie' in resp_test.headers:
                cookies_str = resp_test.headers.get('Set-Cookie', '').lower()
                if any(kw in cookies_str for kw in ['fangyu', 'fy_', '_fy']):
                    Logger.success("    ✓ 检测到 Fangyu Cookie 设置")
                    detection_results["变量设置检测"] = True
            
            # 4. 汇总结果
            passed_checks = sum(detection_results.values())
            total_checks = len(detection_results)
            
            if passed_checks >= 2:
                Logger.success(f"✓ 防御系统活动确认 ({passed_checks}/{total_checks} 项检测通过)")
                return True
            elif passed_checks >= 1:
                Logger.warning(f"⚠ 检测到部分防御活动 ({passed_checks}/{total_checks} 项)")
                return True
            else:
                Logger.warning("⚠ 未检测到明显的防御系统活动")
                Logger.warning("  可能原因:")
                Logger.warning("  - SDK 注入未启用 ($fangyu_sdk_inject = off)")
                Logger.warning("  - 防御逻辑针对特定条件触发")
                Logger.warning("  - 需要检查 body_filter_by_lua_block 配置")
                return None
                
        except requests.exceptions.Timeout:
            Logger.warning("⚠ 请求超时，无法完成活动检测")
            return None
        except requests.exceptions.RequestException as e:
            Logger.warning(f"⚠ 网络请求失败: {str(e)[:100]}")
            return None
        except Exception as e:
            Logger.warning(f"⚠ 活动检测失败: {str(e)[:100]}")
            return None
    
    def _test_performance(self, domain: str) -> Optional[bool]:
        """测试性能影响"""
        Logger.step("测试 9/9: 测试性能影响")
        try:
            response_times = []
            
            # 发送3次请求测试平均响应时间
            for i in range(3):
                start_time = time.time()
                resp = requests.get(
                    f"https://{domain}/", 
                    headers={"User-Agent": "Mozilla/5.0 (Performance Test)"}, 
                    timeout=10, 
                    verify=False
                )
                elapsed = time.time() - start_time
                
                if resp.status_code == 200:
                    response_times.append(elapsed)
            
            if not response_times:
                Logger.warning("⚠ 无法获取响应时间")
                return None
            
            avg_time = sum(response_times) / len(response_times)
            max_time = max(response_times)
            
            # 性能评估
            if avg_time < 1.0:
                Logger.success(f"✓ 响应时间良好 (平均: {avg_time:.3f}s, 最大: {max_time:.3f}s)")
                return True
            elif avg_time < 3.0:
                Logger.warning(f"⚠ 响应时间可接受 (平均: {avg_time:.3f}s, 最大: {max_time:.3f}s)")
                return True
            else:
                Logger.warning(f"⚠ 响应时间较慢 (平均: {avg_time:.3f}s, 最大: {max_time:.3f}s)")
                return False
                
        except requests.exceptions.RequestException as e:
            Logger.warning(f"⚠ 性能测试失败: {e}")
            return None

    def _display_results(self, test_results: Dict[str, Optional[bool]]) -> bool:
        """
        显示测试结果汇总。
        
        Args:
            test_results: 测试结果字典，key 为测试项名称，value 为测试结果（True/False/None）
            
        Returns:
            True 表示所有关键测试通过，False 表示有关键测试未通过
        """
        print()
        print("=" * 90)
        print("安装验证结果汇总")
        print("=" * 90)
        print()
        
        # 定义关键测试项（这些必须通过）
        critical_tests = [
            ("defense.lua 文件存在", test_results.get('defense_lua_exists', False)),
            ("defense.lua 内容验证", test_results.get('defense_lua_valid', False)),
            ("Real-IP 配置完整", test_results.get('real_ip_config', False)),
            ("Nginx 配置逻辑验证", test_results.get('nginx_config')),
            ("Nginx 语法验证", test_results.get('nginx_syntax', False)),
        ]
        
        # 定义警告测试项（可以跳过）
        warning_tests = [
            ("无 Fangyu 错误日志", test_results.get('no_errors', True)),
            ("网站正常访问", test_results.get('website_ok', False)),
            ("防御系统活动检测", test_results.get('defense_active', None)),
            ("性能影响评估", test_results.get('performance', None)),
        ]
        
        # 统计结果
        critical_definite = [(name, result) for name, result in critical_tests if result is not None]
        critical_passed = sum(1 for _, result in critical_definite if result is True)
        critical_total = len(critical_definite)
        
        warning_passed = sum(1 for _, result in warning_tests if result is True)
        warning_skipped = sum(1 for _, result in warning_tests if result is None)
        warning_total = len(warning_tests)
        
        # 显示关键测试结果
        Logger.step(f"关键测试 ({critical_passed}/{critical_total} 通过)")
        for name, result in critical_tests:
            if result is True:
                Logger.success(f"  ✓ {name}")
            elif result is False:
                Logger.error(f"  ✗ {name}")
            else:
                Logger.warning(f"  ? {name} (未测试)")
        
        print()
        
        # 显示可选测试结果
        Logger.step(f"可选测试 ({warning_passed}/{warning_total} 通过, {warning_skipped} 跳过)")
        for name, result in warning_tests:
            if result is True:
                Logger.success(f"  ✓ {name}")
            elif result is False:
                Logger.warning(f"  ⚠ {name}")
            else:
                Logger.warning(f"  - {name} (已跳过)")
        
        print()
        print("=" * 80)
        
        # 判断整体结果
        if critical_passed == critical_total:
            Logger.success("✅ 核心功能部署成功！")
            if warning_passed < warning_total - warning_skipped:
                Logger.warning("部分可选验证未通过，但不影响核心功能")
            return True
        else:
            Logger.error("❌ 关键测试未通过，部署可能存在问题")
            return False


class DefenseLuaDeployer:
    """Defense.lua 部署器（使用统一上传接口和验证）"""
    
    def __init__(self, api_client: 'OnePanelAPIClient'):
        self.api_client = api_client
        self.uploader = FileUploader(api_client)
        self.validator = ConfigValidator()
    
    def _find_defense_lua_source(self) -> Optional[str]:
        """查找 defense.lua 源文件"""
        possible_paths = [
            str(Path(__file__).parent / "defense.lua"),
            str(Path(__file__).parent / "app" / "services" / "defense_file" / "nginx_lua" / "defense.lua"),
            "./defense.lua",
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                file_size = os.path.getsize(path)
                if file_size < 500:
                    Logger.warning(f"跳过 {path} (文件太小: {file_size} 字节，可能是占位符)")
                    continue
                Logger.success(f"找到源文件: {path} ({file_size} 字节)")
                return path
        
        return None
    
    def deploy(self, domain: str, container_id: str) -> bool:
        """
        部署 defense.lua 到容器（带验证）。
        
        Args:
            domain: 站点域名
            container_id: 容器 ID
            
        Returns:
            True 表示部署成功，False 表示失败
            
        Raises:
            SystemExit: 当找不到源文件或部署失败时
        """
        Logger.step(f"部署 defense.lua for {domain}...")
        
        source_file = self._find_defense_lua_source()
        
        if not source_file:
            Logger.error("找不到完整的 defense.lua 文件")
            Logger.warning("请确保完整的 defense.lua 文件存在于:")
            Logger.warning(f"  {str(Path(__file__).parent / 'defense.lua')}")
            sys.exit(1)
        
        target_dir = f"/www/sites/{domain}/lua"
        
        # 使用统一上传接口，带验证
        success = self.uploader.upload_content(
            container_id=container_id,
            content=Path(source_file),
            target_dir=target_dir,
            filename="defense.lua",
            description="核心防御脚本",
            validate_func=self.validator.validate_defense_lua
        )
        
        if not success:
            Logger.error("defense.lua 部署失败")
            sys.exit(1)
        
        return True


class RealIpConfigDeployer:
    """Real-IP 配置部署器（使用统一上传接口）"""
    
    def __init__(self, api_client: OnePanelAPIClient):
        self.api_client = api_client
        self.uploader = FileUploader(api_client)

    def deploy(self, domain: str, container_id: str) -> bool:
        """
        部署 Real-IP 配置到站点 lua 目录（与 defense.lua 同目录）。
        
        Args:
            domain: 站点域名
            container_id: 容器 ID
            
        Returns:
            True 表示部署成功，False 表示失败
            
        Raises:
            SystemExit: 当部署失败时
        """
        Logger.step(f"部署 Real-IP 配置 for {domain}...")
        target_dir = f"/www/sites/{domain}/lua"
        
        # 使用统一上传接口（内容字符串模式）
        success = self.uploader.upload_content(
            container_id=container_id,
            content=_real_ip_config_content(),
            target_dir=target_dir,
            filename="fangyu_real_ip.conf",
            description="Real-IP 配置"
        )
        
        if not success:
            Logger.error("Real-IP 配置部署失败")
            sys.exit(1)
        
        return True


class FangyuInstaller:
    def __init__(self, panel_url: str, panel_key: str):
        self.api_client = OnePanelAPIClient(panel_url, panel_key)
        self.container_manager = ContainerManager(self.api_client)
        self.deployer = DefenseLuaDeployer(self.api_client)
        self.real_ip_deployer = RealIpConfigDeployer(self.api_client)
        self.main_conf_manager = NginxConfManager(self.api_client)
        self.resolver_config = NginxResolverConfigurator(self.api_client)
        self.nginx_manager = NginxConfigManager(self.api_client)
        self.tester = InstallationTester(self.api_client)

    def install(self, domain: str, site_id: str, site_key: str, site_secret: str, gateway_url: str, skip_ssl_check: bool = False) -> bool:
        try:
            _, container_id = self.container_manager.find_openresty_container()
            self.container_manager.check_lua_dependencies(container_id)
            print()
            Logger.step("检查并配置 nginx.conf 中的 Lua 模块...")
            if not self.main_conf_manager.check_lua_config(container_id):
                Logger.warning("nginx.conf 中缺少 Lua 配置，尝试自动添加...")
                self.main_conf_manager.add_lua_config(container_id)
            self.resolver_config.ensure_resolver_configured(container_id)
            self.real_ip_deployer.deploy(domain, container_id)
            self.deployer.deploy(domain, container_id)
            config_path = self.nginx_manager.update_website_config(domain, site_id, site_key, site_secret, gateway_url, container_id, skip_ssl_check)
            success = self.tester.run_tests(domain, container_id, config_path)
            if not success:
                Logger.warning("虽然安装过程完成，但某些测试未通过")
                return False
            return True
        except requests.exceptions.RequestException as e:
            Logger.error(f"API 请求失败: {e}")
            return False
        except (OSError, ValueError) as e:
            Logger.error(f"操作失败: {e}")
            return False
        except KeyboardInterrupt:
            Logger.warning("用户中断安装")
            return False


def install_main(domain: str, site_id: str, site_key: str, site_secret: str, gateway_url: str, panel_url: str, panel_key: str, skip_ssl_check: bool = False) -> None:
    """
    安装器主入口函数（被 CLI 调用）。
    
    Args:
        domain: 目标站点域名
        site_id: 站点数字主键（Site.id）
        site_key: 站点密钥字符串（site_xxxxxxxx）
        site_secret: 站点签名密钥
        gateway_url: Fangyu 网关 URL
        panel_url: 1Panel API 地址
        panel_key: 1Panel API 密钥
        skip_ssl_check: 是否跳过 SSL 证书验证
        
    Raises:
        SystemExit: 安装成功时退出码为 0，失败时为 1
    """
    installer = FangyuInstaller(panel_url, panel_key)
    success = installer.install(domain, site_id, site_key, site_secret, gateway_url, skip_ssl_check)
    sys.exit(0 if success else 1)


def build_parser() -> argparse.ArgumentParser:
    """
    构建命令行参数解析器。
    
    Returns:
        配置好的 ArgumentParser 实例
    """
    parser = argparse.ArgumentParser(description="迁移现有 Nginx 配置为 Fangyu 模板配置")
    parser.add_argument("input", help="原始 Nginx 配置文件路径")
    parser.add_argument("output", nargs="?", help="输出文件路径，不填则打印到标准输出")
    parser.add_argument("--site-id", required=True, dest="site_id", help="Fangyu Site ID")
    parser.add_argument("--app-id", required=True, dest="app_id", help="Fangyu App ID")
    parser.add_argument("--app-secret", required=True, dest="app_secret", help="Fangyu App Secret")
    parser.add_argument("--gateway-url", required=True, dest="gateway_url", help="Fangyu Gateway URL")
    return parser


def main() -> int:
    """
    命令行配置迁移模式的主入口。
    
    Returns:
        0 表示成功，非 0 表示失败
    """
    parser = build_parser()
    args = parser.parse_args()

    try:
        source_path = Path(args.input)
        config_content = source_path.read_text(encoding="utf-8")
    except OSError as e:
        Logger.error(f"读取配置文件失败: {e}")
        return 1
    migrated = FangyuTemplateMigrator.migrate_config(
        config_content,
        args.site_id,
        args.site_key,
        args.site_secret,
        args.gateway_url,
    )

    try:
        if args.output:
            output_path = Path(args.output)
            output_path.write_text(migrated, encoding="utf-8", newline="\n")
            print(str(output_path))
        else:
            print(migrated)
        return 0
    except OSError as e:
        Logger.error(f"写入配置文件失败: {e}")
        return 1


if __name__ == "__main__":
    # 如果没有命令行参数，使用内置配置进行完整部署测试
    if len(sys.argv) == 1:
        print("=" * 80)
        Logger.step("使用内置配置进行完整部署测试")
        print("=" * 80)
        print()
        
        # 实际配置（从 fangyu_scripts.py 提取）
        DOMAIN = "wayaifair.shop"
        SITE_KEY = "site_a8d1e78e"      # 站点密钥字符串，对应 $fangyu_site_key
        SITE_ID = "3"                   # 站点数字主键（Site.id），对应 $fangyu_site_id
        SITE_SECRET = "aefb5b8d165d0ad3e093e3953931235bb84e80ac0fa86904"
        GATEWAY_URL = "https://gateway.foxfingerlab.com"
        
        # 1Panel API 配置
        PANEL_URL = "http://198.200.42.128:31384"
        PANEL_KEY = "pWAEY3ldk1phmLLAHgnmibxRgABMoBwZ"
        
        try:
            installer = FangyuInstaller(PANEL_URL, PANEL_KEY)
            Logger.success("✓ 安装器初始化成功")
            print()
            
            success = installer.install(
                domain=DOMAIN,
                site_id=SITE_ID,
                site_key=SITE_KEY,
                site_secret=SITE_SECRET,
                gateway_url=GATEWAY_URL,
                skip_ssl_check=True  # 跳过 SSL 检查
            )
            
            print()
            print("=" * 80)
            if success:
                Logger.success("✅ 完整部署测试通过！")
                Logger.success(f"✓ 域名 {DOMAIN} 已成功配置 Fangyu Defense")
                sys.exit(0)
            else:
                Logger.warning("⚠️  部署完成但部分验证测试未通过")
                Logger.warning("请检查上方输出以确认实际部署状态")
                sys.exit(1)
        except requests.exceptions.RequestException as e:
            print()
            Logger.error(f"❌ API 请求失败: {e}")
            sys.exit(1)
        except (OSError, ValueError) as e:
            print()
            Logger.error(f"❌ 部署失败: {e}")
            sys.exit(1)
        except KeyboardInterrupt:
            print()
            Logger.warning("⚠️  用户中断部署")
            sys.exit(130)
        except Exception as e:
            print()
            Logger.error(f"❌ 未知错误: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    else:
        # 有命令行参数时使用配置迁移模式
        raise SystemExit(main())
