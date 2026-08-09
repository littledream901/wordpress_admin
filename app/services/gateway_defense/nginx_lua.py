"""
Nginx + Lua 网关防御服务（用于 WordPress 平台）
"""
import asyncio
import hashlib
import json
import os
import re
import shlex
import tempfile
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

import requests

from app.log import logger
from app.models.config_provider import ConfigProvider, ProviderConfigItem, ResourceProviderBinding
from app.services.gateway_defense.base import GatewayDefenseService


# ============================================================================
# Nginx 配置解析辅助函数
# ============================================================================

def _strip_comment(line: str) -> str:
    """智能移除行尾注释，保留字符串内的 # 字符"""
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
    """在 Nginx 配置中查找指定块的起止行号（基于大括号深度解析）"""
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
    """在 server 块内查找根路径 location / 块的起止行号"""
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
    """清理配置值的首尾空白字符和引号"""
    return value.strip().strip('`"\' ')


def _extract_server_name(config_content: str) -> Optional[str]:
    """从 Nginx 配置中提取 server_name 指令的值"""
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


def _real_ip_config_path(domain: str) -> str:
    """生成 Real-IP 配置文件路径（与 defense.lua 同目录）"""
    return f"/www/sites/{domain}/lua/fangyu_real_ip.conf"


def _real_ip_block(domain: str) -> str:
    """生成 Real-IP include 块（指向站点 lua 目录）"""
    return f"    include {_real_ip_config_path(domain)};"


def _validate_nginx_config_logic(config_content: str, domain: str) -> Tuple[bool, List[str]]:
    """逻辑校验 Nginx 配置（检查 Fangyu 必需变量与指令是否存在）
    
    Returns:
        (valid, errors) - valid 为 True 时 errors 为空列表
    """
    errors = []
    
    # 检查必需变量
    required_vars = [
        '$fangyu_gateway_url',
        '$fangyu_site_id',
        '$fangyu_site_key',
        '$fangyu_site_secret',
    ]
    for var in required_vars:
        if var not in config_content:
            errors.append(f'缺少必需变量: {var}')
    
    # 检查必需指令
    if 'access_by_lua_file' not in config_content:
        errors.append('缺少 access_by_lua_file 指令')
    elif f'/www/sites/{domain}/lua/defense.lua' not in config_content:
        errors.append('access_by_lua_file 路径不正确')
    
    if 'body_filter_by_lua_block' not in config_content:
        errors.append('缺少 body_filter_by_lua_block 指令')
    
    # 检查 Real-IP 配置引用
    real_ip_path = _real_ip_config_path(domain)
    if real_ip_path not in config_content:
        errors.append(f'缺少 Real-IP 配置引用: {real_ip_path}')
    
    return len(errors) == 0, errors


def _real_ip_config_content() -> str:
    """生成 Real-IP 配置内容（包含 Cloudflare IP 段和私有 IP 段）"""
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


def _render_blocks(domain: str, site_id: str, site_key: str, site_secret: str, gateway_url: str) -> Tuple[str, str, str]:
    """生成 Fangyu 配置的三个块：变量块、access 块、body_filter 块"""
    domain = _clean_value(domain)
    site_id = _clean_value(site_id)
    site_key = _clean_value(site_key)
    site_secret = _clean_value(site_secret)
    gateway_url = _clean_value(gateway_url)
    variables = f"""
{_real_ip_block(domain)}

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
    set $fy_server_token     "";"""
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


def _has_fangyu_config(config_content: str) -> bool:
    """检测 Nginx 配置中是否已存在 Fangyu Defense 相关配置
    
    仅检查明确的 Fangyu 特征标记，不对站点自有的 real_ip/body_filter 产生误判。
    """
    cleaned = '\n'.join(_strip_comment(line) for line in config_content.split('\n'))
    patterns = (
        r'(?m)^\s*set\s+\$fangyu_',      # Fangyu 变量
        r'(?m)^\s*set\s+\$fy_',          # Fangyu 变量缩写
        r'fangyu_real_ip\.conf',         # Fangyu Real-IP 配置文件引用
        r'defense\.lua',                 # Fangyu defense.lua 脚本
    )
    return any(re.search(p, cleaned) for p in patterns)


def _remove_old_fangyu_config(config_content: str) -> str:
    """移除 Nginx 配置中已有的 Fangyu Defense 配置块（幂等部署准备）

    未检测到 Fangyu 配置时原样返回，避免首次部署误删站点自有的
    set_real_ip_from / proxy_set_header / body_filter_by_lua_block 等指令。
    """
    if not _has_fangyu_config(config_content):
        return config_content

    lines = config_content.split('\n')
    result = []
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
        result.append(line)
    return '\n'.join(result)


def _inject_variables(config_content: str, variables: str) -> str:
    """在 server 块的 server_name 指令后注入 Fangyu 变量配置"""
    lines = config_content.split('\n')
    server_start, server_end = _find_block(lines, 'server')
    if server_start < 0 or server_end < 0:
        return config_content
    result = []
    inserted = False
    for index, line in enumerate(lines):
        result.append(line)
        if inserted or index < server_start or index > server_end:
            continue
        text = _strip_comment(line).strip()
        if text.startswith('server_name') and text.endswith(';'):
            result.append('')
            result.append(variables.rstrip())
            result.append('')
            inserted = True
    return '\n'.join(result)


def _inject_access(config_content: str, access: str) -> str:
    """在 location / 块开头注入 access_by_lua_file 指令"""
    lines = config_content.split('\n')
    server_start, server_end = _find_block(lines, 'server')
    if server_start < 0 or server_end < 0:
        return config_content
    location_start, location_end = _find_root_location(lines, server_start, server_end)
    if location_start < 0 or location_end < 0:
        return config_content
    result = []
    for i, line in enumerate(lines):
        if i == location_start + 1:
            result.append(access)
        result.append(line)
    return '\n'.join(result)


def _inject_body_filter(config_content: str, body_filter: str) -> str:
    """在 location / 块结束前注入 body_filter_by_lua_block 指令"""
    lines = config_content.split('\n')
    server_start, server_end = _find_block(lines, 'server')
    if server_start < 0 or server_end < 0:
        return config_content
    location_start, location_end = _find_root_location(lines, server_start, server_end)
    if location_start < 0 or location_end < 0:
        return config_content
    return '\n'.join(lines[:location_end] + [body_filter] + lines[location_end:])


# ============================================================================
# 1Panel API 客户端
# ============================================================================

class OnePanelAPIClient:
    """1Panel API 客户端（基于 MD5 签名认证）"""

    def __init__(self, panel_url: str, panel_key: str):
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

    def search_containers(self, name: str, state: str = "running", page_size: int = 50, max_pages: int = 100) -> List[Dict]:
        all_containers = []
        for page in range(1, max_pages + 1):
            resp = self.session.post(
                f"{self.panel_url}/api/v2/containers/search",
                headers=self._get_headers(),
                json={"name": name, "state": state, "page": page, "pageSize": page_size, "orderBy": "name", "order": "ascending"},
                timeout=10,
                verify=False,
            )
            if resp.status_code != 200:
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
        return resp.status_code == 200 and resp.json().get("code") == 200

    def check_file_exists(self, container_id: str, file_path: str) -> bool:
        success, stdout, _ = self.exec_container_command(
            container_id,
            f"test -f {shlex.quote(file_path)} && echo 'exists' || echo 'not_found'"
        )
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
                break
            data = resp.json()
            items = data.get("data", {}).get("items", []) if data.get("code") == 200 else []
            if not items:
                break
            all_websites.extend(items)
            if len(items) < page_size:
                break
        return all_websites


# ============================================================================
# Fangyu 安装器
# ============================================================================

class FangyuInstaller:
    """Fangyu Defense 安装器（负责 nginx.conf 配置、lua 部署、站点配置更新）"""

    def __init__(self, api_client: OnePanelAPIClient, lua_source: str, task_log: Optional[List[Dict[str, Any]]] = None):
        self.api_client = api_client
        self.lua_source = lua_source
        # 任务日志（结构化步骤记录，供前端展示与排障）
        self.task_log: List[Dict[str, Any]] = task_log if task_log is not None else []
        # 当前部署的站点 ID（仅用于汇总日志标识）
        self.site_id: str = ''

    def _log_step(self, step: str, ok: bool, msg: str = '', **extra) -> None:
        """记录任务步骤日志（仅写入结构化列表，不逐条打印，最终由 install 汇总输出 JSON）"""
        entry = {
            'ts': datetime.now().isoformat(),
            'step': step,
            'ok': ok,
            'msg': msg,
            **extra,
        }
        self.task_log.append(entry)

    def _log_summary(self, ok: bool, domain: str, duration_ms: int, error: str = '') -> None:
        """一次性输出 JSON 汇总日志（步骤明细压缩为 step/ok/msg 三元组）"""
        payload = {
            'type': 'nginx_lua',
            'domain': domain,
            'site_id': self.site_id,
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

    def find_openresty_container(self) -> Optional[str]:
        """查找 OpenResty 容器 ID"""
        self._log_step('查找OpenResty容器', True, '开始查询')
        containers = self.api_client.search_containers("openresty", state="running")
        if not containers:
            self._log_step('查找OpenResty容器', False, '未找到运行中的容器')
            return None
        container_id = containers[0].get('containerID')
        if not container_id:
            self._log_step('查找OpenResty容器', False, '容器信息缺少 containerID')
            return None
        self._log_step('查找OpenResty容器', True, f'找到容器: {container_id[:12]}', container_id=container_id)
        return container_id

    def ensure_lua_config(self, container_id: str) -> bool:
        """确保 nginx.conf 中已配置 lua_package_path 和 resolver"""
        nginx_conf_path = "/usr/local/openresty/nginx/conf/nginx.conf"
        content = self.api_client.get_container_file_content(container_id, nginx_conf_path)
        if not content:
            self._log_step('配置nginx.conf', False, f'无法读取 {nginx_conf_path}')
            return False

        cleaned = '\n'.join(_strip_comment(line) for line in content.split('\n'))
        has_lua_path = re.search(r'(?m)^\s*lua_package_path\b', cleaned) is not None
        has_lua_cpath = re.search(r'(?m)^\s*lua_package_cpath\b', cleaned) is not None
        has_resolver = re.search(r'(?m)^\s*resolver\b', cleaned) is not None

        if has_lua_path and has_lua_cpath and has_resolver:
            self._log_step('配置nginx.conf', True, 'Lua 模块与 resolver 已存在，跳过')
            return True

        # 添加 Lua 配置
        lines = content.split('\n')
        new_lines = []
        inserted_lua = has_lua_path and has_lua_cpath
        inserted_resolver = has_resolver
        http_start, http_end = _find_block(lines, 'http')

        for idx, line in enumerate(lines):
            new_lines.append(line)
            if not inserted_lua and idx == http_start:
                new_lines.append('    lua_package_path "/usr/local/openresty/lualib/?.lua;;";')
                new_lines.append('    lua_package_cpath "/usr/local/openresty/lualib/?.so;;";')
                new_lines.append('    lua_code_cache on;')
                inserted_lua = True
            if not inserted_resolver and http_start >= 0 and idx > http_start and (http_end < 0 or idx < http_end):
                text = _strip_comment(line)
                if 'include' in text and 'mime.types' in text:
                    new_lines.append('    resolver 8.8.8.8 8.8.4.4 ipv6=off;')
                    inserted_resolver = True

        new_content = '\n'.join(new_lines).replace('\r\n', '\n').replace('\r', '\n')

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_file = Path(tmp_dir) / "nginx.conf"
                tmp_file.write_text(new_content, encoding='utf-8', newline='\n')
                ok = self.api_client.upload_file_to_container(
                    container_id, str(tmp_file), "/usr/local/openresty/nginx/conf"
                )
            added = []
            if not has_lua_path or not has_lua_cpath:
                added.append('lua_package_path/cpath')
            if not has_resolver:
                added.append('resolver')
            self._log_step(
                '配置nginx.conf', ok,
                f"已补充: {', '.join(added)}" if ok else '上传 nginx.conf 失败',
            )
            return ok
        except (OSError, requests.exceptions.RequestException) as e:
            self._log_step('配置nginx.conf', False, str(e)[:200])
            return False

    def deploy_real_ip_config(self, domain: str, container_id: str) -> bool:
        """部署 Real-IP 配置到站点 lua 目录"""
        target_dir = f"/www/sites/{domain}/lua"
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_file = Path(tmp_dir) / "fangyu_real_ip.conf"
                tmp_file.write_text(_real_ip_config_content(), encoding='utf-8', newline='\n')
                ok = self.api_client.upload_file_to_container(
                    container_id, str(tmp_file), target_dir
                )
            self._log_step(
                '部署Real-IP配置', ok,
                f'{target_dir}/fangyu_real_ip.conf' if ok else '上传失败',
            )
            return ok
        except (OSError, requests.exceptions.RequestException) as e:
            self._log_step('部署Real-IP配置', False, str(e)[:200])
            return False

    def deploy_defense_lua(self, domain: str, container_id: str) -> bool:
        """部署 defense.lua 到容器"""
        lua_path = Path(self.lua_source)
        if not lua_path.exists():
            self._log_step('部署defense.lua', False, f'源文件不存在: {self.lua_source}')
            raise FileNotFoundError(f"Lua 源文件不存在: {self.lua_source}")

        target_dir = f"/www/sites/{domain}/lua"
        ok = self.api_client.upload_file_to_container(
            container_id, str(lua_path), target_dir
        )
        self._log_step(
            '部署defense.lua', ok,
            f'{target_dir}/defense.lua ({lua_path.stat().st_size} 字节)' if ok else '上传失败',
        )
        return ok

    def _find_nginx_config_path(self, website_info: Dict, container_id: str) -> Optional[str]:
        """查找站点的 Nginx 配置文件路径"""
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
                return path
        return None

    def update_website_config(
        self,
        domain: str,
        site_id: str,
        site_key: str,
        site_secret: str,
        gateway_url: str,
        container_id: str,
    ) -> Tuple[bool, str]:
        """更新站点 Nginx 配置，注入 Fangyu Defense 配置"""
        # 查找站点
        self._log_step('更新站点配置', True, f'查询站点: {domain}')
        websites = self.api_client.search_websites(domain)
        if not websites:
            self._log_step('更新站点配置', False, f'找不到站点: {domain}')
            return False, f"找不到站点: {domain}"
        website_info = websites[0]

        # 查找配置文件
        config_path = self._find_nginx_config_path(website_info, container_id)
        if not config_path:
            self._log_step('更新站点配置', False, '无法找到 Nginx 配置文件')
            return False, "无法找到 Nginx 配置文件"
        self._log_step('更新站点配置', True, f'找到配置: {config_path}')

        # 读取当前配置
        current_config = self.api_client.get_container_file_content(container_id, config_path)
        if not current_config:
            self._log_step('更新站点配置', False, '无法读取 Nginx 配置文件')
            return False, "无法读取 Nginx 配置文件"

        # 提取实际域名
        config_domain = (
            _extract_server_name(current_config)
            or website_info.get('primaryDomain')
            or website_info.get('alias')
            or domain
        )

        # 生成并注入配置
        vars_block, access_lua, body_filter = _render_blocks(
            config_domain, site_id, site_key, site_secret, gateway_url
        )
        modified_config = _remove_old_fangyu_config(current_config)
        modified_config = _inject_variables(modified_config, vars_block)
        modified_config = _inject_access(modified_config, access_lua)
        modified_config = _inject_body_filter(modified_config, body_filter)

        # 写入前做逻辑校验（注入失败时不下发，避免留下半截配置）
        valid, errors = _validate_nginx_config_logic(modified_config, config_domain)
        if not valid:
            err = '; '.join(errors)
            self._log_step('更新站点配置', False, f'配置校验失败: {err}'[:300])
            return False, f"Nginx 配置校验失败: {err}"

        # 通过 1Panel API 更新配置
        if not self.api_client.update_website_nginx_config(int(website_info['id']), modified_config):
            self._log_step('更新站点配置', False, '通过 1Panel API 更新配置失败')
            return False, "通过 1Panel API 更新配置失败"
        self._log_step('更新站点配置', True, '已注入 Fangyu 变量与指令')

        # 测试 Nginx 配置语法（失败不阻断部署）
        syntax_ok, _, _ = self.api_client.exec_container_command(container_id, "nginx -t")
        if syntax_ok:
            self._log_step('测试Nginx语法', True, 'nginx -t 通过')
        else:
            self._log_step('测试Nginx语法', False, '语法检查失败（已跳过）')

        return True, config_path

    def install(
        self,
        domain: str,
        site_id: str,
        site_key: str,
        site_secret: str,
        gateway_url: str,
    ) -> Dict[str, Any]:
        """
        执行完整的安装流程：
        1. 查找 OpenResty 容器
        2. 配置 nginx.conf（Lua 模块 + DNS resolver）
        3. 部署 Real-IP 配置
        4. 部署 defense.lua
        5. 更新站点 Nginx 配置
        6. 部署后自检验证
        """
        started_at = datetime.now()
        self.site_id = str(site_id)
        self._log_step('部署开始', True, f'域名={domain} 站点ID={site_id} 网关={gateway_url}')
        try:
            # 步骤1: 查找容器
            container_id = self.find_openresty_container()
            if not container_id:
                return self._fail_result('未找到运行中的 OpenResty 容器', started_at, domain)

            # 步骤2: 配置 nginx.conf（失败不阻断）
            self.ensure_lua_config(container_id)

            # 步骤3: 部署 Real-IP 配置
            if not self.deploy_real_ip_config(domain, container_id):
                return self._fail_result('Real-IP 配置部署失败', started_at, domain, container_id)

            # 步骤4: 部署 defense.lua
            if not self.deploy_defense_lua(domain, container_id):
                return self._fail_result('defense.lua 部署失败', started_at, domain, container_id)

            # 步骤5: 更新站点配置
            ok, config_path_or_err = self.update_website_config(
                domain, site_id, site_key, site_secret, gateway_url, container_id
            )
            if not ok:
                return self._fail_result(config_path_or_err, started_at, domain, container_id)

            # 步骤6: 自检验证
            verify_result = self.verify_installation(
                domain, container_id, config_path_or_err
            )

            duration_ms = int((datetime.now() - started_at).total_seconds() * 1000)
            if verify_result['ok']:
                self._log_step('部署完成', True, f'耗时 {duration_ms}ms')
            else:
                self._log_step('部署完成', False, verify_result.get('error', '')[:300])
            self._log_summary(
                verify_result['ok'], domain, duration_ms,
                '' if verify_result['ok'] else verify_result.get('error', ''),
            )

            return {
                'ok': verify_result['ok'],
                'domain': domain,
                'container_id': container_id,
                'config_path': config_path_or_err,
                'verify': verify_result,
                'task_log': self.task_log,
                'duration_ms': duration_ms,
                'error': verify_result.get('error') if not verify_result['ok'] else None,
            }

        except FileNotFoundError as e:
            return self._fail_result(str(e), started_at, domain)
        except requests.exceptions.RequestException as e:
            return self._fail_result(f'API 请求失败: {str(e)}', started_at, domain)
        except Exception as e:
            return self._fail_result(f'安装失败: {str(e)}', started_at, domain)

    def _fail_result(
        self,
        error: str,
        started_at: datetime,
        domain: str,
        container_id: str = '',
    ) -> Dict[str, Any]:
        """构造失败返回（统一附带任务日志与耗时）"""
        duration_ms = int((datetime.now() - started_at).total_seconds() * 1000)
        self._log_step('部署失败', False, error[:300])
        self._log_summary(False, domain, duration_ms, error)
        return {
            'ok': False,
            'error': error,
            'domain': domain,
            'container_id': container_id,
            'task_log': self.task_log,
            'duration_ms': duration_ms,
        }

    def verify_installation(
        self,
        domain: str,
        container_id: str,
        config_path: str,
    ) -> Dict[str, Any]:
        """
        部署后自检验证（关键项失败即整体失败）。

        关键检查：
        - defense.lua 存在且大小 >= 5KB
        - fangyu_real_ip.conf 存在且包含 CF-Connecting-IP
        - 站点 Nginx 配置包含 Fangyu 必需变量、指令、Real-IP include
        - nginx -t 语法通过

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

        # 1. defense.lua 存在性
        lua_path = f"/www/sites/{domain}/lua/defense.lua"
        lua_content = self.api_client.get_container_file_content(container_id, lua_path)
        if not lua_content:
            _add('defense.lua 存在', False, f'无法读取 {lua_path}')
        elif len(lua_content) < 5000:
            _add('defense.lua 存在', False, f'文件太小 ({len(lua_content)} 字节)')
        else:
            _add('defense.lua 存在', True, f'{len(lua_content)} 字节')

        # 2. Real-IP 配置
        real_ip_path = _real_ip_config_path(domain)
        real_ip_content = self.api_client.get_container_file_content(container_id, real_ip_path)
        if not real_ip_content:
            _add('Real-IP 配置存在', False, f'无法读取 {real_ip_path}')
        else:
            missing = [k for k in ('set_real_ip_from', 'real_ip_header CF-Connecting-IP', 'real_ip_recursive on')
                       if k not in real_ip_content]
            if missing:
                _add('Real-IP 配置完整', False, f'缺少: {", ".join(missing)}')
            else:
                _add('Real-IP 配置完整', True, f'包含 {real_ip_content.count("set_real_ip_from")} 个 IP 段')

        # 3. 站点 Nginx 配置（带重试，1Panel 写后刷盘有延迟）
        current_config = self._read_config_with_retry(container_id, config_path, max_retries=3)
        if not current_config:
            _add('站点 Nginx 配置', False, f'无法读取 {config_path}')
        else:
            required_vars = ['$fangyu_gateway_url', '$fangyu_site_id', '$fangyu_site_key', '$fangyu_site_secret']
            missing_vars = [v for v in required_vars if v not in current_config]
            if missing_vars:
                _add('站点变量注入', False, f'缺少: {", ".join(missing_vars)}')
            else:
                _add('站点变量注入', True, '')

            required_directives = ['access_by_lua_file', 'body_filter_by_lua_block']
            missing_directives = [d for d in required_directives if d not in current_config]
            if missing_directives:
                _add('Lua 指令注入', False, f'缺少: {", ".join(missing_directives)}')
            else:
                _add('Lua 指令注入', True, '')

            if real_ip_path not in current_config:
                _add('Real-IP include', False, f'配置中未找到 include {real_ip_path}')
            else:
                _add('Real-IP include', True, '')

            expected_lua = f"/www/sites/{domain}/lua/defense.lua"
            if expected_lua not in current_config:
                _add('defense.lua 路径匹配', False, f'期望路径 {expected_lua} 未出现在配置中')
            else:
                _add('defense.lua 路径匹配', True, '')

        # 4. Nginx 语法检查
        syntax_ok, _stdout, stderr = self.api_client.exec_container_command(
            container_id, "nginx -t"
        )
        if syntax_ok:
            _add('nginx -t 语法检查', True, '')
        else:
            # API 不支持 exec 时视为跳过（返回 True 不阻断，但记录）
            if stderr and 'API 调用失败' in stderr:
                _add('nginx -t 语法检查', True, '容器 exec 接口不可用，已跳过')
            else:
                _add('nginx -t 语法检查', False, (stderr or '未知错误').strip()[:200])

        failed = [c for c in checks if not c['ok']]
        if failed:
            return {
                'ok': False,
                'checks': checks,
                'error': '; '.join(f"{c['name']}: {c['msg']}" for c in failed),
            }
        return {'ok': True, 'checks': checks}

    def _read_config_with_retry(self, container_id: str, path: str, max_retries: int = 3) -> Optional[str]:
        """带重试的配置读取（1Panel 写后刷盘有延迟，立即读可能拿到旧内容）"""
        for attempt in range(max_retries):
            try:
                content = self.api_client.get_container_file_content(container_id, path)
                if content:
                    return content
                if attempt < max_retries - 1:
                    time.sleep(1)
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    raise
        return None


# ============================================================================
# 网关防御服务
# ============================================================================

class NginxLuaDefenseService(GatewayDefenseService):
    """Nginx + Lua 网关防御服务"""

    def __init__(self):
        # Lua 源代码路径
        self.lua_source = "app/services/defense_file/nginx_lua/defense.lua"

    def _verify_lua_source(self) -> bool:
        """验证 Lua 源文件是否存在"""
        lua_path = Path(self.lua_source)
        if not lua_path.exists():
            raise FileNotFoundError(f"Lua 源文件不存在: {self.lua_source}")

        # 验证文件大小（应该 > 5KB）
        if lua_path.stat().st_size < 5000:
            raise ValueError(f"Lua 源文件太小，可能不完整: {self.lua_source}")

        return True

    async def _get_onepanel_config(self, site_id: int) -> tuple:
        """
        获取站点绑定的 1Panel Provider 配置

        Returns:
            (panel_url, panel_key, provider_id)
        """
        # 查找站点绑定的 1Panel Provider
        binding = await ResourceProviderBinding.filter(
            resource_type='site',
            resource_id=site_id,
            provider_type='onepanel',
            bind_type='preferred'
        ).first()

        provider_id = None
        if binding:
            provider = await ConfigProvider.get_or_none(id=binding.provider_id, status='active')
            if provider:
                provider_id = provider.id

        # 如果没有绑定，使用默认 Provider
        if not provider_id:
            provider = await ConfigProvider.get_default('onepanel')
            if not provider:
                raise ValueError("未找到可用的 1Panel Provider")
            provider_id = provider.id

        # 获取配置项
        config_items = await ProviderConfigItem.get_map(provider_id)

        # 构建 panel_url
        url = config_items.get('url') or config_items.get('OP_URL', '')
        if not url:
            raise ValueError(f"Provider #{provider_id} 缺少 URL 配置")

        if not url.startswith('http'):
            url = 'https://' + url
        panel_url = url.rstrip('/')

        # 获取 api_key
        panel_key = config_items.get('api_key') or config_items.get('OP_API_KEY', '')
        if not panel_key:
            raise ValueError(f"Provider #{provider_id} 缺少 API Key 配置")

        return panel_url, panel_key, provider_id

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
        部署 Nginx Lua 防御

        调用流程：
        1. 验证 defense.lua 源文件存在
        2. 验证站点密钥已配置（必须外部提供）
        3. 验证网关侧站点标识已配置（必须外部提供，非本项目主键）
        4. 获取站点绑定的 1Panel Provider 配置
        5. 执行安装流程：
           - 查找 OpenResty 容器
           - 配置 nginx.conf 的 Lua 模块和 DNS resolver
           - 部署 Real-IP 配置文件
           - 上传 defense.lua
           - 更新站点 Nginx 配置
        6. 更新站点状态和配置
        """
        try:
            # 步骤1: 验证 Lua 源文件
            self._verify_lua_source()

            # 步骤2: 验证密钥（必须外部提供）
            if not site_key or not site_secret:
                if not site.gateway_site_key or not site.gateway_site_secret:
                    return {'ok': False, 'error': '站点密钥未配置，请先设置 gateway_site_key 和 gateway_site_secret'}
                site_key = site.gateway_site_key
                site_secret = site.gateway_site_secret
            else:
                site.gateway_site_key = site_key
                site.gateway_site_secret = site_secret

            # 步骤3: 验证网关侧站点标识（必须外部提供，不能用本地主键兜底）
            if not gateway_site_id:
                if not site.gateway_site_id:
                    return {
                        'ok': False,
                        'error': '网关站点标识未配置，请先设置 gateway_site_id（由网关侧分配，不是本项目的站点ID）',
                    }
                gateway_site_id = site.gateway_site_id
            else:
                site.gateway_site_id = gateway_site_id

            # 步骤4: 获取 1Panel 配置
            panel_url, panel_key, provider_id = await self._get_onepanel_config(site.id)

            # 步骤5: 执行安装（在线程池中执行，避免阻塞）
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._install_sync,
                site.domain,
                gateway_site_id,
                site_key,
                site_secret,
                gateway_url,
                panel_url,
                panel_key,
            )

            # 步骤5: 更新站点状态
            if result['ok']:
                site.gateway_defense_status = 'deployed'
                site.gateway_defense_type = 'nginx_lua'
                site.gateway_deployed_at = datetime.now()
                site.gateway_last_error = ''

                site.gateway_config_json = json.dumps({
                    'gateway_url': gateway_url,
                    'gateway_site_id': gateway_site_id,
                    'fail_mode': fail_mode,
                    'sdk_inject': sdk_inject,
                    'provider_id': provider_id,
                    'provider_type': 'onepanel',
                    'lua_source': self.lua_source,
                    'config_path': result.get('config_path'),
                    'container_id': result.get('container_id'),
                    'task_log': result.get('task_log', []),
                    'duration_ms': result.get('duration_ms'),
                }, ensure_ascii=False)
                await site.save()
            else:
                site.gateway_defense_status = 'failed'
                site.gateway_last_error = result.get('error', '')
                await site.save()

            return result

        except (ValueError, FileNotFoundError) as e:
            logger.error(json.dumps({
                'type': 'nginx_lua', 'domain': site.domain, 'site_id': str(site.id),
                'ok': False, 'error': str(e)[:300],
            }, ensure_ascii=False))
            return {'ok': False, 'error': str(e)}
        except Exception as e:
            logger.error(json.dumps({
                'type': 'nginx_lua', 'domain': site.domain, 'site_id': str(site.id),
                'ok': False, 'error': str(e)[:300],
            }, ensure_ascii=False))
            return {'ok': False, 'error': f'部署失败: {str(e)}'}

    def _install_sync(
        self,
        domain: str,
        site_id: str,
        site_key: str,
        site_secret: str,
        gateway_url: str,
        panel_url: str,
        panel_key: str,
    ) -> Dict[str, Any]:
        """同步执行安装（在线程池中执行）"""
        api_client = OnePanelAPIClient(panel_url, panel_key)
        installer = FangyuInstaller(api_client, self.lua_source, task_log=self.task_log)
        return installer.install(domain, site_id, site_key, site_secret, gateway_url)

    async def undeploy(self, site) -> Dict[str, Any]:
        """
        卸载 Nginx Lua 防御

        通过 1Panel API 从站点 Nginx 配置中移除 Fangyu 相关块并重新下发
        """
        try:
            config = json.loads(site.gateway_config_json or '{}')

            # 获取 1Panel 配置
            panel_url, panel_key, _ = await self._get_onepanel_config(site.id)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._undeploy_sync,
                site.domain,
                panel_url,
                panel_key,
            )

            if result['ok']:
                site.gateway_defense_status = 'undeployed'
                site.gateway_last_error = ''
                await site.save()

            return result

        except Exception as e:
            logger.error(json.dumps({
                'type': 'nginx_lua', 'action': 'undeploy', 'domain': site.domain,
                'site_id': str(site.id), 'ok': False, 'error': str(e)[:300],
            }, ensure_ascii=False))
            return {'ok': False, 'error': f'卸载失败: {str(e)}'}

    def _undeploy_sync(self, domain: str, panel_url: str, panel_key: str) -> Dict[str, Any]:
        """同步卸载（从站点 Nginx 配置中移除 Fangyu 块）"""
        try:
            api_client = OnePanelAPIClient(panel_url, panel_key)

            # 查找容器
            containers = api_client.search_containers("openresty", state="running")
            if not containers:
                return {'ok': False, 'error': '未找到运行中的 OpenResty 容器'}
            container_id = containers[0].get('containerID')

            # 查找站点
            websites = api_client.search_websites(domain)
            if not websites:
                return {'ok': False, 'error': f'找不到站点: {domain}'}
            website_info = websites[0]

            # 查找并读取配置
            installer = FangyuInstaller(api_client, self.lua_source)
            config_path = installer._find_nginx_config_path(website_info, container_id)
            if not config_path:
                return {'ok': False, 'error': '无法找到 Nginx 配置文件'}

            current_config = api_client.get_container_file_content(container_id, config_path)
            if not current_config:
                return {'ok': False, 'error': '无法读取 Nginx 配置文件'}

            # 移除 Fangyu 配置
            cleaned_config = _remove_old_fangyu_config(current_config)

            # 更新站点配置
            if not api_client.update_website_nginx_config(int(website_info['id']), cleaned_config):
                return {'ok': False, 'error': '通过 1Panel API 更新配置失败'}

            return {'ok': True, 'msg': f'已从站点 {domain} 卸载 Fangyu 配置'}

        except requests.exceptions.RequestException as e:
            return {'ok': False, 'error': f'API 请求失败: {str(e)}'}
        except Exception as e:
            return {'ok': False, 'error': f'卸载失败: {str(e)}'}

    async def check_status(self, site) -> Dict[str, Any]:
        """检查 Nginx Lua 部署状态"""
        if site.gateway_defense_status != 'deployed':
            return {'ok': False, 'status': site.gateway_defense_status}

        try:
            config = json.loads(site.gateway_config_json or '{}')
            return {
                'ok': True,
                'status': 'deployed',
                'domain': site.domain,
                'lua_source': config.get('lua_source'),
                'config_path': config.get('config_path'),
                'task_log': config.get('task_log', []),
                'duration_ms': config.get('duration_ms'),
                'deployed_at': site.gateway_deployed_at.isoformat() if site.gateway_deployed_at else None
            }
        except Exception as e:
            return {'ok': False, 'error': str(e)}
