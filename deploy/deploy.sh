#!/bin/bash
# =============================================
#  Wordpress Admin — 部署/更新/管理脚本
# =============================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
GIT_REPO="${GIT_REPO:-https://github.com/littledream901/wordpress_admin.git}"
GIT_BRANCH="${GIT_BRANCH:-dev}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
step() { echo -e "${BLUE}[STEP]${NC}  $1"; }

# 等待应用健康检查通过（最多60秒）
wait_healthy() {
    for i in $(seq 1 30); do
        if curl -sf http://localhost/api/v1/base/health >/dev/null 2>&1; then
            log "服务已就绪"
            return 0
        fi
        sleep 2
    done
    warn "服务可能尚未完全启动，请稍后手动验证"
    return 0
}

# =============================================
# 环境检查
# =============================================
check_deps() {
    command -v docker  >/dev/null 2>&1 || err "Docker 未安装，请先安装 Docker 20.10+"
    command -v docker compose >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1 || err "Docker Compose 未安装"
    log "依赖检查通过"
}

# =============================================
# clone — 首次克隆项目到服务器
# =============================================
clone_project() {
    local target_dir="${1:-wordpres-admin}"
    local repo_url="${2:-$GIT_REPO}"

    step "克隆项目代码..."

    if [ -d "$target_dir" ]; then
        warn "目录 $target_dir 已存在，跳过克隆"
        cd "$target_dir"
    else
        git clone -b "$GIT_BRANCH" "$repo_url" "$target_dir" || err "克隆失败，请检查仓库地址和网络"
        cd "$target_dir"
        log "项目已克隆到 $(pwd)"
    fi

    exec bash deploy/deploy.sh init
}

# =============================================
# init — 首次部署
# =============================================
init_deploy() {
    step "====== 首次部署 ======"
    check_deps

    cd "$PROJECT_DIR"

    # 1. 生成 .env
    if [ ! -f ".env" ]; then
        cp .env.example .env

        if command -v openssl >/dev/null 2>&1; then
            SECRET=$(openssl rand -hex 32)
            DEFAULT_PW=$(openssl rand -base64 12 | tr -dc 'A-Za-z0-9' | head -c16)
            DB_PW=$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c24)
            MYSQL_ROOT_PW=$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c24)
        else
            SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || python -c "import secrets; print(secrets.token_hex(32))")
            DEFAULT_PW=$(python3 -c "import secrets; print(secrets.token_urlsafe(12))" 2>/dev/null || python -c "import secrets; print(secrets.token_urlsafe(12))")
            DB_PW=$(python3 -c "import secrets; print(secrets.token_urlsafe(18))" 2>/dev/null || python -c "import secrets; print(secrets.token_urlsafe(18))")
            MYSQL_ROOT_PW=$(python3 -c "import secrets; print(secrets.token_urlsafe(18))" 2>/dev/null || python -c "import secrets; print(secrets.token_urlsafe(18))")
        fi

        sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET/" .env
        sed -i "s/^DEFAULT_PASSWORD=.*/DEFAULT_PASSWORD=$DEFAULT_PW/" .env
        sed -i "s/^DB_PASSWORD=.*/DB_PASSWORD=$DB_PW/" .env
        sed -i "s/^MYSQL_ROOT_PASSWORD=.*/MYSQL_ROOT_PASSWORD=$MYSQL_ROOT_PW/" .env
        log "已生成 .env（随机密钥）"
        echo ""
        echo -e "  ${YELLOW}管理员初始密码: ${DEFAULT_PW}${NC}"
        echo -e "  ${YELLOW}请妥善保存，可通过 .env 中 DEFAULT_PASSWORD 查看${NC}"
        echo ""
    else
        # .env 已存在，检查密钥是否仍为模板值
        if grep -q "^SECRET_KEY=your-secret-key-here" .env 2>/dev/null; then
            warn ".env 中 SECRET_KEY 仍为模板值，正在自动生成..."
            SECRET=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
            sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET/" .env
            log "已更新 SECRET_KEY"
        fi
        if grep -q "^DEFAULT_PASSWORD=$" .env 2>/dev/null; then
            DEFAULT_PW=$(openssl rand -base64 12 2>/dev/null | tr -dc 'A-Za-z0-9' | head -c16 || python3 -c "import secrets; print(secrets.token_urlsafe(12))")
            sed -i "s/^DEFAULT_PASSWORD=.*/DEFAULT_PASSWORD=$DEFAULT_PW/" .env
            log "已更新 DEFAULT_PASSWORD"
        fi
        if grep -q "^DB_PASSWORD=change-me-to-a-strong-password" .env 2>/dev/null; then
            DB_PW=$(openssl rand -base64 18 2>/dev/null | tr -dc 'A-Za-z0-9' | head -c24 || python3 -c "import secrets; print(secrets.token_urlsafe(18))")
            sed -i "s/^DB_PASSWORD=.*/DB_PASSWORD=$DB_PW/" .env
            log "已更新 DB_PASSWORD"
        fi
        if grep -q "^MYSQL_ROOT_PASSWORD=root-secret-change-me" .env 2>/dev/null; then
            MYSQL_ROOT_PW=$(openssl rand -base64 18 2>/dev/null | tr -dc 'A-Za-z0-9' | head -c24 || python3 -c "import secrets; print(secrets.token_urlsafe(18))")
            sed -i "s/^MYSQL_ROOT_PASSWORD=.*/MYSQL_ROOT_PASSWORD=$MYSQL_ROOT_PW/" .env
            log "已更新 MYSQL_ROOT_PASSWORD"
        fi
        warn ".env 已存在，跳过创建"
    fi

    # 2. 创建持久化目录
    mkdir -p data logs static/avatars

    # 3. 构建并启动
    step "构建镜像并启动容器..."
    docker compose up -d --build

    # 4. 等待服务就绪
    step "等待服务就绪..."
    wait_healthy

    # 5. 输出部署信息
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  部署成功！${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo "  访问地址:     http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'YOUR_IP')"
    echo "  健康检查:     curl http://localhost/api/v1/base/health"
    echo "  管理员密码:   grep DEFAULT_PASSWORD .env"
    echo "  查看日志:     docker compose logs -f"
    echo -e "${GREEN}========================================${NC}"
}

# =============================================
# update — 更新部署
# =============================================
update_deploy() {
    step "====== 更新部署 ======"
    check_deps

    cd "$PROJECT_DIR"

    # 1. 备份当前状态
    log "备份当前数据库和静态文件..."
    if [ "${DB_ENGINE:-mysql}" = "mysql" ] && [ -n "${MYSQL_ROOT_PASSWORD:-}" ] && docker compose exec -T db mysqladmin ping -uroot -p"${MYSQL_ROOT_PASSWORD}" --silent 2>/dev/null; then
        docker compose exec -T db mysqldump -u"${DB_USER:-admin}" -p"${DB_PASSWORD}" "${DB_NAME:-vue_fastapi_admin}" \
            > "data/backup_$(date +%Y%m%d_%H%M%S).sql" 2>/dev/null && log "MySQL 已备份到 data/" || warn "MySQL 备份失败"
    elif [ -f "data/db.sqlite3" ]; then
        cp data/db.sqlite3 "data/db.sqlite3.bak.$(date +%Y%m%d_%H%M%S)"
        log "SQLite 数据库已备份"
    fi
    if [ -d "static" ]; then
        tar -czf "data/static_backup_$(date +%Y%m%d_%H%M%S).tar.gz" static/ 2>/dev/null && log "static/ 已备份" || true
    fi

    if [ -f ".env" ]; then
        cp .env .env.bak
    fi

    # 2. 拉取代码
    log "拉取最新代码..."
    git pull origin "$(git rev-parse --abbrev-ref HEAD)" || warn "git pull 失败，使用当前代码继续"

    # 3. 还原 .env
    if [ -f ".env.bak" ] && ! diff -q .env .env.bak >/dev/null 2>&1; then
        mv .env.bak .env
        log ".env 已还原"
    else
        rm -f .env.bak
    fi

    # 4. 构建新镜像（旧容器保持运行，用户不中断）
    step "构建新镜像（老服务继续运行）..."
    docker compose build app || { err "构建失败"; exit 1; }

    # 5. 滚动更新：优雅停止旧容器 → 立即启动新容器
    step "滚动重启（优雅停止 → 启动新容器，中断约3-5秒）..."
    docker compose stop -t 30 app
    docker compose up -d --no-deps app

    # 6. 等待新服务健康检查通过
    step "等待服务就绪..."
    wait_healthy

    # 7. 清理旧镜像
    docker image prune -f 2>/dev/null || true

    # 6. 等待就绪
    step "等待服务就绪..."
    for i in $(seq 1 30); do
        if curl -sf http://localhost/api/v1/base/health >/dev/null 2>&1; then
            log "服务已就绪"
            break
        fi
        sleep 2
    done

    echo ""
    echo -e "${GREEN}====== 更新完成 ======${NC}"
    echo "  健康检查: curl http://localhost/api/v1/base/health"
    echo "  查看日志: docker compose logs -f"
}

# =============================================
# status — 查看运行状态
# =============================================
show_status() {
    cd "$PROJECT_DIR"

    echo -e "${BLUE}===== 容器状态 =====${NC}"
    docker compose ps 2>/dev/null || echo "  容器未运行"

    echo ""
    echo -e "${BLUE}===== 健康检查 =====${NC}"
    if curl -sf http://localhost/api/v1/base/health >/dev/null 2>&1; then
        echo "  状态: ${GREEN}正常${NC}"
        curl -s http://localhost/api/v1/base/health
        echo ""
    else
        echo "  状态: ${RED}异常${NC}"
    fi

    echo ""
    echo -e "${BLUE}===== 资源占用 =====${NC}"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null || true

    echo ""
    echo -e "${BLUE}===== 近期日志 =====${NC}"
    docker compose logs --tail 20 2>/dev/null || echo "  无法获取日志"
}

# =============================================
# restart — 重启服务
# =============================================
restart_service() {
    step "重启服务..."
    cd "$PROJECT_DIR"
    docker compose restart
    sleep 5

    if curl -sf http://localhost/api/v1/base/health >/dev/null 2>&1; then
        log "重启完成，服务正常"
    else
        warn "重启后健康检查失败，请检查日志: docker compose logs -f"
    fi
}

# =============================================
# stop — 停止服务
# =============================================
stop_service() {
    step "停止服务..."
    cd "$PROJECT_DIR"
    docker compose down
    log "服务已停止"
}

# =============================================
# logs — 查看日志
# =============================================
show_logs() {
    cd "$PROJECT_DIR"
    docker compose logs -f --tail "${1:-100}"
}

# =============================================
# 入口
# =============================================
print_usage() {
    echo "用法: bash deploy/deploy.sh <命令> [参数]"
    echo ""
    echo "命令:"
    echo "  clone [目录] [仓库地址]  克隆项目并初始化部署"
    echo "  init                     首次部署（生成密钥 -> 构建 -> 启动）"
    echo "  update                   更新部署（备份 -> 拉取代码 -> 重建）"
    echo "  status                   查看运行状态和健康检查"
    echo "  restart                  重启服务"
    echo "  stop                     停止服务"
    echo "  logs [行数]              查看日志（默认 100 行，Ctrl+C 退出）"
    echo ""
    echo "示例:"
    echo "  # 从零开始（服务器上执行）"
    echo "  git clone -b dev https://github.com/littledream901/wordpress_admin.git"
    echo "  cd wordpress_admin"
    echo "  bash deploy/deploy.sh init"
    echo ""
    echo "  # 或一键克隆"
    echo "  bash deploy/deploy.sh clone wordpres-admin"
    echo ""
    echo "  # 更新"
    echo "  bash deploy/deploy.sh update"
}

case "${1:-}" in
    clone)
        clone_project "${2:-wordpres-admin}" "${3:-$GIT_REPO}"
        ;;
    init)
        init_deploy
        ;;
    update)
        update_deploy
        ;;
    status)
        show_status
        ;;
    restart)
        restart_service
        ;;
    stop)
        stop_service
        ;;
    logs)
        show_logs "${2:-100}"
        ;;
    -h|--help|help|"")
        print_usage
        ;;
    *)
        echo -e "${RED}未知命令: $1${NC}"
        echo ""
        print_usage
        exit 1
        ;;
esac
