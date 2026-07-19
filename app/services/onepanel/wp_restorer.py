import logging
import os
import re
import secrets
import time
import uuid
from typing import Dict, List, Optional

import httpx

from app.utils.provider_resolver import ProviderResolver
from app.core.exceptions import WordPressOperationError
from .client import OnePanelAPI
from .file_manager import OnePanelFileManager
from .utils import _log, _provider_value, normalize_domain


def _extract_wp_error(resp: httpx.Response) -> str:
    """从 WordPress 错误页 HTML 中提取有意义的错误信息。"""
    status = resp.status_code
    body = resp.text or ""
    # 尝试解析 JSON（PHP shutdown handler 可能已输出 JSON fatal error）
    try:
        data = resp.json()
        if isinstance(data, dict) and 'error' in data:
            return f"HTTP {status}: {data.get('error', '')} (line {data.get('line', '?')})"
        return f"HTTP {status}: {body[:200]}"
    except Exception:
        pass
    title_m = re.search(r'<title>(.*?)<\/title>', body, re.IGNORECASE)
    title = title_m.group(1) if title_m else ""
    paragraphs = re.findall(r'<p[^>]*>(.*?)<\/p>', body, re.IGNORECASE)
    msg_parts = [re.sub(r'<[^>]+>', '', p).strip() for p in paragraphs]
    msg_parts = [p for p in msg_parts if p]
    parts = [f"HTTP {status}"]
    if title:
        parts.append(title)
    if msg_parts:
        parts.append(" | ".join(msg_parts[:3]))
    if not title and not msg_parts:
        plain = re.sub(r'<[^>]+>', ' ', body).strip()
        parts.append(' '.join(plain.split())[:300])
    return ": ".join(parts)


class OnePanelWordPressRestorer:
    """WordPress 站点后处理 —— 文件恢复、域名替换、Woo Key/CTX 注入"""

    def __init__(self, api: OnePanelAPI, file_manager: OnePanelFileManager):
        self.api = api
        self.file_manager = file_manager
        cfgs = ProviderResolver.sync_get_config_map('onepanel')
        self.template_backup_path = str(_provider_value(cfgs, 'OP_TEMPLATE_BACKUP_PATH', 'template_backup_path', '') or '')
        self.wp_app_key = str(_provider_value(cfgs, 'OP_WP_APP_KEY', 'wp_app_key', 'wordpress'))
        self.wp_app_root = str(_provider_value(cfgs, 'OP_WP_APP_ROOT', 'wp_app_root', f'/opt/1panel/apps/{self.wp_app_key}'))
        self.panel_base = str(_provider_value(cfgs, 'OP_PANEL_BASE', 'panel_base', '/opt/1panel'))
        raw_mode = str(_provider_value(cfgs, 'OP_RESTORE_MODE', 'restore_mode', 'safe')).strip().lower()
        if raw_mode in ('safe', 'wp_content'):
            self.restore_mode = 'safe'
        elif raw_mode == 'full_data':
            self.restore_mode = 'full_data'
        else:
            self.restore_mode = 'safe'
        self.old_source_domain = str(_provider_value(cfgs, 'OP_OLD_SOURCE_DOMAIN', 'old_source_domain', '') or '').strip()
        # SSL 验证：优先 pipeline Provider，回退 settings
        _wp_ssl = ProviderResolver.sync_get_config('pipeline', 'wp_verify_ssl', 'true')
        self.wp_verify_ssl = _wp_ssl.lower() != 'false'
        # 可配的额外根文件（如 .htaccess, wp-cli.yml 等）
        raw_root_files = cfgs.get('OP_RESTORE_ROOT_FILES') or ''
        self.restore_root_files = [x.strip() for x in raw_root_files.split(',') if x.strip()]
        self.woo_script = cfgs.get('OP_WOO_SCRIPT') or 'create-woo-key.php'
        self.ctx_script = cfgs.get('OP_CTX_SCRIPT') or 'ctx-refresh.php'
        self.woo_fetch_retries = int(cfgs.get('OP_WOO_FETCH_RETRIES') or '8')
        self.woo_fetch_interval = int(cfgs.get('OP_WOO_FETCH_INTERVAL') or '5')
        self.ctk_token = cfgs.get('OP_CTK_TOKEN') or ''

    def _data_root(self, service_name: str) -> str:
        """WordPress data 根目录（wp-config.php 和 PHP 脚本都在这里）"""
        return f'{self.wp_app_root}/{service_name}/data'

    def _find_child_path(self, roots: List[str], target_name: str, max_depth: int = 8,
                         exclude_prefixes: Optional[List[str]] = None) -> Optional[str]:
        """在多个根目录下递归查找指定文件/目录名"""
        exclude_prefixes = [p.rstrip('/') for p in (exclude_prefixes or [])]
        visited = set()
        queue: List[tuple] = [(r.rstrip('/'), 0) for r in roots if r]
        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth > max_depth:
                continue
            if any(current == p or current.startswith(p + '/') for p in exclude_prefixes):
                continue
            visited.add(current)
            try:
                items = self.file_manager.search(current) or []
            except Exception:
                continue
            for item in items:
                name = item.get('name')
                if not name:
                    continue
                child = f'{current}/{name}'
                if any(child == p or child.startswith(p + '/') for p in exclude_prefixes):
                    continue
                if name == target_name:
                    return child
                is_dir = bool(item.get('isDir')) or item.get('type') in ['dir', 'directory']
                if is_dir or '.' not in name:
                    queue.append((child, depth + 1))
        return None

    def _backup_full_path(self) -> str:
        p = self.template_backup_path
        if not p:
            return ''
        if p.startswith('/'):
            return p
        return f'{self.panel_base.rstrip("/")}/backup/{p.lstrip("/")}'

    def restore_files(self, service_name: str) -> None:
        """从模板备份恢复 WordPress 文件，支持 safe / full_data 两种模式"""
        if not self.template_backup_path:
            return

        target = f'{self.wp_app_root}/{service_name}'
        data_dir = f'{target}/data'
        wp_config_path = f'{data_dir}/wp-config.php'

        original_wp_config = self.file_manager.read(wp_config_path)

        full_backup = self._backup_full_path()
        # 使用唯一临时目录解压，避免复用固定目录导致旧文件污染
        temp_dir = f'/opt/1panel/tmp/restore_wp_{uuid.uuid4().hex[:12]}'
        self.file_manager.decompress(full_backup, temp_dir, 'tar.gz', wait=10)
        base = os.path.basename(full_backup).replace('.tar.gz', '')
        outer = f'{temp_dir}/{base}'

        extracted_roots = [outer, f'{outer}/wordpress', temp_dir]
        all_temp_dirs = [temp_dir]  # 记录所有临时目录，最后统一清理

        app_tar = None
        inner_tar = f'{outer}/app.tar.gz'
        if self.file_manager.exists(inner_tar):
            app_tar = inner_tar
        else:
            app_tar = self._find_child_path([outer, temp_dir], 'app.tar.gz', max_depth=4)

        if app_tar:
            self.file_manager.decompress(app_tar, temp_dir, 'tar.gz', wait=10)
            extracted_roots.extend([f'{temp_dir}/wordpress', temp_dir])
            # app.tar.gz 解压后可能带有 data/ 目录结构
            decomp_data = f'{temp_dir}/data'
            if self.file_manager.exists(decomp_data):
                extracted_roots.append(decomp_data)

        wp_content_src = self._find_child_path(extracted_roots, 'wp-content', max_depth=8)
        if not wp_content_src:
            raise WordPressOperationError("restore files", detail="未找到 wp-content")

        src_data = os.path.dirname(wp_content_src)

        if self.restore_mode == 'full_data':
            _logger = logging.getLogger(__name__)
            _logger.warning(
                'full_data 模式已启用：将覆盖 wp-admin / wp-includes / wp-content。'
                '这可能导致模板核心文件与当前 WordPress 镜像版本不兼容，'
                '生产环境建议使用 safe 模式。'
            )
            for name in ['wp-content', 'wp-admin', 'wp-includes']:
                try:
                    self.file_manager.delete(f'{data_dir}/{name}', is_dir=True)
                except Exception:
                    pass
                if self.file_manager.exists(f'{src_data}/{name}'):
                    self.file_manager.move([f'{src_data}/{name}'], data_dir, 'cut', wait=3)
            for item in self.file_manager.search(src_data):
                name = item.get('name')
                if not name or name == 'wp-config.php' or name in ['wp-content', 'wp-admin', 'wp-includes']:
                    continue
                try:
                    self.file_manager.delete(f'{data_dir}/{name}', is_dir=bool(item.get('isDir')))
                except Exception:
                    pass
                self.file_manager.move([f'{src_data}/{name}'], data_dir, 'cut', wait=1)
        else:
            try:
                self.file_manager.delete(f'{data_dir}/wp-content', is_dir=True)
            except Exception:
                pass
            self.file_manager.move([wp_content_src], data_dir, 'cut', wait=5)

        self.file_manager.save(wp_config_path, original_wp_config)

        # 恢复额外根文件（.htaccess, wp-cli.yml 等）
        if self.restore_root_files:
            src_data = f'{wp_content_src}/..'
            for name in self.restore_root_files:
                src_file = f'{src_data}/{name}'
                if self.file_manager.exists(src_file):
                    self.file_manager.delete(f'{data_dir}/{name}', is_dir=False)
                    self.file_manager.move([src_file], data_dir, 'cut', wait=1)

        # 清理所有临时目录
        for tmp in list(dict.fromkeys(all_temp_dirs)):
            try:
                self.file_manager.delete(tmp, is_dir=True)
            except Exception:
                pass

        try:
            self.file_manager.chmod(data_dir, mode=493, user='root', group='root', sub=True)
            self.file_manager.chmod(f'{data_dir}/wp-content', mode=493, sub=True)
            self.file_manager.chmod(f'{data_dir}/wp-content/uploads', mode=511, sub=True)
        except Exception:
            pass

    # --- 域名替换 ---

    def inject_domain_replace_script(self, service_name: str, old_domain: str, new_domain: str, target_protocol: str) -> str:
        """注入域名替换 PHP 脚本（处理 PHP serialize），返回 security token"""
        if not old_domain:
            old_domain = self.old_source_domain
        token = secrets.token_urlsafe(32)
        path = f'{self._data_root(service_name)}/domain-replace.php'
        target_url = f'{target_protocol}://{new_domain}'
        try:
            old_domain = normalize_domain(old_domain)
        except ValueError:
            pass
        try:
            new_domain = normalize_domain(new_domain)
        except ValueError:
            pass
        php = f'''<?php
header('Content-Type: application/json; charset=utf-8');
$token = '{token}';
if (!isset($_GET['token']) || !hash_equals($token, $_GET['token'])) {{ http_response_code(403); echo json_encode(['code'=>403,'msg'=>'forbidden']); exit; }}
define('WP_USE_THEMES', false);
require_once __DIR__ . '/wp-load.php';
global $wpdb;

$oldDomain = '{old_domain}';
$newDomain = '{new_domain}';
$targetUrl = '{target_url}';
$oldList = [
  'https://' . $oldDomain,
  'http://' . $oldDomain,
  'https:\\/\\/' . $oldDomain,
  'http:\\/\\/' . $oldDomain,
  $oldDomain,
];
$newList = [
  $targetUrl,
  $targetUrl,
  str_replace('/', '\\/\\/', $targetUrl),
  str_replace('/', '\\/\\/', $targetUrl),
  $newDomain,
];

function fc_replace_recursive($data, $oldList, $newList) {{
  if (is_array($data)) {{
    foreach ($data as $k => $v) {{ $data[$k] = fc_replace_recursive($v, $oldList, $newList); }}
    return $data;
  }}
  if (is_object($data)) {{
    foreach ($data as $k => $v) {{ $data->$k = fc_replace_recursive($v, $oldList, $newList); }}
    return $data;
  }}
  if (is_string($data)) {{ return str_replace($oldList, $newList, $data); }}
  return $data;
}}

function fc_replace_value($value, $oldList, $newList) {{
  if (!is_string($value) || $value === '') {{ return $value; }}
  $un = @unserialize($value);
  if ($un !== false || $value === 'b:0;') {{
    $newUn = fc_replace_recursive($un, $oldList, $newList);
    return serialize($newUn);
  }}
  return str_replace($oldList, $newList, $value);
}}

$tables = $wpdb->get_col('SHOW TABLES');
$changedRows = 0;
$changedCells = 0;
$processedTables = [];

// 只处理当前 WordPress 前缀的表，避免误扫其他系统表
$prefix = $wpdb->prefix;
foreach ($tables as $table) {{
  if ($prefix && strpos($table, $prefix) !== 0) {{ continue; }}
  $columns = $wpdb->get_results('SHOW COLUMNS FROM `' . str_replace('`', '``', $table) . '`');
  if (!$columns) {{ continue; }}
  $primary = '';
  $textCols = [];
  foreach ($columns as $col) {{
    if ($col->Key === 'PRI' && !$primary) {{ $primary = $col->Field; }}
    if (preg_match('/char|text|blob|json/i', $col->Type)) {{ $textCols[] = $col->Field; }}
  }}
  if (!$primary || !$textCols) {{ continue; }}
  $selectCols = array_merge([$primary], $textCols);
  $selectSql = 'SELECT `' . implode('`,`', array_map(function($c){{ return str_replace('`','``',$c); }}, $selectCols)) . '` FROM `' . str_replace('`','``',$table) . '`';
  $rows = $wpdb->get_results($selectSql, ARRAY_A);
  if (!$rows) {{ continue; }}
  foreach ($rows as $row) {{
    $updates = [];
    foreach ($textCols as $col) {{
      if (!array_key_exists($col, $row)) {{ continue; }}
      $oldVal = $row[$col];
      $newVal = fc_replace_value($oldVal, $oldList, $newList);
      if ($newVal !== $oldVal) {{ $updates[$col] = $newVal; $changedCells++; }}
    }}
    if ($updates) {{
      $wpdb->update($table, $updates, [$primary => $row[$primary]]);
      $changedRows++;
    }}
  }}
  $processedTables[] = $table;
}}

if (function_exists('update_option')) {{
  update_option('siteurl', $targetUrl);
  update_option('home', $targetUrl);
  update_option('blogname', $newDomain);
}}

echo json_encode([
  'code' => 200,
  'msg' => 'domain replace finished',
  'old_domain' => $oldDomain,
  'new_domain' => $newDomain,
  'target_url' => $targetUrl,
  'changed_rows' => $changedRows,
  'changed_cells' => $changedCells,
  'tables' => count($processedTables),
], JSON_UNESCAPED_UNICODE);
'''
        self.file_manager.save(path, php)
        return token

    def remove_domain_replace_script(self, service_name: str) -> None:
        self.file_manager.delete(f'{self._data_root(service_name)}/domain-replace.php', is_dir=False)

    def fetch_domain_replace(self, domain: str, token: str) -> dict:
        """通过 HTTP 调用域名替换 PHP 脚本。

        优先通过域名访问；若域名挂 Cloudflare 代理且源站暂无 SSL（525 错误），
        自动回退到 localhost 直连，绕过 CDN 层。
        """
        urls = [
            (f'http://{domain}/domain-replace.php?token={token}', {}),
            (f'https://{domain}/domain-replace.php?token={token}', {}),
            # 绕过 Cloudflare：直连 1Panel OpenResty（127.0.0.1:80），Host 头指向域名
            (f'http://127.0.0.1/domain-replace.php?token={token}', {'Host': domain}),
        ]
        last_error = ''
        for _ in range(6):
            for url, extra_headers in urls:
                try:
                    resp = httpx.get(url, headers=extra_headers, timeout=60,
                                     verify=self.wp_verify_ssl, follow_redirects=True)
                    if resp.status_code != 200:
                        last_error = _extract_wp_error(resp)
                        continue
                    if not resp.text or not resp.text.strip():
                        last_error = "empty response body"
                        continue
                    data = resp.json()
                    if data.get('code') == 200:
                        return data
                    last_error = resp.text[:500]
                except Exception as exc:
                    last_error = str(exc)
            time.sleep(5)
        raise WordPressOperationError("domain replace", detail=last_error)

    # --- wp-config ---

    def patch_wp_config(self, service_name: str, domain: str, protocol: str) -> None:
        """幂等写入/更新 WP_HOME / WP_SITEURL 及性能配置到 wp-config.php"""
        path = f'{self._data_root(service_name)}/wp-config.php'
        content = self.file_manager.read(path)
        target_home = f"{protocol}://{domain}"

        replacements = {
            "WP_HOME": f"define('WP_HOME', '{target_home}');",
            "WP_SITEURL": f"define('WP_SITEURL', '{target_home}');",
            "FS_METHOD": "define('FS_METHOD', 'direct');",
            "WP_MEMORY_LIMIT": "define('WP_MEMORY_LIMIT', '64M');",
            "WP_MAX_MEMORY_LIMIT": "define('WP_MAX_MEMORY_LIMIT', '128M');",
            "WP_POST_REVISIONS": "define('WP_POST_REVISIONS', 3);",
            "AUTOSAVE_INTERVAL": "define('AUTOSAVE_INTERVAL', 300);",
            "DISABLE_WP_CRON": "define('DISABLE_WP_CRON', true);",
        }

        for key, new_line in replacements.items():
            pattern = rf"define\s*\(\s*['\"]{key}['\"]\s*,\s*.*?\);"
            if re.search(pattern, content):
                content = re.sub(pattern, new_line, content)
            else:
                marker = "/* That's all, stop editing!"
                pos = content.find(marker)
                insert_text = f"\n// 1Panel clone settings\n{new_line}\n"
                if pos > 0:
                    content = content[:pos] + insert_text + content[pos:]
                else:
                    content += insert_text

        self.file_manager.save(path, content)

    # --- WooCommerce Key ---

    def inject_woo_script(self, service_name: str) -> str:
        """注入 WooCommerce API Key 生成 PHP 脚本，返回 security token"""
        token = secrets.token_urlsafe(32)
        path = f'{self._data_root(service_name)}/{self.woo_script}'
        php = f'''<?php
header('Content-Type: application/json; charset=utf-8');
$token = '{token}';
if (!isset($_GET['token']) || !hash_equals($token, $_GET['token'])) {{ http_response_code(403); echo json_encode(['code'=>403,'msg'=>'forbidden']); exit; }}
require_once __DIR__ . '/wp-load.php';
if (!class_exists('WooCommerce')) {{ echo json_encode(['code'=>500,'msg'=>'WooCommerce not active']); exit; }}
global $wpdb;
$consumer_key = 'ck_' . bin2hex(random_bytes(20));
$consumer_secret = 'cs_' . bin2hex(random_bytes(20));
$wpdb->insert($wpdb->prefix . 'woocommerce_api_keys', [
  'user_id' => $wpdb->get_var("SELECT u.ID FROM {{$wpdb->users}} u INNER JOIN {{$wpdb->usermeta}} m ON u.ID=m.user_id WHERE m.meta_key='{{$wpdb->prefix}}capabilities' AND m.meta_value LIKE '%administrator%' LIMIT 1") ?: 1,
  'description' => '1Panel Auto Clone Key',
  'permissions' => 'read_write',
  'consumer_key' => wc_api_hash($consumer_key),
  'consumer_secret' => $consumer_secret,
  'truncated_key' => substr($consumer_key, -7),
]);
echo json_encode(['code'=>200,'consumer_key'=>$consumer_key,'consumer_secret'=>$consumer_secret], JSON_UNESCAPED_UNICODE);
'''
        self.file_manager.save(path, php)
        return token

    def remove_woo_script(self, service_name: str) -> None:
        self.file_manager.delete(f'{self._data_root(service_name)}/{self.woo_script}', is_dir=False)

    def fetch_woo_keys(self, domain: str, token: str, protocol: str) -> tuple:
        """通过 HTTP 调用 PHP 脚本获取 WooCommerce API Key。

        优先通过域名访问；若 Cloudflare 代理导致 525，回退 localhost 直连。
        """
        urls = [
            (f'{protocol}://{domain}/{self.woo_script}?token={token}', {}),
            (f'http://127.0.0.1/{self.woo_script}?token={token}', {'Host': domain}),
        ]
        if protocol == 'https':
            urls.insert(1, (f'http://{domain}/{self.woo_script}?token={token}', {}))
        for _ in range(self.woo_fetch_retries):
            for url, extra_headers in urls:
                try:
                    resp = httpx.get(url, headers=extra_headers, timeout=30,
                                     verify=self.wp_verify_ssl, follow_redirects=True)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get('code') == 200 and data.get('consumer_key') and data.get('consumer_secret'):
                            return data['consumer_key'], data['consumer_secret']
                except Exception:
                    pass
            time.sleep(self.woo_fetch_interval)
        raise WordPressOperationError("get woo key")

    # --- CTX / Feed 刷新 ---

    def inject_ctx_script(self, service_name: str, domain: str, protocol: str) -> str:
        """注入 CTX 刷新 PHP 脚本，返回 CTX Refresh URL"""
        token = secrets.token_urlsafe(32)
        path = f'{self._data_root(service_name)}/{self.ctx_script}'
        php = f'''<?php
/**
 * CTX Feed 自动化刷新与链接获取桥接脚本 - JSON 输出版
 */
define('WP_USE_THEMES', false);

if (file_exists('wp-load.php')) {{
    require_once('wp-load.php');
}} else {{
    header("HTTP/1.1 500 Internal Server Error");
    header("Content-Type: application/json; charset=utf-8");
    echo json_encode(['code' => 500, 'msg' => "Error: wp-load.php not found."], JSON_UNESCAPED_UNICODE);
    exit;
}}

global $wp_query;
status_header(200);
if (isset($wp_query) && is_object($wp_query)) {{
    $wp_query->is_404 = false;
}}

$secret_token = '{token}';

if (!isset($_GET['token']) || $_GET['token'] !== $secret_token) {{
    header("HTTP/1.1 403 Forbidden");
    header("Content-Type: application/json; charset=utf-8");
    echo json_encode(['code' => 403, 'msg' => "Access Denied: Invalid or missing token."], JSON_UNESCAPED_UNICODE);
    exit;
}}

// 统一返回 JSON 头
header("Content-Type: application/json; charset=utf-8");

// 用于收集输出数据
$response = [
    'code' => 200,
    'msg' => 'success',
    'cache_flush' => false,
    'triggered_hooks' => [],
    'triggered_count' => 0,
    'feed_links' => [],
    'feed_dir_status' => ''
];

if (function_exists('wp_cache_flush')) {{
    wp_cache_flush();
    $response['cache_flush'] = true;
}}

$cron_jobs = _get_cron_array();
$triggered_count = 0;

if (is_array($cron_jobs)) {{
    foreach ($cron_jobs as $timestamp => $hooks) {{
        foreach ($hooks as $hook_name => $hook_data) {{
            if (strpos($hook_name, 'woo_feed_') !== false || strpos($hook_name, 'ctx_feed_') !== false) {{
                foreach ($hook_data as $key => $data) {{
                    $args = isset($data['args']) ? $data['args'] : array();
                    do_action_ref_array($hook_name, $args);
                    $response['triggered_hooks'][] = $hook_name;
                    $triggered_count++;
                }}
            }}
        }}
    }}
}}

if ($triggered_count === 0) {{
    if (has_action('woo_feed_update_single_feed')) {{
        do_action('woo_feed_update_single_feed');
        $response['triggered_hooks'][] = 'woo_feed_update_single_feed';
        $triggered_count++;
    }}
}}
$response['triggered_count'] = $triggered_count;

// 扫描 feed 文件链接
if (function_exists('wp_upload_dir')) {{
    $upload_dir = wp_upload_dir();
    $feed_base_dir = $upload_dir['basedir'] . '/woo-feed/';
    $feed_base_url = $upload_dir['baseurl'] . '/woo-feed/';

    if (is_dir($feed_base_dir)) {{
        $files = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($feed_base_dir));
        $found_files = 0;
        foreach ($files as $file) {{
            if ($file->isFile() && in_array(strtolower($file->getExtension()), array('xml', 'csv', 'txt'))) {{
                // 过滤掉 logs 目录中的日志文件，只保留真正的 feed
                $relative_path = str_replace($feed_base_dir, '', $file->getPathname());
                $clean_relative = str_replace('\\\\', '/', $relative_path);
                if (strpos($clean_relative, '/logs/') !== false) {{
                    continue;
                }}
                // 完整公网链接存入数组
                $full_link = $feed_base_url . ltrim($clean_relative, '/');
                $response['feed_links'][] = $full_link;
                $found_files++;
            }}
        }}
        if ($found_files === 0) {{
            $response['feed_dir_status'] = "No feed files (.xml/.csv/.txt) found in woo-feed directory yet.";
        }} else {{
            $response['feed_dir_status'] = "Found $found_files valid feed files.";
        }}
    }} else {{
        $response['feed_dir_status'] = "Feed directory does not exist yet. It will be auto-created by the plugin shortly.";
    }}
}}

// 最终输出标准 JSON
echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
'''
        self.file_manager.save(path, php)
        return f'{protocol}://{domain}/{self.ctx_script}?token={token}'

    def remove_ctx_script(self, service_name: str) -> None:
        self.file_manager.delete(f'{self._data_root(service_name)}/{self.ctx_script}', is_dir=False)

    def fetch_feed_links(self, ctx_refresh_url: str) -> list:
        """通过 HTTP 调用 CTX 脚本获取所有 feed 链接列表，返回扁平的 URL 字符串列表。自动过滤 logs 目录。

        优先通过域名访问；若 Cloudflare 代理导致 525，回退 localhost 直连。
        """
        if not ctx_refresh_url:
            return []
        # 构造 localhost 回退 URL（绕过 Cloudflare）
        import urllib.parse as _up
        _parsed = _up.urlparse(ctx_refresh_url)
        _local_url = f'http://127.0.0.1{_parsed.path}?{_parsed.query}'
        _domain = _parsed.hostname or ''
        urls = [
            (ctx_refresh_url, {}),
            (_local_url, {'Host': _domain}),
        ]
        for i in range(1, 7):
            for url, extra_headers in urls:
                try:
                    resp = httpx.get(url, headers=extra_headers, timeout=60,
                                     verify=self.wp_verify_ssl, follow_redirects=True)
                    if resp.status_code == 200:
                        data = resp.json()
                        links = data.get('feed_links') or []
                        if isinstance(links, list) and links:
                            links = [str(l) for l in links]
                            # 过滤 logs 目录（PHP 端已过滤，此处为二次保障）
                            links = [l for l in links if '/logs/' not in l]
                            _log.info("CTX 刷新成功，获取到 %s 条 Feed 链接", len(links))
                            return links
                        _log.warning("CTX 刷新未返回 feed_links，第 %s/6 次", i)
                except Exception as exc:
                    _log.warning("CTX 刷新链接请求失败，第 %s/6 次：%s", i, exc)
            time.sleep(5)
        _log.warning("CTX Feed_Link 获取失败")
        return []

    def fetch_last_feed_link(self, ctx_refresh_url: str) -> Optional[str]:
        """获取第一个 feed 链接（logs 已在 fetch_feed_links 中过滤）"""
        feeds = self.fetch_feed_links(ctx_refresh_url)
        return feeds[0] if feeds else None

    def fetch_feed_link(self, domain: str, token: str, protocol: str) -> list:
        """已弃用，请使用 fetch_feed_links"""
        import warnings
        warnings.warn("fetch_feed_link is deprecated, use fetch_feed_links instead", DeprecationWarning)
        return self.fetch_feed_links(domain, token, protocol)

    def health_check(self, domain: str, protocol: str) -> bool:
        """对创建完成的 WordPress 站点做基础健康检查（带重试）"""
        import httpx as _h

        urls = [
            f'{protocol}://{domain}/wp-login.php',
            f'{protocol}://{domain}/',
        ]
        import time as _time

        for attempt in range(1, 11):
            for url in urls:
                try:
                    resp = _h.get(url, timeout=30, verify=self.wp_verify_ssl, follow_redirects=True)
                    if resp.status_code not in (200, 301, 302):
                        continue

                    final_url = str(resp.url or '').lower()
                    text = (resp.text or '').lower()

                    if any(x in final_url for x in ['/wp-login.php', '/wp-admin', domain.lower()]):
                        if 'wordpress' in text or 'wp-login' in text or 'wp-content' in text or 'user_login' in text:
                            return True
                except Exception:
                    pass
            if attempt < 10:
                _time.sleep(10)

        return False