"""HubStudio Connector 生命周期管理"""

import logging
import os
import socket
import subprocess
import time
from typing import Optional

from .client import HubStudioClient


class HubStudioRuntime:
    """本地 Connector 运行时管理"""

    def __init__(self, config: dict, logger: logging.Logger):
        self.connector_dir = config.get("connector_dir", r"D:\Program Files\Hubstudio")
        self.exe_name = config.get("exe_name", "hubstudio_connector.exe")
        self.http_port = int(config.get("http_port") or "6873")
        self.base_url = config.get("base_url", f"http://localhost:{self.http_port}")
        self.app_id = config.get("app_id", "")
        self.app_secret = config.get("app_secret", "")
        self.group_code = config.get("group_code", "")
        self.kernel_version = int(config.get("real_kernel_version") or "137")
        self.logger = logger
        self.client: Optional[HubStudioClient] = None

    def is_port_open(self, host="127.0.0.1", port=None, timeout=0.5) -> bool:
        port = port or self.http_port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            sock.close()
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            try:
                sock.close()
            except Exception:
                pass
            return False

    def kill_old_connector(self):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/f", "/im", self.exe_name, "/t"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            else:
                subprocess.run(["pkill", "-f", self.exe_name],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            time.sleep(1)
            self.logger.info("旧 Connector 进程已清理")
        except Exception as e:
            self.logger.warning(f"清理旧进程异常: {e}")

    def start_connector(self):
        exe_full_path = os.path.join(self.connector_dir, self.exe_name)
        if not os.path.exists(exe_full_path):
            raise FileNotFoundError(f"Connector 不存在: {exe_full_path}")

        if self.is_port_open():
            self.logger.info(f"Connector 端口 {self.http_port} 已在运行，复用")
            self.client = HubStudioClient(base_url=self.base_url)
            return

        self.kill_old_connector()
        launch_args = [
            exe_full_path,
            "--server_mode=http",
            f"--http_port={self.http_port}",
            f"--app_id={self.app_id}",
            f"--app_secret={self.app_secret}",
            f"--group_code={self.group_code}",
        ]
        kwargs = {"cwd": self.connector_dir}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(launch_args, **kwargs)
        self.logger.info(f"Connector 已启动: {exe_full_path}")

        for i in range(20):
            if self.is_port_open():
                self.logger.info(f"端口 {self.http_port} 就绪")
                time.sleep(1)
                self.client = HubStudioClient(base_url=self.base_url)
                return
            time.sleep(1)
            self.logger.info(f"等待端口 {self.http_port}... ({i+1}/20)")
        raise TimeoutError(f"等待端口 {self.http_port} 超时")

    def ensure_client(self) -> HubStudioClient:
        if not self.client:
            self.start_connector()
        return self.client
