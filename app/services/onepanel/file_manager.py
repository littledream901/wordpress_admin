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
        """解压文件"""
        ok, msg = self.api.post('/files/decompress', {'path': src, 'dst': dst, 'type': typ, 'secret': '', 'taskID': str(uuid.uuid4())})
        if not ok:
            raise OnePanelError("decompress", detail=src)
        time.sleep(wait)

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
