"""
1Panel API 客户端 —— 基于 httpx。

特性：
  - httpx.Client 连接池（优于 requests.Session）
  - 自动重试 + 指数退避
  - 1Panel-Token 签名认证
  - 大文件下载/分块上传

依赖：
  pip install httpx
"""

import hashlib
import time
from typing import Any, Dict, Tuple
from urllib.parse import quote

import httpx

from app.utils.provider_resolver import ProviderResolver
from app.core.exceptions import OnePanelError, ProviderConfigError
from .utils import _log, _provider_value, safe_log_data


def _parse_concatenated_json(text: str) -> dict | None:
    """解析 1Panel 可能返回的多个拼接 JSON 对象。

    1Panel 批量操作（如 /files/batch/role）可能为多个路径各返回一个 JSON，
    导致响应体形如 `{...}{...}`，无法被 json.loads 整体解析。

    返回第一个 code==200 的结果；若没有成功的则返回第一个对象；解析失败返回 None。
    """
    import json as _json
    text = text.strip()
    if not text:
        return None
    decoder = _json.JSONDecoder()
    objects: list[dict] = []
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx] in ' \t\n\r':
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
            if isinstance(obj, dict):
                objects.append(obj)
            idx = end
        except _json.JSONDecodeError:
            break
    if not objects:
        return None
    # 优先返回成功的，否则返回第一个
    for obj in objects:
        if obj.get('code') == 200:
            return obj
    return objects[0]


class OnePanelAPI:
    def __init__(self):
        cfgs = ProviderResolver.sync_get_config_map('onepanel')
        url = str(_provider_value(cfgs, 'OP_URL', 'url', '')).strip()
        self._configured = bool(url)
        if not self._configured:
            _log.warning("1Panel 未配置 (url/OP_URL 为空)，1Panel 相关功能将不可用")
        elif not url.startswith('http'):
            _log.warning("1Panel url 缺少协议头：%s，请补全 http:// 或 https://", url)
        self.base = url.rstrip('/') + '/api/v2'
        self.api_key = str(_provider_value(cfgs, 'OP_API_KEY', 'api_key', '') or '')
        self.max_retries = int(_provider_value(cfgs, 'OP_MAX_RETRIES', 'max_retries', '5'))
        self.retry_interval = int(_provider_value(cfgs, 'OP_RETRY_INTERVAL', 'retry_interval', '5'))
        self.timeout = int(_provider_value(cfgs, 'OP_TIMEOUT', 'timeout', '45'))
        # SSL 验证：从 onepanel Provider 读取
        verify_ssl = ProviderResolver.sync_get_config('onepanel', 'op_verify_ssl', 'true')
        self.verify_ssl = verify_ssl.lower() != 'false'
        self.session = httpx.Client(verify=self.verify_ssl, http2=True)

    def headers(self, json_content: bool = True) -> Dict[str, str]:
        ts = str(int(time.time()))
        token = hashlib.md5(f'1panel{self.api_key}{ts}'.encode('utf-8')).hexdigest()
        base: Dict[str, str] = {'1Panel-Token': token, '1Panel-Timestamp': ts, 'Accept': 'application/json'}
        if json_content:
            base['Content-Type'] = 'application/json'
        return base

    def _request(self, method: str, endpoint: str, payload: Dict[str, Any] = None) -> Tuple[bool, Any]:
        if not self._configured or not self.base or self.base == '/api/v2':
            raise ProviderConfigError("onepanel", "url", "面板地址未配置，无法发起请求")
        url = self.base + endpoint
        last_err: Any = None
        _log.debug("1Panel %s %s payload=%s", method, endpoint, safe_log_data(payload or {}, 900))
        for attempt in range(1, self.max_retries + 1):
            try:
                headers = self.headers()
                resp = self.session.request(
                    method=method, url=url, headers=headers,
                    json=payload if method != 'GET' else None,
                    timeout=httpx.Timeout(self.timeout),
                )
                text = resp.text.strip()
                if resp.status_code in (502, 503, 504) or not text:
                    last_err = f'HTTP {resp.status_code}: empty/5xx'
                    _log.warning("1Panel %s %s 第 %s/%s 次异常响应：%s",
                                 method, endpoint, attempt, self.max_retries, last_err)
                    time.sleep(self.retry_interval)
                    continue
                try:
                    data = resp.json()
                except Exception as json_err:
                    # 1Panel 批量操作可能返回多个拼接的 JSON 对象
                    _log.debug("1Panel %s %s resp.json() 失败: %s，尝试拼接 JSON 解析",
                               method, endpoint, json_err)
                    data = _parse_concatenated_json(text)
                    if data is None:
                        last_err = f'HTTP {resp.status_code}: invalid JSON'
                        _log.warning("1Panel %s %s 第 %s/%s 次非 JSON 响应(json_err=%s)：%s",
                                     method, endpoint, attempt, self.max_retries, json_err, text[:200])
                        time.sleep(self.retry_interval)
                        continue

                if data.get('code') == 200:
                    _log.debug("1Panel %s %s success", method, endpoint)
                    return True, data.get('data')
                # 特定端点的「不存在」属于预期分支
                msg_text = str(data.get('message') or '').lower()
                expected_branch = (
                    (endpoint == '/files/save' and ('目标路径不存在' in msg_text or 'not exist' in msg_text or 'no such' in msg_text))
                    or (endpoint == '/files/del' and ('no such file' in msg_text or 'not exist' in msg_text or '不存在' in msg_text))
                )
                if expected_branch:
                    _log.debug("1Panel %s %s expected branch response=%s", method, endpoint, safe_log_data(data, 800))
                else:
                    _log.error("1Panel %s %s failed response=%s", method, endpoint, safe_log_data(data, 1200))
                return False, f"{data.get('code')}: {data.get('message')}"
            except (httpx.HTTPError, OSError) as exc:
                last_err = str(exc)
                _log.warning("1Panel %s %s 第 %s/%s 次请求异常：%s",
                             method, endpoint, attempt, self.max_retries, exc)
                time.sleep(self.retry_interval)
        return False, last_err

    def post(self, endpoint: str, payload: Dict[str, Any]) -> Tuple[bool, Any]:
        return self._request('POST', endpoint, payload)

    def get(self, endpoint: str) -> Tuple[bool, Any]:
        return self._request('GET', endpoint)

    def download_file(self, path: str) -> bytes:
        """下载 1Panel 服务器上的文件（支持大文件）"""
        cfgs = ProviderResolver.sync_get_config_map('onepanel')
        panel_base = _provider_value(cfgs, 'OP_PANEL_BASE', 'panel_base', '/opt/1panel')
        full = path if path.startswith(f'{panel_base}/backup') else f'{panel_base}/backup/{path.lstrip("/")}'
        url = self.base + '/files/download?path=' + quote(full, safe='/')
        for _ in range(self.max_retries):
            resp = self.session.get(
                url, headers=self.headers(json_content=False),
                timeout=httpx.Timeout(180),
            )
            if resp.status_code == 200 and resp.content:
                return resp.content
            time.sleep(self.retry_interval)
        raise OnePanelError("download file", detail=full)

    def upload_chunk(self, remote_dir: str, filename: str, data: bytes) -> str:
        """分块上传文件到 1Panel 服务器"""
        url = self.base + '/files/chunkupload'
        form = {'filename': filename, 'path': remote_dir, 'chunkIndex': '0', 'chunkCount': '1'}
        files_payload = {'file': (filename, data, 'application/octet-stream')}
        alt_payload = {'chunk': (filename, data, 'application/octet-stream')}
        hdrs = self.headers(json_content=False)
        for file_payload in (files_payload, alt_payload):
            field_name = list(file_payload.keys())[0]
            for _ in range(self.max_retries):
                try:
                    resp = self.session.post(
                        url, data=form, files=file_payload,
                        headers=hdrs, timeout=httpx.Timeout(240),
                    )
                    if resp.status_code == 200:
                        js = resp.json()
                        if js.get('code') == 200:
                            _log.debug("upload_chunk 成功：字段名=%s 路径=%s", field_name, remote_dir)
                            return remote_dir.rstrip('/') + '/' + filename
                except Exception:
                    pass
                time.sleep(self.retry_interval)
        raise OnePanelError("upload file", detail=filename)
