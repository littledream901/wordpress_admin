import json
import os
import typing
import warnings

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # ── 运行环境 ──
    DEBUG: bool = False
    """调试模式：True 时开启 /docs /redoc /openapi.json 文档和热重载；开发时请在 .env 中显式设置 DEBUG=true"""

    VERSION: str = "0.1.0"
    APP_TITLE: str = "Wordpress 管理"
    PROJECT_NAME: str = "Wordpress 管理"
    APP_DESCRIPTION: str = "Wordpress 站点管理平台"

    # ── CORS ──
    CORS_ORIGINS: typing.Union[typing.List[str], str] = ["*"]
    """允许的跨域来源，生产环境必须指定具体域名，如 ["https://your-domain.com"]"""
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: typing.List[str] = ["*"]
    CORS_ALLOW_HEADERS: typing.List[str] = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """兼容各种 CORS_ORIGINS 格式：JSON 数组、反引号、多余空格等。"""
        if v is None:
            return ["*"]
        if isinstance(v, list):
            return v
        # 清理反引号、多余空格
        cleaned = str(v).replace("`", "").strip()
        try:
            origins = json.loads(cleaned)
            if isinstance(origins, list):
                return origins
        except (json.JSONDecodeError, ValueError):
            pass
        # 回退：按逗号分割
        parts = [p.strip().strip("\"'") for p in cleaned.strip("[]").split(",") if p.strip()]
        return parts if parts else ["*"]

    PROJECT_ROOT: str = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    BASE_DIR: str = os.path.abspath(os.path.join(PROJECT_ROOT, os.pardir))
    LOGS_ROOT: str = os.path.join(BASE_DIR, "app/logs")

    # ── 安全 ──
    SECRET_KEY: str = ""
    """JWT 签名密钥，生产环境务必更换（openssl rand -hex 32）"""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 day
    JWT_REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30  # 30 day
    DEFAULT_PASSWORD: str = ""
    """新建用户/重置密码的默认密码，生产环境务必更换"""
    RESET_ADMIN_PASSWORD: bool = False
    """首次部署 / 强制重置时设为 true，init_superuser() 会用 DEFAULT_PASSWORD 覆盖 admin 密码"""

    # ── 限流 ──
    RATE_LIMIT_MAX_REQUESTS: int = 100  # 每分钟最大请求数
    RATE_LIMIT_WINDOW_SECONDS: int = 60  # 限流窗口（秒）

    # ── 审计日志 ──
    AUDIT_EXCLUDE_PATHS: typing.List[str] = []
    """审计日志排除路径列表，支持前缀匹配（如 /static）和通配符（如 /api/v1/*/download）。
    留空则使用内置默认值（静态文件、文档、上传接口、流式下载等）"""

    # ── Redis（分布式限流 / 缓存，可选）──
    REDIS_URL: str = ""
    """Redis 连接地址，格式: redis://[:password@]host:port/db。
    留空则使用内存限流（单实例模式，多 worker 不共享状态）。"""

    # ── 数据库 ──
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "admin"
    DB_PASSWORD: str = ""
    DB_NAME: str = "vue_fastapi_admin"

    # ── 流水线 / Feed ──
    FEED_EXPIRE_DAYS: int = 3
    """Feed 文件下载有效期（天），过期后不可下载"""

    @property
    def TORTOISE_ORM(self) -> dict:
        return {
            "connections": {
                "default": {
                    "engine": "tortoise.backends.mysql",
                    "credentials": {
                        "host": self.DB_HOST,
                        "port": self.DB_PORT,
                        "user": self.DB_USER,
                        "password": self.DB_PASSWORD,
                        "database": self.DB_NAME,
                        "connect_timeout": 5,
                        "charset": "utf8mb4",
                        "init_command": "SET SESSION sql_notes = 0",
                    },
                    "minsize": 5,
                    "maxsize": 20,
                    "pool_recycle": 3600,
                }
            },
            "apps": {
                "models": {
                    "models": [
                        "app.models.admin",
                        "app.models.account",
                        "app.models.config",
                        "app.models.config_provider",
                        "app.models.site_pipeline",
                        "app.models.feed_file",
                        "app.models.gmail_account",
                        "app.models.shopify_collect",
                        "app.models.operation_job",
                        "app.models.import_job",
                        "app.models.ads_manager",
                    ],
                    "default_connection": "default",
                },
            },
            "use_tz": False,
            "timezone": "Asia/Shanghai",
        }

    DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    def validate_production_settings(self) -> list[str]:
        """校验生产环境关键配置，返回告警列表。

        在 app 启动时调用，DEBUG=false 时对高风险配置告警。
        """
        warnings_list = []

        if not self.SECRET_KEY or len(self.SECRET_KEY) < 16:
            warnings_list.append("SECRET_KEY 为空或过短（<16 字符），生产环境务必更换")

        if not self.DEFAULT_PASSWORD:
            warnings_list.append("DEFAULT_PASSWORD 未设置，新用户将使用空密码")

        if self.CORS_ORIGINS == ["*"]:
            warnings_list.append("CORS_ORIGINS 为 ['*']，生产环境应限制为具体域名")

        if self.DEBUG:
            warnings_list.append("DEBUG=True，生产环境应设为 False")

        if not self.DB_PASSWORD:
            warnings_list.append("DB_PASSWORD 为空，数据库未设置密码")

        return warnings_list


settings = Settings()
