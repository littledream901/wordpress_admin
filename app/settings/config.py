import os
import typing
import warnings

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
    CORS_ORIGINS: typing.List = ["*"]
    """允许的跨域来源，生产环境必须指定具体域名，如 ["https://your-domain.com"]"""
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: typing.List = ["*"]
    CORS_ALLOW_HEADERS: typing.List = ["*"]

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

    # ── 限流 ──
    RATE_LIMIT_MAX_REQUESTS: int = 100  # 每分钟最大请求数
    RATE_LIMIT_WINDOW_SECONDS: int = 60  # 限流窗口（秒）

    # ── Redis（分布式限流 / 缓存，可选）──
    REDIS_URL: str = ""
    """Redis 连接地址，格式: redis://[:password@]host:port/db。
    留空则使用内存限流（单实例模式，多 worker 不共享状态）。"""

    # ── 数据库 ──
    DB_ENGINE: str = "sqlite"  # sqlite / mysql / postgres
    DB_SQLITE_PATH: str = ""  # 为空则使用默认路径
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "vue_fastapi_admin"

    @property
    def TORTOISE_ORM(self) -> dict:
        connections = {}
        if self.DB_ENGINE == "mysql":
            connections["default"] = {
                "engine": "tortoise.backends.mysql",
                "credentials": {
                    "host": self.DB_HOST,
                    "port": self.DB_PORT,
                    "user": self.DB_USER,
                    "password": self.DB_PASSWORD,
                    "database": self.DB_NAME,
                },
            }
        elif self.DB_ENGINE == "postgres":
            connections["default"] = {
                "engine": "tortoise.backends.asyncpg",
                "credentials": {
                    "host": self.DB_HOST,
                    "port": self.DB_PORT,
                    "user": self.DB_USER,
                    "password": self.DB_PASSWORD,
                    "database": self.DB_NAME,
                },
            }
        else:  # sqlite
            db_path = self.DB_SQLITE_PATH or f"{self.BASE_DIR}/db.sqlite3"
            connections["default"] = {
                "engine": "tortoise.backends.sqlite",
                "credentials": {"file_path": db_path},
            }
        return {
            "connections": connections,
            "apps": {
                "models": {
                    "models": ["app.models", "aerich.models"],
                    "default_connection": "default",
                },
            },
            "use_tz": False,
            "timezone": "Asia/Shanghai",
        }
    DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"


settings = Settings()
