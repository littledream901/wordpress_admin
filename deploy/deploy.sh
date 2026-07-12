#!/bin/bash
# =============================================
#  Vue FastAPI Admin — 服务器部署/更新脚本
#  用法: bash deploy.sh [init|update]
#
#  首次部署: bash deploy.sh init
#  更新版本: bash deploy.sh update
# =============================================
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

init_deploy() {
    log "====== 首次部署 ======"

    cd "$PROJECT_DIR"

    # 创建环境变量文件
    if [ ! -f ".env" ]; then
        cp .env.example .env
        # 自动生成随机密钥
        SECRET=$(openssl rand -hex 32 2>/dev/null || python -c "import secrets; print(secrets.token_hex(32))")
        DEFAULT_PW=$(openssl rand -base64 12 2>/dev/null || python -c "import secrets; print(secrets.token_urlsafe(12))")
        sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET/" .env
        sed -i "s/^DEFAULT_PASSWORD=.*/DEFAULT_PASSWORD=$DEFAULT_PW/" .env
        log "已生成 .env 文件（含随机密钥）"
    else
        warn ".env 已存在，跳过"
    fi

    # 创建数据目录
    mkdir -p data logs

    # 启动
    docker compose up -d --build

    log "====== 部署完成 ======"
    echo ""
    echo "  访问地址: http://$(hostname -I | awk '{print $1}')"
    echo "  健康检查: curl http://localhost/api/v1/base/health"
    echo "  管理员密码: grep DEFAULT_PASSWORD .env"
    echo "  查看日志: docker compose logs -f"
}

update_deploy() {
    log "====== 更新部署 ======"

    cd "$PROJECT_DIR"

    # 备份 .env
    if [ -f ".env" ]; then
        cp .env .env.bak
    fi

    log "拉取最新代码..."
    git pull origin "$(git rev-parse --abbrev-ref HEAD)"

    # 还原 .env
    if [ -f ".env.bak" ]; then
        mv .env.bak .env
    fi

    log "重新构建并启动..."
    docker compose up -d --build

    # 清理旧镜像
    docker image prune -f

    log "====== 更新完成 ======"
    echo "  健康检查: curl http://localhost/api/v1/base/health"
}

# ========== 入口 ==========
case "${1:-}" in
    init)
        init_deploy
        ;;
    update)
        update_deploy
        ;;
    *)
        echo "用法: bash deploy.sh {init|update}"
        echo ""
        echo "  init   — 首次部署（生成 .env + 构建 + 启动）"
        echo "  update — 拉取最新代码 + 重建容器"
        exit 1
        ;;
esac
