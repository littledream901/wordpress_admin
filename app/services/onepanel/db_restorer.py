import json
import time
import uuid
from typing import Dict

from app.utils.provider_resolver import ProviderResolver
from app.core.exceptions import OnePanelError, ProviderConfigError
from .client import OnePanelAPI
from .utils import _log, _provider_value


class OnePanelDatabaseRestorer:
    """1Panel 数据库恢复 —— 通过备份/恢复 API 上传 SQL 备份并恢复"""

    # WordPress 核心表名列表，用于恢复后校验
    WP_CORE_TABLES = ['wp_options', 'wp_posts', 'wp_postmeta', 'wp_users', 'wp_usermeta']

    def __init__(self, api: OnePanelAPI):
        self.api = api
        cfgs = ProviderResolver.sync_get_config_map('onepanel')
        self.db_backup_path = str(_provider_value(cfgs, 'OP_DB_BACKUP_PATH', 'db_backup_path', '') or '')
        bid = int(_provider_value(cfgs, 'OP_BACKUP_ACCOUNT_ID', 'backup_account_id', '0'))
        self.backup_account_id = bid if bid > 0 else 1  # 默认使用本地服务器备份账户
        self.panel_base = str(_provider_value(cfgs, 'OP_PANEL_BASE', 'panel_base', '/opt/1panel'))

    def _wait_task_done(self, task_id: str, desc: str, timeout: int = 600, interval: int = 5) -> None:
        """轮询 1Panel 异步任务状态，失败时读取详细日志"""
        success_words = {'success', 'successful', 'done', 'completed', 'finish', 'finished'}
        failed_words = {'failed', 'fail', 'error', 'err', 'timeout', 'canceled', 'cancelled'}
        start = time.time()
        last_status = ''
        while time.time() - start < timeout:
            status = ''
            msg = ''
            ok, data = self.api.post('/logs/tasks/search', {'page': 1, 'pageSize': 10, 'taskID': task_id})
            if ok and isinstance(data, dict):
                items = data.get('items') or []
                if items:
                    item = items[0]
                    status = str(item.get('status') or item.get('Status') or item.get('state') or '')
                    msg = str(item.get('message') or item.get('msg') or '')
            # 补充读取任务日志最新内容，获取更详细的错误信息
            ok_read, read_data = self.api.post('/logs/tasks/read', {'page': 1, 'pageSize': 100, 'taskID': task_id, 'latest': True})
            if ok_read and read_data:
                read_text = json.dumps(read_data, ensure_ascii=False, default=str) if not isinstance(read_data, str) else read_data
                if not msg:
                    msg = read_text[-500:]
                if not status:
                    low_text = read_text.lower()
                    if any(w in low_text for w in success_words):
                        status = 'success'
                    elif any(w in low_text for w in failed_words):
                        status = 'failed'
            low = status.lower()
            if status and status != last_status:
                _log.info("%s 状态变更：taskID=%s status=%s msg=%s", desc, task_id, status or "running", (msg or "")[:200])
                last_status = status
            if any(w in low for w in success_words):
                return
            if any(w in low for w in failed_words):
                detail = msg or f'status={status}'
                raise OnePanelError("db restore", detail=f"taskID={task_id}")
            time.sleep(interval)
        raise TimeoutError(f'{desc} 等待超时：taskID={task_id}')

    def restore(self, db_name: str) -> None:
        """从数据库备份文件恢复（使用 1Panel 标准备份/恢复 API）"""
        if not self.db_backup_path:
            raise ProviderConfigError("onepanel", "db_backup_path", "未配置数据库备份路径")
        bp = self.db_backup_path.lower()
        if bp.endswith('.tar.gz') or bp.endswith('.tar') or bp.endswith('.zip'):
            raise ProviderConfigError("onepanel", "db_backup_path", "配置值不是有效的SQL备份文件")
        # 下载数据库备份文件（支持大文件，不通过 /files/content 读取）
        raw = self.api.download_file(self.db_backup_path)
        # 检测是否为 gzip 压缩（根据文件扩展名或内容魔数）
        is_gz = self.db_backup_path.lower().endswith(('.sql.gz', '.gz'))
        if not is_gz and len(raw) >= 2:
            is_gz = raw[:2] == b'\x1f\x8b'  # gzip 魔数
        ext = '.sql.gz' if is_gz else '.sql'
        # 上传到目标数据库目录
        upload_dir = f'{self.panel_base}/uploads/database/mysql/mysql/{db_name}/'
        filename = f'{db_name}_restore_{int(time.time())}{ext}'
        upload_path = self.api.upload_chunk(upload_dir, filename, raw)
        # 触发恢复
        task_id = str(uuid.uuid4())
        payload = {
            'downloadAccountID': self.backup_account_id,
            'type': 'mysql',
            'name': 'mysql',
            'detailName': db_name,
            'file': upload_path,
            'secret': '',
            'taskID': task_id,
            'timeout': 1800,
        }
        ok, msg = self.api.post('/backups/recover/byupload', payload)
        if not ok:
            raise OnePanelError("db restore", detail=str(msg))
        self._wait_task_done(task_id, f'数据库恢复 {db_name}', timeout=600, interval=5)
