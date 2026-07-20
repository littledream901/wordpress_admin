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
from .php_client import (
    PHPClient,
    PHPClientError,
    PHPClientNetworkError,
    PHPClientResponseError,
    PHPClientServerError,
)
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
        # PHP HTTP 客户端（统一重试/错误处理/脱敏）
        self.php_client = PHPClient(verify_ssl=self.wp_verify_ssl, default_timeout=60.0)

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
        php = rf'''<?php
header('Content-Type: application/json; charset=utf-8');

// 捕获 PHP Fatal error 输出诊断 JSON（shutdown 时 error_get_last 可拿到致命错误）
register_shutdown_function(function() {{
    $err = error_get_last();
    if ($err && in_array($err['type'], [E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR, E_USER_ERROR])) {{
        http_response_code(500);
        $msg = $err['message'];
        // 脱敏路径
        $msg = str_replace(dirname(__DIR__), '', $msg);
        echo json_encode(['code' => 500, 'error' => $msg, 'file' => basename($err['file']), 'line' => $err['line']], JSON_UNESCAPED_UNICODE);
        exit;
    }}
}});

$token = '{token}';
if (!isset($_GET['token']) || !hash_equals($token, $_GET['token'])) {{ http_response_code(403); echo json_encode(['code'=>403,'msg'=>'forbidden']); exit; }}
define('WP_USE_THEMES', false);

try {{
    require_once __DIR__ . '/wp-load.php';
}} catch (\Throwable $e) {{
    http_response_code(500);
    echo json_encode(['code' => 500, 'error' => $e->getMessage(), 'file' => basename($e->getFile()), 'line' => $e->getLine()], JSON_UNESCAPED_UNICODE);
    exit;
}}

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
    try {{
      $newUn = fc_replace_recursive($un, $oldList, $newList);
      return serialize($newUn);
    }} catch (\Error $e) {{
      // 不完整类（如 ActionScheduler_IntervalSchedule）无法递归遍历，回退字符串替换
    }}
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
        # ── 写入后验证：确认文件已落盘 ──
        if not self.file_manager.exists(path):
            raise WordPressOperationError(
                "domain replace script inject",
                detail=f"domain-replace.php 写入后磁盘验证失败：{path}，请检查磁盘权限与路径",
            )
        _log.info("domain-replace.php 已写入 %s", path)
        return token

    def remove_domain_replace_script(self, service_name: str) -> None:
        self.file_manager.delete(f'{self._data_root(service_name)}/domain-replace.php', is_dir=False)

    def fetch_domain_replace(self, domain: str, token: str) -> dict:
        """通过 HTTP 调用域名替换 PHP 脚本（统一重试/错误处理）。

        HTTP 404 是关键信号：脚本写入了磁盘但 Web 根目录未命中。
        此时不做无意义重试，直接抛出可诊断的错误信息。
        """
        path = f"domain-replace.php?token={token}"
        try:
            return self.php_client.fetch_with_fallback(
                domain=domain, path=path, step="domain_replace",
                success_check=lambda d: d.get("code") == 200,
                max_retries=1,
            )
        except PHPClientResponseError as e:
            msg = str(e)
            if "HTTP 404" in msg:
                raise WordPressOperationError(
                    "domain replace", detail=(
                        f"HTTP 404：domain-replace.php 不可访问 ({domain})。"
                        "排查步骤：1) 文件是否写入到当前站点的 Nginx root 目录下？ "
                        "2) 当前域名是否指向正确站点？ "
                        "3) Nginx 是否已 reload？"
                    )
                )
            raise WordPressOperationError("domain replace", detail=msg)
        except PHPClientError as e:
            raise WordPressOperationError("domain replace", detail=str(e))
        except Exception as e:
            raise WordPressOperationError("domain replace", detail=str(e))

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

// ── 诊断输出（失败时附带上下文）──
function woo_diagnose_and_exit($reason) {{
    $diag = ['code' => 500, 'msg' => $reason];
    // 尽力收集上下文（任一函数不可用时跳过）
    try {{ $diag['home_url'] = function_exists('home_url') ? home_url() : 'home_url() not available'; }} catch (\Throwable $e) {{ $diag['home_url'] = 'error: '.$e->getMessage(); }}
    try {{ $diag['site_url'] = function_exists('site_url') ? site_url() : 'site_url() not available'; }} catch (\Throwable $e) {{ $diag['site_url'] = 'error: '.$e->getMessage(); }}
    try {{ $diag['plugins_dir'] = defined('WP_PLUGIN_DIR') ? WP_PLUGIN_DIR : (defined('WP_CONTENT_DIR') ? WP_CONTENT_DIR.'/plugins' : 'unknown'); }} catch (\Throwable $e) {{ $diag['plugins_dir'] = 'error: '.$e->getMessage(); }}
    try {{ $diag['active_plugins'] = function_exists('get_option') ? get_option('active_plugins', []) : []; }} catch (\Throwable $e) {{ $diag['active_plugins'] = []; }}
    $diag['woo_in_active_plugins'] = in_array('woocommerce/woocommerce.php', $diag['active_plugins'] ?? []);
    try {{ $diag['woo_class_exists'] = class_exists('WooCommerce'); }} catch (\Throwable $e) {{ $diag['woo_class_exists'] = false; }}
    try {{ $diag['woo_plugin_file_exists'] = is_file(($diag['plugins_dir'] ?? '').'/woocommerce/woocommerce.php'); }} catch (\Throwable $e) {{ $diag['woo_plugin_file_exists'] = false; }}
    try {{ $diag['script_dir'] = __DIR__; }} catch (\Throwable $e) {{ $diag['script_dir'] = 'unknown'; }}
    echo json_encode($diag, JSON_UNESCAPED_UNICODE);
    exit;
}}

// ── 加载 WordPress 核心 ──
$wp_load = __DIR__ . '/wp-load.php';
if (!is_file($wp_load)) {{
    woo_diagnose_and_exit("wp-load.php not found at script directory: " . __DIR__);
}}
try {{
    require_once $wp_load;
}} catch (\Throwable $e) {{
    woo_diagnose_and_exit("wp-load.php load failed: " . $e->getMessage());
}}

// ── 验证 WooCommerce 已加载 ──
if (!class_exists('WooCommerce')) {{
    woo_diagnose_and_exit("WooCommerce class not loaded (check active_plugins / plugins_dir / site context)");
}}

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
        if not self.file_manager.exists(path):
            raise WordPressOperationError(
                "woo script inject",
                detail=f"{self.woo_script} 写入后磁盘验证失败：{path}",
            )
        return token

    def remove_woo_script(self, service_name: str) -> None:
        self.file_manager.delete(f'{self._data_root(service_name)}/{self.woo_script}', is_dir=False)

    def fetch_woo_keys(self, domain: str, token: str, protocol: str) -> tuple:
        """通过 HTTP 调用 PHP 脚本获取 WooCommerce API Key（统一重试/错误处理）"""
        path = f"{self.woo_script}?token={token}"
        try:
            data = self.php_client.fetch_with_fallback(
                domain=domain, path=path, step="woo_keys",
                success_check=lambda d: (
                    d.get("code") == 200
                    and d.get("consumer_key")
                    and d.get("consumer_secret")
                ),
                max_retries=3,
            )
            return data["consumer_key"], data["consumer_secret"]
        except PHPClientError as e:
            raise WordPressOperationError("get woo key", detail=str(e))

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
        if not self.file_manager.exists(path):
            raise WordPressOperationError(
                "ctx script inject",
                detail=f"{self.ctx_script} 写入后磁盘验证失败：{path}",
            )
        return f'{protocol}://{domain}/{self.ctx_script}?token={token}'

    def remove_ctx_script(self, service_name: str) -> None:
        self.file_manager.delete(f'{self._data_root(service_name)}/{self.ctx_script}', is_dir=False)

    def fetch_feed_links(self, ctx_refresh_url: str) -> list:
        """通过 HTTP 调用 CTX 脚本获取所有 feed 链接列表。

        ctx-refresh.php 的 500 通常是 WordPress 侧代码逻辑错误（非瞬态），
        因此最多重试 1 次，且仅走 HTTPS（HTTP→HTTPS 重定向无意义）。
        返回扁平的 URL 字符串列表，自动过滤 logs 目录。
        """
        if not ctx_refresh_url:
            return []

        from urllib.parse import urlparse

        parsed = urlparse(ctx_refresh_url)
        domain = parsed.hostname
        path = parsed.path.lstrip("/")
        if parsed.query:
            path = f"{path}?{parsed.query}"

        url = f"https://{domain}/{path}"
        try:
            data = self.php_client.fetch_json(
                url=url,
                success_check=lambda d: isinstance(d.get("feed_links"), list) and len(d["feed_links"]) > 0,
                max_retries=1,
                step="ctx_feed",
            )
            links = [str(l) for l in (data.get("feed_links") or [])]
            links = [l for l in links if "/logs/" not in l]
            _log.info("CTX 刷新成功，获取到 %s 条 Feed 链接", len(links))
            return links
        except PHPClientResponseError as e:
            _log.warning("CTX Feed_Link 获取失败（业务错误，不重试）: %s", e)
            return []
        except PHPClientError as e:
            _log.warning("CTX Feed_Link 获取失败: %s", e)
            return []

    def fetch_last_feed_link(self, ctx_refresh_url: str) -> Optional[str]:
        """获取第一个 feed 链接（logs 已在 fetch_feed_links 中过滤）"""
        feeds = self.fetch_feed_links(ctx_refresh_url)
        return feeds[0] if feeds else None


    def health_check(self, domain: str, protocol: str) -> bool:
        """对创建完成的 WordPress 站点做基础健康检查（带重试）。

        使用 php_client.raw_request 统一处理网络重试和日志脱敏，
        保留 WP 特有的 body/URL 模式匹配逻辑。
        """
        paths = ['wp-login.php', '']
        client = self.php_client

        for attempt in range(1, 11):
            for path in paths:
                for proto in ("https", "http"):
                    try:
                        verify = self.wp_verify_ssl if proto == "https" else False
                        # 临时覆盖 SSL 验证
                        client.verify_ssl = verify
                        resp = client.raw_request("GET", f"{proto}://{domain}/{path.lstrip('/')}", max_retries=1)

                        if resp.status_code not in (200, 301, 302):
                            continue

                        final_url = str(resp.url or '').lower()
                        text = (resp.text or '').lower()

                        if any(x in final_url for x in ['/wp-login.php', '/wp-admin', domain.lower()]):
                            if 'wordpress' in text or 'wp-login' in text or 'wp-content' in text or 'user_login' in text:
                                return True
                    except PHPClientError:
                        pass
            if attempt < 10:
                time.sleep(10)

        return False