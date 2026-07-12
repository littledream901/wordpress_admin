#!/bin/sh
set -e

echo "========================================="
echo "  Vue FastAPI Admin - Docker Entrypoint"
echo "========================================="

# ========== 环境检查 ==========
if [ "$DEBUG" = "false" ] || [ "$DEBUG" = "False" ]; then
    echo "[INFO] 生产模式启动"

    # 安全检查：生产环境必须设置 SECRET_KEY
    if [ "$SECRET_KEY" = "3488a63e1765035d386f05409663f55c83bfae3b3c61a932744b20ad14244dcf" ] || [ -z "$SECRET_KEY" ]; then
        echo "==================================================================="
        echo "[WARN] SECRET_KEY 未设置或使用默认值！"
        echo "[WARN] 请通过环境变量设置生产密钥: -e SECRET_KEY=<random-secret>"
        echo "==================================================================="
    fi

    # 检查 DEFAULT_PASSWORD
    if [ "$DEFAULT_PASSWORD" = "123456" ] || [ "$DEFAULT_PASSWORD" = "change-me-to-a-complex-password" ]; then
        echo "==================================================================="
        echo "[WARN] DEFAULT_PASSWORD 使用不安全的值，建议更换为复杂密码"
        echo "==================================================================="
    fi
else
    echo "[INFO] 开发模式启动"
fi

# ========== 数据库表结构同步 ==========
echo "[INFO] 执行数据库迁移 (aerich upgrade)..."
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

# ========== 初始化默认数据（菜单/角色/管理员） ==========
echo "[INFO] 初始化默认数据..."
python -c "
from app.core.init_app import init_default_data
init_default_data()
print('[INFO] 默认数据已初始化')
"

# ========== 启动 Nginx ==========
echo "[INFO] 启动 Nginx..."
nginx

# ========== 启动后端 ==========
echo "[INFO] 启动 FastAPI (端口 9999)..."
if [ "$DEBUG" = "true" ] || [ "$DEBUG" = "True" ]; then
    exec python run.py
else
    exec uvicorn app:app --host 127.0.0.1 --port 9999 --workers 2 --log-level info --no-server-header
fi
