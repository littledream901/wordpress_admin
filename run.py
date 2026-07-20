import os
import uvicorn
from uvicorn.config import LOGGING_CONFIG

if __name__ == "__main__":
    dev_mode = os.getenv("DEV_MODE", "false").lower() in ("true", "1", "yes")
    debug = os.getenv("DEBUG", "true").lower() in ("true", "1", "yes")
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "9999"))
    workers = 1 if dev_mode else int(os.getenv("WORKERS", "1"))

    # uvicorn 日志格式对齐 loguru
    LOGGING_CONFIG["formatters"]["default"]["fmt"] = "%(asctime)s | %(levelname)-8s | %(message)s"
    LOGGING_CONFIG["formatters"]["default"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
    LOGGING_CONFIG["formatters"]["access"]["fmt"] = (
        '%(asctime)s | %(levelname)-8s | %(client_addr)s - "%(request_line)s" %(status_code)s'
    )
    LOGGING_CONFIG["formatters"]["access"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
    # 生产环境 uvicorn.access 设为 WARNING，开发环境 INFO
    LOGGING_CONFIG["loggers"]["uvicorn.access"]["level"] = "INFO" if debug else "WARNING"

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=dev_mode,
        workers=workers,
        log_config=LOGGING_CONFIG,
    )
