"""
HubStudio 本地执行 Agent

运行方式:
    python -m app.agent.hubstudio_agent

工作流程:
    1. 加载本地 .env 配置（机器相关 + 默认值）
    2. 登录后端 → 拉取 DB Provider 配置（覆盖本地默认值）
    3. 启动本地 HubStudio Connector
    4. 轮询后端领取任务 → 执行 → 回传结果
    5. 定期发送心跳

环境变量（同目录 .env 文件，或系统环境变量）:

  [后端连接] - Agent 独有，DB 无
    HUB_AGENT_SERVER_URL   后端地址，默认 http://127.0.0.1:9999/api/v1
    HUB_AGENT_USERNAME     登录账号
    HUB_AGENT_PASSWORD     登录密码

  [Worker 控制] - Agent 独有
    HUB_AGENT_WORKER_NAME  Worker 名称（默认主机名）
    HUB_AGENT_PROVIDER_ID  供应商 ID，0=不筛选
    HUB_AGENT_POLL_INTERVAL  轮询间隔秒（默认 5）
    HUB_AGENT_HEARTBEAT_INTERVAL 心跳间隔秒（默认 30）
    HUB_AGENT_MAX_BACKOFF  网络故障最大退避秒（默认 300）
    HUB_AGENT_LOG_DIR      日志目录（默认 ./logs/hubstudio）

  [Connector] - 机器相关，本地独有
    HUB_CONNECTOR_DIR      Connector 安装目录
    HUB_EXE_NAME           可执行文件名
    HUB_HTTP_PORT          Connector 端口（默认 6873）
    HUB_BASE_URL           Connector API（默认 http://localhost:6873）

  [密钥 & 业务配置] - 本地兜底，登录后由 DB 覆盖
    HUB_APP_ID / HUB_APP_SECRET / HUB_GROUP_CODE  HubStudio 连接密钥
    HUB_KERNEL_VER          内核版本（默认 137）
    HUB_DEFAULT_PROXY_TYPE  默认代理类型
    HUB_DEFAULT_UI_LANGUAGE 浏览器语言
    HUB_ADMIN_SITE_NAME / HUB_ADMIN_SITE_ALIAS / ...  任务执行默认值
"""

import importlib.util
import json
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

# 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _PROJECT_ROOT)

# 加载 .env 文件（读取 HUB_AGENT_USERNAME / HUB_AGENT_PASSWORD 等配置）
try:
    from dotenv import load_dotenv

    if getattr(sys, "frozen", False):
        # PyInstaller 打包后：优先读 EXE 同目录（用户覆盖），否则读内置默认
        _env_path = os.path.join(os.path.dirname(sys.executable), ".env")
        if not os.path.exists(_env_path):
            _env_path = os.path.join(sys._MEIPASS, ".env")
    else:
        # 开发模式：从同目录 .env 读取，与项目根 .env 隔离
        _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(_env_path)
except ImportError:
    pass


def _import_executor():
    """直接加载 executor 模块，绕过 app/__init__.py 避免引入 FastAPI 等重型依赖。
    
    兼容 PyInstaller --onefile 打包模式（通过 sys._MEIPASS 定位数据文件）。
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后，数据文件解压到 sys._MEIPASS
        _executor_path = os.path.join(sys._MEIPASS, "app", "services", "hubstudio_executor.py")
    else:
        _executor_path = os.path.join(
            os.path.dirname(__file__), "..", "services", "hubstudio_executor.py"
        )
    _executor_path = os.path.normpath(_executor_path)
    spec = importlib.util.spec_from_file_location(
        "hubstudio_executor", _executor_path,
        submodule_search_locations=[]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载执行器模块: {_executor_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_executor_mod = _import_executor()

HubStudioLocalExecutor = _executor_mod.HubStudioLocalExecutor
HubStudioRuntime = _executor_mod.HubStudioRuntime
HubStudioClient = _executor_mod.HubStudioClient
get_agent_logger = _executor_mod.get_agent_logger

# 网络层错误（用于退避重试判断）
_NETWORK_ERRORS = (
    urllib.error.URLError,
    ConnectionError,
    ConnectionRefusedError,
    ConnectionResetError,
    TimeoutError,
    OSError,
)

# provider_id ≠ 0 时，必须从 DB 获取的敏感密钥
_SENSITIVE_PROVIDER_KEYS = ("app_id", "app_secret", "group_code")


class HubStudioAgent:
    """HubStudio 本地执行 Agent"""

    def __init__(self):
        self.logger = get_agent_logger()
        self._running = True

        # ── 服务器连接配置 ──
        self.server_url = os.getenv("HUB_AGENT_SERVER_URL", "http://127.0.0.1:9999/api/v1")
        # 清理：去末尾斜杠，修复内部双斜杠（保留 https:// 的 //）
        self.server_url = self.server_url.rstrip("/")
        if "://" in self.server_url:
            proto, rest = self.server_url.split("://", 1)
            rest = rest.replace("//", "/")
            self.server_url = f"{proto}://{rest}"
        self.username = os.getenv("HUB_AGENT_USERNAME", "admin")
        self.password = os.getenv("HUB_AGENT_PASSWORD", "123456")
        self._token: Optional[str] = None  # 登录后自动获取
        self.worker_name = os.getenv("HUB_AGENT_WORKER_NAME", socket.gethostname())
        self.provider_id = int(os.getenv("HUB_AGENT_PROVIDER_ID") or "0")
        self.poll_interval = int(os.getenv("HUB_AGENT_POLL_INTERVAL") or "5")
        self.heartbeat_interval = int(os.getenv("HUB_AGENT_HEARTBEAT_INTERVAL") or "30")  # 心跳间隔秒

        # ── HubStudio 本地配置 ──
        self.config = self._load_config()

        # ── 断连退避状态 ──
        self._consecutive_net_errors = 0
        self._consecutive_http_errors = 0
        self._heartbeat_fail_count = 0
        self._max_backoff = int(os.getenv("HUB_AGENT_MAX_BACKOFF") or "300")  # 最大退避秒

        # ── 初始化执行器 ──
        self.logger.info(f"Agent 启动: worker={self.worker_name}, server={self.server_url}, "
                          f"provider={self.provider_id or '不限'}")
        self.runtime = HubStudioRuntime(self.config, self.logger)
        self.executor = HubStudioLocalExecutor(self.runtime)
        self._apply_agent_config()

    def _load_config(self) -> dict:
        """从环境变量加载本地配置（DB 中的配置由 _fetch_agent_config 在登录后覆盖）

        - 机器相关配置（connector 路径等）：始终从 .env 读取
        - 敏感密钥（app_id / app_secret / group_code）：
            provider_id = 0 时允许 .env 兜底，
            provider_id ≠ 0 时必须从 DB 拉取，不清空本地兜底会在 _fetch_agent_config 后校验
        """
        # ── 机器相关（本地独有，DB 无） ──
        config = {
            "connector_dir": os.getenv("HUB_CONNECTOR_DIR", r"D:\Program Files\Hubstudio"),
            "exe_name": os.getenv("HUB_EXE_NAME", "hubstudio_connector.exe"),
            "http_port": os.getenv("HUB_HTTP_PORT", "6873"),
            "base_url": os.getenv("HUB_BASE_URL", "http://localhost:6873"),
            "real_kernel_version": os.getenv("HUB_KERNEL_VER", "137"),

            # ── 任务执行默认值（本地兜底，登录后由 DB 覆盖） ──
            "default_proxy_type_name": os.getenv("HUB_DEFAULT_PROXY_TYPE", "不使用代理"),
            "default_ui_language": os.getenv("HUB_DEFAULT_UI_LANGUAGE", "en"),
            "admin_site_name": os.getenv("HUB_ADMIN_SITE_NAME", ""),
            "admin_site_alias": os.getenv("HUB_ADMIN_SITE_ALIAS", ""),
            "admin_account_name": os.getenv("HUB_ADMIN_ACCOUNT_NAME", ""),
            "admin_account_password": os.getenv("HUB_ADMIN_ACCOUNT_PASSWORD", ""),
        }
        # ─� 敏感密钥：provider_id ≠ 0 时不允许 .env 兜底 ──
        if self.provider_id:
            config["app_id"] = ""
            config["app_secret"] = ""
            config["group_code"] = ""
        else:
            config["app_id"] = os.getenv("HUB_APP_ID", "")
            config["app_secret"] = os.getenv("HUB_APP_SECRET", "")
            config["group_code"] = os.getenv("HUB_GROUP_CODE", "")
        return config

    def _apply_agent_config(self):
        """将 Agent 级配置应用到执行器"""
        _CONFIG_ATTR_MAP = {
            "default_proxy_type_name": "default_proxy_type",
            "default_ui_language": "default_ui_language",
            "admin_site_name": "admin_site_name",
            "admin_site_alias": "admin_site_alias",
            "admin_account_name": "admin_account_name",
            "admin_account_password": "admin_account_password",
        }
        for config_key, attr_name in _CONFIG_ATTR_MAP.items():
            value = self.config.get(config_key)
            if value is not None:
                setattr(self.executor, attr_name, value)

    # ── 认证 ──

    def _prompt_credentials(self):
        """如果账号密码未配置，交互式输入"""
        if not self.username:
            self.username = input("请输入后端登录账号: ").strip()
        if not self.password:
            import getpass
            self.password = getpass.getpass("请输入后端登录密码: ")

    def _login(self) -> str:
        """登录后端获取 JWT token"""
        self._prompt_credentials()
        self.logger.info(f"正在登录后端 (username={self.username})...")
        data = self._api_unauth_post("/base/access_token", payload={
            "username": self.username,
            "password": self.password,
        })
        token = data.get("data", {}).get("access_token")
        if not token:
            raise RuntimeError(f"登录失败: {json.dumps(data, ensure_ascii=False)}")
        self._token = token
        self.logger.info("登录成功")
        return token

    def _api_unauth_post(self, path: str, payload: dict) -> dict:
        """不携带 token 的 POST 请求（仅用于登录）"""
        url = f"{self.server_url}{path}"
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") and data["code"] != 200:
                raise RuntimeError(f"登录失败: {data.get('msg', 'unknown error')}")
            return data

    # ── HTTP 客户端（直连后端 API） ──

    def _api_request(
        self, method: str, path: str,
        payload: Optional[dict] = None, params: Optional[dict] = None,
        max_retries: int = 3, quiet_final_error: bool = False,
        _is_retry_after_login: bool = False,
    ) -> dict:
        """统一的 HTTP 请求方法，网络错误自动重试，token 过期自动刷新。

        Args:
            method: HTTP 方法 (GET/POST)
            max_retries: 最大重试次数
            quiet_final_error: True 时不输出最终失败 error（由调用方自行处理）
        """
        if not self._token:
            self._login()

        url = f"{self.server_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        last_error = None
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(url, data=body, method=method)
                req.add_header("Content-Type", "application/json")
                req.add_header("Authorization", f"Bearer {self._token}")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("code") and data["code"] != 200:
                        raise RuntimeError(data.get("msg", "unknown error"))
                    return data
            except urllib.error.HTTPError as e:
                if e.code == 401 and not _is_retry_after_login:
                    self.logger.warning("Token 已过期，自动重新登录...")
                    try:
                        self._login()
                        return self._api_request(method, path, payload, params,
                                                 max_retries=max_retries,
                                                 quiet_final_error=quiet_final_error,
                                                 _is_retry_after_login=True)
                    except Exception:
                        pass
                error_body = e.read().decode("utf-8") if e.fp else str(e)
                self.logger.error(f"API [{method} {path}]: HTTP {e.code} {error_body}")
                raise
            except _NETWORK_ERRORS as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = 2 ** attempt
                    self.logger.warning(
                        f"API 网络错误 [{method} {path}]，{delay}s 后重试({attempt + 1}/{max_retries}): {e}"
                    )
                    time.sleep(delay)
                    continue
            except Exception as e:
                self.logger.error(f"API 调用失败 [{method} {path}]: {e}")
                raise

        # 网络重试耗尽
        if not quiet_final_error:
            self.logger.error(f"API 网络错误 [{method} {path}]，已重试 {max_retries} 次: {last_error}")
        raise last_error

    def _api_post(self, path: str, payload: Optional[dict] = None, params: Optional[dict] = None,
                  max_retries: int = 3, quiet_final_error: bool = False) -> dict:
        return self._api_request("POST", path, payload=payload, params=params,
                                 max_retries=max_retries, quiet_final_error=quiet_final_error)

    def _api_get(self, path: str, params: Optional[dict] = None, max_retries: int = 3) -> dict:
        return self._api_request("GET", path, params=params, max_retries=max_retries)

    def _warn_missing_sensitive(self, source: str = "DB"):
        """检查并警告缺少必要密钥"""
        missing = [k for k in _SENSITIVE_PROVIDER_KEYS if not self.config.get(k)]
        if missing:
            self.logger.error(
                f"Provider [{self.provider_id}] 缺少必要密钥: {', '.join(missing)} "
                f"(来源: {source})。请在后台「配置中心」→ Provider [{self.provider_id}] "
                f"的配置项中设置，任务执行可能因此失败！"
            )
            return False
        return True

    def _fetch_agent_config(self):
        """从服务端拉取 Provider 配置（DB 为准），覆盖本地默认值

        provider_id = 0 时服务端自动解析默认 hubstudio Provider，
        并返回 _resolved_provider_id 告知 Agent 实际 ID。
        """
        _was_zero = not self.provider_id

        self.logger.info(f"正在从服务端拉取 Provider 配置 (provider_id={self.provider_id or '默认'})...")
        try:
            resp = self._api_get("/site-pipeline/hub-job/agent-config",
                                 params={"provider_id": self.provider_id})
            server_config = resp.get("data", {})
        except Exception as e:
            self.logger.error(
                f"拉取 Provider 配置失败: {e}。"
                f"敏感密钥（app_id / app_secret / group_code）必须在后台配置中心中设置！"
            )
            self._warn_missing_sensitive(source=".env 兜底")
            return

        # 服务端可能返回了实际解析的 provider_id
        resolved_id = server_config.pop("_resolved_provider_id", self.provider_id)
        if resolved_id and resolved_id != self.provider_id:
            self.logger.info(f"未指定 Provider，服务端自动解析为默认 HubStudio Provider（DB 记录 ID={resolved_id}）")
            self.provider_id = resolved_id

        # 从 0 切换到 DB 模式：清空 .env 兜底的敏感密钥，强制从 DB 获取
        if _was_zero and self.provider_id:
            for k in _SENSITIVE_PROVIDER_KEYS:
                self.config[k] = ""

        if not server_config:
            if self.provider_id:
                self.logger.error(
                    f"Provider [{self.provider_id}] 在服务端无配置项！"
                    f"请在后台「配置中心」→ 选择该 Provider → 点击「配置」，添加 app_id / app_secret / group_code"
                )
                self._warn_missing_sensitive(source="DB 为空")
            else:
                self.logger.info("服务端无默认 hubstudio Provider，使用 .env 兜底")
            return

        # 服务端配置优先，覆盖本地
        merged_keys = []
        for key, value in server_config.items():
            if key.startswith("_"):
                continue
            if value and value != self.config.get(key):
                self.config[key] = value
                merged_keys.append(key)

        if merged_keys:
            self.logger.info(f"已从服务端合并 {len(merged_keys)} 个配置项: {merged_keys}")
            self._apply_agent_config()
        else:
            self.logger.info("服务端配置与本地一致，无需更新")

        # 有 provider_id 时校验敏感密钥完整性
        if self.provider_id:
            self._warn_missing_sensitive(source="DB")

    # ── 心跳 ──

    def _send_heartbeat(self, task_id: int = 0, task_status: str = ""):
        """发送心跳到后端"""
        try:
            params = {
                "worker_name": self.worker_name,
                "provider_id": self.provider_id,
                "task_id": task_id,
                "task_status": task_status,
            }
            self._api_post("/site-pipeline/hub-job/heartbeat", params=params, max_retries=1,
                           quiet_final_error=True)
            self._heartbeat_fail_count = 0
        except (*_NETWORK_ERRORS, urllib.error.HTTPError):
            self._heartbeat_fail_count += 1
            if self._heartbeat_fail_count == 1:
                self.logger.warning(f"心跳发送失败，后端可能不可达 (server={self.server_url})")
        except Exception as e:
            self.logger.warning(f"心跳发送失败 (server={self.server_url}): {e}")

    # ── 任务领取 / 回传 ──

    def claim_job(self) -> Optional[dict]:
        """从后端领取一个待执行任务"""
        params = {"worker_name": self.worker_name}
        if self.provider_id:
            params["provider_id"] = self.provider_id
        resp = self._api_post("/site-pipeline/hub-job/claim", params=params)
        if resp.get("code") == 200 and resp.get("data", {}).get("ok"):
            job = resp["data"]["job"]
            self.logger.info(f"领取任务: id={job.get('id')}, type={job.get('job_type')}, "
                           f"domain={job.get('domain')}")
            return job
        return None

    def report_job(self, job_id: int, status: str, result: dict, error: str = ""):
        """回传任务执行结果"""
        payload = {
            "status": status,
            "result_json": json.dumps(result, ensure_ascii=False),
            "error_message": error,
            "worker_name": self.worker_name,
        }
        self._api_post(f"/site-pipeline/hub-job/{job_id}/report", payload=payload)

    # ── 主循环 ──

    def run_once(self) -> bool:
        """执行一轮：领取任务 → 执行 → 回传。网络错误会上抛给主循环退避。"""
        job = None
        try:
            job = self.claim_job()
            if not job:
                return False

            job_id = job["id"]
            job_type = job.get("job_type", "")
            domain = job.get("domain", "")

            self.logger.info(f"开始执行: id={job_id}, type={job_type}, domain={domain}")

            # 执行
            result = self.executor.execute(job)
            ok = result.get("status") == "success"
            error = result.get("error", "")

            # 回传
            self.report_job(job_id, "success" if ok else "failed", result, error)
            self.logger.info(f"执行完成: id={job_id}, ok={ok}")
            return True

        except _NETWORK_ERRORS:
            raise  # 网络错误上抛，由主循环统一退避
        except urllib.error.HTTPError:
            raise  # HTTP 错误上抛，由主循环统一退避（避免每轮双重报错）
        except Exception as e:
            self.logger.error(f"执行异常: {e}", exc_info=True)
            if job:
                try:
                    self.report_job(job["id"], "failed", {}, str(e))
                except Exception:
                    pass
            return False

    def run(self):
        """主循环：持续轮询"""
        # ── 启动横幅 ──
        self.logger.info("=" * 60)
        self.logger.info(f"HubStudio Agent 已启动")
        self.logger.info(f"  Worker:      {self.worker_name}")
        self.logger.info(f"  Server:      {self.server_url}")
        if self.provider_id:
            self.logger.info(f"  Provider:    [{self.provider_id}]（精确匹配，密钥从 DB 拉取）")
        else:
            self.logger.info(f"  Provider:    默认（服务端解析默认 Provider，密钥从 DB 拉取）")
        self.logger.info(f"  Poll:        {self.poll_interval}s")
        self.logger.info(f"  Heartbeat:   {self.heartbeat_interval}s")
        self.logger.info(f"  Connector:   {self.config['connector_dir']}\\{self.config['exe_name']}")
        self.logger.info("=" * 60)

        # ── 启动前登录后端（带退避重试，不登录不启动主循环）──
        self._prompt_credentials()
        login_ok = False
        for attempt in range(1, 100):  # 最多重试约 8 分钟
            try:
                self._login()
                login_ok = True
                break
            except Exception as e:
                delay = min(2 ** (attempt - 1), 60)
                self.logger.warning(
                    f"后端登录失败 (第 {attempt} 次): {e}，{delay}s 后重试"
                )
                time.sleep(delay)
        if not login_ok:
            self.logger.error("后端登录失败，已达最大重试次数，退出")
            return

        # ── 从服务端拉取 Provider 配置（带退避重试）──
        config_ok = False
        for attempt in range(1, 20):
            try:
                self._fetch_agent_config()
                config_ok = True
                break
            except Exception as e:
                delay = min(2 ** (attempt - 1), 30)
                self.logger.warning(
                    f"拉取 Provider 配置失败 (第 {attempt} 次): {e}，{delay}s 后重试"
                )
                time.sleep(delay)
        if not config_ok:
            self.logger.warning(
                "拉取 Provider 配置失败，将以本地兜底配置运行"
            )

        # ── 配置完整性摘要 ──
        if self.provider_id:
            all_ok = True
            for k in _SENSITIVE_PROVIDER_KEYS:
                val = self.config.get(k, "")
                status = "OK" if val else "缺失！"
                if not val:
                    all_ok = False
                self.logger.info(f"  {k}: {status}")
            if not all_ok:
                self.logger.warning(
                    "部分密钥缺失，任务执行可能失败。"
                    "请在后台「配置中心」→ Provider 配置项中补充。"
                )

        # 启动前检查 Connector
        connector_dir = self.config.get("connector_dir", "")
        exe_name = self.config.get("exe_name", "")
        self.logger.info(f"检查 Connector: dir={connector_dir}, exe={exe_name}, port={self.config.get('http_port')}")
        try:
            self.runtime.start_connector()
            self.logger.info("Connector 启动检查通过")
        except Exception as e:
            self.logger.error(f"Connector 启动失败: {e}")
            self.logger.warning("Agent 将继续运行，但任务执行可能会失败")

        # 首次心跳
        self._send_heartbeat()

        # 启动心跳线程
        def heartbeat_loop():
            while self._running:
                time.sleep(self.heartbeat_interval)
                if self._running:
                    self._send_heartbeat()

        heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        heartbeat_thread.start()

        consecutive_empty = 0
        _log_interval = max(1, 60 // self.poll_interval)  # 约每分钟打印一次
        while self._running:
            try:
                had_job = self.run_once()
                self._consecutive_net_errors = 0  # 成功后重置网络错误计数
                self._consecutive_http_errors = 0  # 成功后重置 HTTP 错误计数
                if had_job:
                    consecutive_empty = 0
                    time.sleep(2)  # 任务执行后短暂等待
                else:
                    consecutive_empty += 1
                    if consecutive_empty % _log_interval == 0:
                        self.logger.info(f"无待执行任务 ({consecutive_empty * self.poll_interval}s)")
                    time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                self.logger.info("收到中断信号")
                break
            except _NETWORK_ERRORS:
                # 后端不可达 → 指数退避
                self._consecutive_net_errors += 1
                delay = min(
                    self.poll_interval * (2 ** min(self._consecutive_net_errors - 1, 6)),
                    self._max_backoff,
                )
                if self._consecutive_net_errors == 1:
                    self.logger.warning(f"后端不可达 ({self.server_url})，将自动重试")
                self.logger.info(
                    f"等待 {delay}s 后重试 (第 {self._consecutive_net_errors} 次)"
                    if self._consecutive_net_errors > 1
                    else f"等待 {delay}s 后重试"
                )
                time.sleep(delay)
            except urllib.error.HTTPError as e:
                # HTTP 错误（401/403/5xx 等）→ 长间隔退避
                self._consecutive_http_errors += 1
                delay = min(30 * self._consecutive_http_errors, self._max_backoff)
                if self._consecutive_http_errors == 1:
                    self.logger.warning(
                        f"后端返回 HTTP {e.code}，请检查配置 (server={self.server_url})"
                    )
                self.logger.info(f"等待 {delay}s 后重试 (第 {self._consecutive_http_errors} 次)")
                time.sleep(delay)
            except Exception as e:
                self.logger.error(f"Agent 循环异常: {e}", exc_info=True)
                time.sleep(self.poll_interval)

        self.shutdown()

    def shutdown(self):
        """优雅关闭"""
        self._running = False
        self.logger.info("Agent 正在关闭...")
        try:
            self.runtime.ensure_client().stop_all_browsers(clearOpening=True)
            self.logger.info("浏览器已全部关闭")
        except Exception:
            pass
        self.logger.info("Agent 已停止")

    def _handle_signal(self, signum, frame):
        """POSIX 信号处理"""
        self._running = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False


def main():
    agent = HubStudioAgent()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, agent._handle_signal)
        except (ValueError, OSError, AttributeError):
            pass  # Windows 不支持部分信号
    agent.run()


if __name__ == "__main__":
    main()
