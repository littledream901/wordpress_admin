#!/bin/sh
set -e

# 加载 .env 环境变量（shell 脚本不自动读取 .env）
if [ -f /app/.env ]; then
    set -a
    . /app/.env
    set +a
fi

echo "========================================="
echo "  Wordpress Admin - Docker Entrypoint"
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
# 创建持久化目录
# =============================================
mkdir -p logs static/avatars uploads/feeds

# =============================================
# 数据库迁移
# =============================================
echo "[INFO] 等待 MySQL 就绪..."
MYSQL_READY=false
for i in $(seq 1 60); do
    if mysql -h"${DB_HOST:-db}" -u"${DB_USER:-admin}" -p"${DB_PASSWORD}" -e "SELECT 1" >/dev/null 2>&1; then
        echo "[INFO] MySQL 已就绪"
        MYSQL_READY=true
        break
    fi
    echo "[INFO] 等待 MySQL 认证就绪... ($i/60)"
    sleep 3
done
if [ "$MYSQL_READY" = false ]; then
    echo "[ERROR] MySQL 未能在 180 秒内就绪，退出"
    exit 1
fi

echo "[INFO] 执行数据库迁移..."
python -c "
import asyncio
import time
from tortoise import Tortoise
from tortoise.exceptions import DBConnectionError
from app.settings import TORTOISE_ORM

async def upgrade():
    # 带重试的 Tortoise 初始化
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            await Tortoise.init(config=TORTOISE_ORM)
            break
        except DBConnectionError as e:
            if attempt < max_retries:
                print(f'[INFO] Tortoise 连接失败 (尝试 {attempt}/{max_retries})，10秒后重试...')
                time.sleep(10)
            else:
                raise

    # 优先尝试 Aerich 迁移
    from tortoise import connections
    conn = connections.get('default')
    try:
        result = await conn.execute_query(\"SHOW TABLES LIKE 'aerich'\")
        if result[1]:
            print('[INFO] Aerich 迁移表存在，执行 aerich upgrade...')
            from aerich import Command
            command = Command(tortoise_config=TORTOISE_ORM, location='./migrations')
            await command.init()
            await command.upgrade(run_in_transaction=True)
            print('[INFO] Aerich 迁移完成')
            return
    except Exception:
        pass

    # 回退：检查是否空库，空库则 generate_schemas
    try:
        result = await conn.execute_query(\"SHOW TABLES LIKE 'user'\")
        if not result[1]:
            await Tortoise.generate_schemas(safe=True)
            print('[INFO] 空库，已通过 generate_schemas 建表')
            # 标记 Aerich 已同步
            try:
                from aerich import Command
                command = Command(tortoise_config=TORTOISE_ORM, location='./migrations')
                await command.init_db(safe=True)
            except Exception:
                pass
        else:
            print('[INFO] 业务表已存在且无 Aerich，跳过迁移')
    except Exception as e:
        print(f'[WARN] 迁移检测异常: {e}')

asyncio.run(upgrade())
"

# =============================================
# 初始化种子数据（幂等，不做高风险修复）
# =============================================
echo "[INFO] 初始化种子数据（菜单/角色/Provider/管理员）..."
python -c "
from app.core.init_app import init_default_data
init_default_data()
print('[INFO] 种子数据已初始化')
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
