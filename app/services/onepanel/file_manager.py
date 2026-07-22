import os
import time
import uuid
from typing import Any, Dict, List

from app.core.exceptions import OnePanelError
from .client import OnePanelAPI
from .utils import _log


class OnePanelFileManager:
    def __init__(self, api: OnePanelAPI):
        self.api = api

    def read(self, path: str) -> str:
        ok, data = self.api.post('/files/content', {'path': path})
        if not ok or not isinstance(data, dict):
            raise OnePanelError("read file", detail=path)
        return data.get('content', '')

    def save(self, path: str, content: str) -> None:
        ok, msg = self.api.post('/files/save', {'path': path, 'content': content})
        if ok:
            return
        msg_text = str(msg)
        if '不存在' in msg_text or 'not exist' in msg_text.lower() or 'no such' in msg_text.lower():
            # 确保父目录存在（1Panel /files 创建文件时不会自动创建中间目录）
            parent = os.path.dirname(path.rstrip('/'))
            if parent and parent != '/' and not self.exists(parent):
                self.api.post('/files', {'path': parent, 'isDir': True, 'mode': 493})
            ok_create, create_msg = self.api.post('/files', {'path': path, 'content': '', 'isDir': False, 'mode': 493})
            if ok_create:
                ok_save_again, save_again_msg = self.api.post('/files/save', {'path': path, 'content': content})
                if ok_save_again:
                    return
                raise OnePanelError("save file", detail=path)
            raise OnePanelError("create file", detail=path)
        raise OnePanelError("save file", detail=path)

    def search(self, path: str) -> List[Dict[str, Any]]:
        """列出目录内容"""
        ok, data = self.api.post('/files/search', {'path': path, 'expand': True, 'showHidden': True, 'page': 1, 'pageSize': 999, 'search': '', 'containSub': False})
        return (data.get('items') or []) if ok and isinstance(data, dict) else []

    def exists(self, path: str) -> bool:
        """检查路径是否存在"""
        parent = os.path.dirname(path.rstrip('/')) or '/'
        name = os.path.basename(path.rstrip('/'))
        return any(x.get('name') == name for x in self.search(parent))

    def delete(self, path: str, is_dir: bool = False, force: bool = True) -> None:
        """删除文件/目录 — 失败时记录日志但不抛异常"""
        ok, msg = self.api.post('/files/del', {'path': path, 'isDir': is_dir, 'forceDelete': force})
        if ok:
            return
        msg_text = str(msg).lower()
        if 'no such file' in msg_text or 'not exist' in msg_text or '不存在' in msg_text:
            _log.debug("删除目标不存在，忽略：%s", path)
            return
        _log.warning("删除文件失败但不中断：%s | %s", path, msg)

    def decompress(self, src: str, dst: str, typ: str = 'tar.gz', wait: int = 8) -> None:
        """解压文件（异步任务，轮询等待完成）"""
        task_id = str(uuid.uuid4())
        ok, msg = self.api.post('/files/decompress', {'path': src, 'dst': dst, 'type': typ, 'secret': '', 'taskID': task_id})
        if not ok:
            raise OnePanelError("decompress", detail=src)
        self._wait_task_done(task_id, f'解压 {os.path.basename(src)}', timeout=300, interval=3)

    def _wait_task_done(self, task_id: str, desc: str, timeout: int = 300, interval: int = 3) -> None:
        """轮询 1Panel 异步任务状态（解压 / 移动等）"""
        success_words = {'success', 'successful', 'done', 'completed', 'finish', 'finished'}
        failed_words = {'failed', 'fail', 'error', 'err', 'timeout', 'canceled', 'cancelled'}
        start = time.time()
        while time.time() - start < timeout:
            ok, data = self.api.post('/logs/tasks/search', {'page': 1, 'pageSize': 10, 'taskID': task_id})
            status = ''
            if ok and isinstance(data, dict):
                items = data.get('items') or []
                if items:
                    item = items[0]
                    status = str(item.get('status') or item.get('Status') or item.get('state') or '')
            low = status.lower()
            if any(w in low for w in success_words):
                _log.info("%s 完成：taskID=%s", desc, task_id)
                return
            if any(w in low for w in failed_words):
                raise OnePanelError(desc, detail=f"taskID={task_id} status={status}")
            time.sleep(interval)
        raise TimeoutError(f'{desc} 等待超时：taskID={task_id}')

    def move(self, old_paths: List[str], new_path: str, typ: str = 'cut', wait: int = 3) -> None:
        """移动文件"""
        ok, msg = self.api.post('/files/move', {'oldPaths': old_paths, 'newPath': new_path, 'type': typ, 'cover': True})
        if not ok:
            raise OnePanelError("move files", detail=str(old_paths))
        time.sleep(wait)

    def chmod(self, path: str, mode: int = 493, user: str = 'root', group: str = 'root', sub: bool = True) -> None:
        """修改权限 — 失败时记录警告但不中断"""
        ok, msg = self.api.post('/files/batch/role', {'paths': [path], 'mode': mode, 'user': user, 'group': group, 'sub': sub})
        if not ok:
            _log.warning("修改权限失败但不中断：%s | %s", path, msg)
