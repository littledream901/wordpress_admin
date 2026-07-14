#!/bin/sh
set -e

echo "========================================="
echo "  Vue FastAPI Admin - Docker Entrypoint"
echo "========================================="

# =============================================
# 环境检查
# =============================================
is_prod() {
    [ "$DEBUG" = "false" ] || [ "$DEBUG" = "False" ] || [ -z "$DEBUG" ]
}

if is_prod; then
    echo "[INFO] 生产模式启动"

    # 密钥校验
    if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "your-secret-key-here" ]; then
        echo "==================================================================="
        echo "[WARN] SECRET_KEY 未设置或使用模板默认值!"
        echo "[WARN] 请通过 .env 设置: SECRET_KEY=\$(openssl rand -hex 32)"
        echo "==================================================================="
    fi

    # 密码校验
    if [ -z "$DEFAULT_PASSWORD" ] || [ "$DEFAULT_PASSWORD" = "123456" ]; then
        echo "==================================================================="
        echo "[WARN] DEFAULT_PASSWORD 为空或使用弱口令，建议更换"
        echo "==================================================================="
    fi

    # CORS 校验
    if echo "${CORS_ORIGINS:-}" | grep -qE '^\["\*"\]$|^\[\]$'; then
        echo "==================================================================="
        echo "[WARN] CORS_ORIGINS 配置过于宽松 (允许所有来源)"
        echo "[WARN] 生产环境建议配置为具体域名: [\"https://your-domain.com\"]"
        echo "==================================================================="
    fi
else
    echo "[INFO] 开发模式启动（热重载 / API 文档已开启）"
fi

# =============================================
# 数据库迁移
# =============================================
if [ "$DB_ENGINE" = "mysql" ]; then
    echo "[INFO] 等待 MySQL 就绪..."
    for i in $(seq 1 30); do
        if mysqladmin ping -h"${DB_HOST:-db}" -u"${DB_USER:-admin}" -p"${DB_PASSWORD}" --silent 2>/dev/null; then
            echo "[INFO] MySQL 已就绪"
            break
        fi
        echo "[INFO] 等待 MySQL... ($i/30)"
        sleep 3
    done
fi

echo "[INFO] 同步数据库表结构..."
python -c "
import asyncio
from tortoise import Tortoise
from app.settings import TORTOISE_ORM

async def upgrade():
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas(safe=True)
    print('[INFO] 数据库表结构已同步')

asyncio.run(upgrade())
"

# =============================================
# 初始化默认数据
# =============================================
echo "[INFO] 初始化默认数据（菜单/角色/管理员）..."
python -c "
from app.core.init_app import init_default_data
init_default_data()
print('[INFO] 默认数据已初始化')
"

# =============================================
# 启动 Nginx
# =============================================
echo "[INFO] 启动 Nginx（前端静态资源 + API 反向代理）..."
nginx -t 2>/dev/null && nginx || echo "[WARN] Nginx 配置测试未通过，跳过启动"

# =============================================
# 启动 FastAPI
# =============================================
WORKERS="${WORKERS:-2}"

if is_prod; then
    echo "[INFO] 启动 FastAPI (uvicorn, ${WORKERS} workers, 端口 9999)..."
    exec uvicorn app:app \
        --host 127.0.0.1 \
        --port "${PORT:-9999}" \
        --workers "$WORKERS" \
        --log-level info \
        --no-server-header \
        --proxy-headers
else
    echo "[INFO] 启动 FastAPI (开发模式, 热重载, 端口 ${PORT:-9999})..."
    exec python run.py
fi
