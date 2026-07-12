import os
import uvicorn
from uvicorn.config import LOGGING_CONFIG

if __name__ == "__main__":
    # 修改默认日志配置
    LOGGING_CONFIG["formatters"]["default"]["fmt"] = "%(asctime)s - %(levelname)s - %(message)s"
    LOGGING_CONFIG["formatters"]["default"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
    LOGGING_CONFIG["formatters"]["access"][
        "fmt"
    ] = '%(asctime)s - %(levelname)s - %(client_addr)s - "%(request_line)s" %(status_code)s'
    LOGGING_CONFIG["formatters"]["access"]["datefmt"] = "%Y-%m-%d %H:%M:%S"

    dev_mode = os.getenv("DEV_MODE", "false").lower() in ("true", "1", "yes")
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "9999"))
    # 开发模式单进程热重载；生产模式可用 WORKERS 指定多进程（默认 1）
    workers = 1 if dev_mode else int(os.getenv("WORKERS", "1"))

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=dev_mode,
        workers=workers,
        log_config=LOGGING_CONFIG,
    )
