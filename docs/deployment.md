# 部署指南

本文档涵盖从零到生产可用的完整部署流程。

---

## 部署前检查清单

部署到生产环境前，请逐项确认：

### 安全配置

- [ ] `SECRET_KEY` 已使用 `openssl rand -hex 32` 生成强随机密钥
- [ ] `DEFAULT_PASSWORD` 已设置为强密码（非 `123456` 等弱口令）
- [ ] `CORS_ORIGINS` 已配置为生产域名（如 `["https://your-domain.com"]`），禁止使用 `["*"]`
- [ ] `DEBUG=false`（生产模式下 API 文档自动关闭）
- [ ] 已配置 HTTPS 反向代理终止 TLS

### 数据库

- [ ] 生产环境使用 MySQL 或 PostgreSQL（非 SQLite）
- [ ] 数据库密码已修改为非默认值
- [ ] 数据库定期备份策略已就位
- [ ] 若使用 SQLite，`DB_SQLITE_PATH` 指向持久化卷目录（Docker 默认 `./data/db.sqlite3`）

### 限流与缓存

- [ ] 多 Worker 模式下已配置 `REDIS_URL` 实现全局分布式限流
- [ ] 根据业务量调整 `RATE_LIMIT_MAX_REQUESTS` 和 `RATE_LIMIT_WINDOW_SECONDS`

### 前端

- [ ] 已执行 `pnpm build` 生成生产构建
- [ ] 前端代码中无 `console.log` / `debugger` 残留
- [ ] `.env.production` 中 `VITE_BASE_API` 指向正确 API 路径

### 容器化

- [ ] `migrations/` 目录已纳入版本控制（不在 `.gitignore` 中）
- [ ] `app/uploads/` 已加入 `.gitignore` 和 `.dockerignore`
- [ ] `data/` 和 `logs/` 目录已由 Docker volume 持久化
- [ ] 容器健康检查正常：`curl http://localhost/api/v1/base/health`

---

## 环境要求

| 依赖 | 最低版本 |
|------|----------|
| Docker | 20.10+ |
| Docker Compose | 2.0+ |
| Python | 3.11+（仅本地开发需要） |
| Node.js | 18+（仅前端构建需要） |

---

## 快速开始

### 方式一：一键部署（推荐）

```bash
# 克隆项目
git clone <your-repo-url>
cd vue-fastapi-admin-main

# 首次部署（自动生成 .env、构建镜像、启动容器）
bash deploy/deploy.sh init

# 获取管理员密码
grep DEFAULT_PASSWORD .env

# 验证服务
curl http://localhost/api/v1/base/health
# 预期返回: {"code":200,"message":"ok"}
```

`deploy.sh init` 自动完成：
1. 从 `.env.example` 生成 `.env`
2. 自动生成随机 `SECRET_KEY` 和 `DEFAULT_PASSWORD`
3. 创建 `data/` 和 `logs/` 持久化目录
4. 构建 Docker 镜像并启动容器
5. 执行数据库迁移和初始数据导入

### 方式二：手动部署

```bash
# 1. 环境配置
cp .env.example .env

# 2. 生成密钥（Linux/macOS）
SECRET=$(openssl rand -hex 32)
DEFAULT_PW=$(openssl rand -base64 12)
sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET/" .env
sed -i "s/^DEFAULT_PASSWORD=.*/DEFAULT_PASSWORD=$DEFAULT_PW/" .env

# 3. 修改生产配置
# 编辑 .env，确保以下设置正确：
#   DEBUG=false
#   CORS_ORIGINS=["https://your-domain.com"]

# 4. 创建持久化目录
mkdir -p data logs

# 5. 构建并启动
docker compose up -d --build

# 6. 验证
curl http://localhost/api/v1/base/health
```

---

## 生产环境配置详解

### 1. 安全密钥

```bash
# 生成 64 位十六进制密钥
openssl rand -hex 32

# 写入 .env
# SECRET_KEY=a1b2c3d4e5f6...（你的生成值）
```

> **重要**: `SECRET_KEY` 用于 JWT 签名，泄漏后攻击者可伪造任意用户的 Token。请务必生成唯一随机值。

### 2. 跨域配置（CORS）

开发环境可设为宽松值，生产环境**必须限定精确域名**：

```bash
# 开发/本地
CORS_ORIGINS=["http://localhost"]

# 生产（单个域名）
CORS_ORIGINS=["https://admin.your-domain.com"]

# 生产（多域名）
CORS_ORIGINS=["https://admin.example.com", "https://www.example.com"]
```

若 `DEBUG=false` 且 CORS 仍为 `["*"]` 或 `["http://localhost"]`，应用将**拒绝启动**。

### 3. 数据库选择

#### SQLite（默认，适合单机/小规模）

```bash
DB_ENGINE=sqlite
DB_SQLITE_PATH=./data/db.sqlite3
```

- 数据存储在 `data/` 目录，由 Docker volume 持久化
- 无需额外安装数据库服务
- 不适合高并发或多实例部署

#### MySQL（生产推荐）

```bash
DB_ENGINE=mysql
DB_HOST=192.168.1.100
DB_PORT=3306
DB_USER=admin
DB_PASSWORD=your-secure-password
DB_NAME=vue_fastapi_admin
```

部署前需先在 MySQL 服务器上创建数据库：

```sql
CREATE DATABASE vue_fastapi_admin CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'admin'@'%' IDENTIFIED BY 'your-secure-password';
GRANT ALL PRIVILEGES ON vue_fastapi_admin.* TO 'admin'@'%';
FLUSH PRIVILEGES;
```

#### PostgreSQL

```bash
DB_ENGINE=postgres
DB_HOST=192.168.1.100
DB_PORT=5432
DB_USER=admin
DB_PASSWORD=your-secure-password
DB_NAME=vue_fastapi_admin
```

### 4. Redis 分布式限流

单 Worker 模式下内存限流即可；多 Worker 模式建议配置 Redis：

```bash
# .env 中添加
REDIS_URL=redis://:your-password@redis-host:6379/0
```

若留空，限流状态仅在单进程内有效，多 Worker 会各自独立计数。

### 5. Worker 数量

```bash
# .env
WORKERS=2  # 建议设为 CPU 核心数
```

- `WORKERS=1`：单进程，适合低负载
- `WORKERS=2~4`：推荐生产配置
- `WORKERS` 设置仅在 `DEV_MODE=false` 时生效

---

## 反向代理与 HTTPS

Docker 容器暴露 `80` 端口（HTTP）。生产环境推荐在前置 Nginx/Caddy 层处理 HTTPS。

### Nginx 反向代理示例

```nginx
# /etc/nginx/sites-available/vue-fastapi-admin

# HTTP → HTTPS 重定向
server {
    listen 80;
    server_name admin.your-domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name admin.your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/admin.your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/admin.your-domain.com/privkey.pem;

    # 安全头（与容器内 Nginx 重复，但 L7 层面双重防护）
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # 客户端上传大小限制
    client_max_body_size 100m;

    location / {
        proxy_pass http://127.0.0.1:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

### Caddy 反向代理（更简单）

```caddyfile
admin.your-domain.com {
    reverse_proxy 127.0.0.1:80
    encode gzip
}
```

Caddy 会自动申请和续期 Let's Encrypt 证书。

---

## Docker Compose 编排

### 默认单容器部署

```yaml
# docker-compose.yml
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: vue-fastapi-admin
    restart: unless-stopped
    ports:
      - "${APP_PORT:-80}:80"
    env_file:
      - .env
    volumes:
      - ./data:/opt/vue-fastapi-admin/data
      - ./logs:/opt/vue-fastapi-admin/logs
    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1/api/v1/base/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
```

### 分离数据库（推荐生产方案）

```yaml
# docker-compose.prod.yml
services:
  app:
    # ... 同上，去掉 depends_on 也可以先启动 app（会自动重试 DB 连接）

  db:
    image: mysql:8.0
    container_name: vue-fastapi-admin-db
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASSWORD}
      MYSQL_DATABASE: ${DB_NAME}
      MYSQL_USER: ${DB_USER}
      MYSQL_PASSWORD: ${DB_PASSWORD}
    volumes:
      - ./mysql-data:/var/lib/mysql
    ports:
      - "127.0.0.1:3306:3306"
```

---

## 持久化与备份

### 需要备份的数据

| 路径 | 内容 | 备份方式 |
|------|------|----------|
| `data/db.sqlite3` | SQLite 数据库文件 | 定期 `cp` 或 `rsync` |
| `data/` | 用户上传文件（头像等） | 随数据库一起备份 |
| `logs/` | 应用日志 | 可选，按需保留 |

### SQLite 备份脚本

```bash
#!/bin/bash
# backup.sh
BACKUP_DIR="/backup/vue-fastapi-admin"
mkdir -p "$BACKUP_DIR"
cp data/db.sqlite3 "$BACKUP_DIR/db.sqlite3.$(date +%Y%m%d_%H%M%S)"
# 保留最近 7 天的备份
find "$BACKUP_DIR" -name "db.sqlite3.*" -mtime +7 -delete
```

### MySQL 备份

```bash
# 通过 docker compose exec 备份
docker compose exec db mysqldump -u admin -p vue_fastapi_admin > backup_$(date +%Y%m%d).sql
```

---

## 升级与回滚

### 滚动升级

```bash
# 拉取最新代码
git pull origin main

# 重新构建并替换容器（数据卷中的数据保留）
docker compose up -d --build

# 清理旧镜像
docker image prune -f
```

### 回滚

```bash
# 1. 切换到目标版本
git checkout <commit-hash>

# 2. 重建
docker compose up -d --build

# 3. 若数据库不兼容，恢复备份
cp data/db.sqlite3.bak data/db.sqlite3
docker compose restart
```

### 零停机升级（多实例）

```bash
# 扩容到 2 个实例
docker compose up -d --scale app=2 --build

# 等待新实例健康
sleep 30

# 缩容（移除旧实例）
docker compose up -d --scale app=1
```

---

## 监控与健康检查

### 内置健康端点

```bash
# 容器内
curl http://127.0.0.1/api/v1/base/health

# 宿主机
curl http://localhost/api/v1/base/health
```

正常返回：`{"code":200,"message":"ok"}`

### 日志查看

```bash
# 实时日志
docker compose logs -f app

# 最近 100 行
docker compose logs --tail 100 app

# 只看错误
docker compose logs app | grep -i error
```

### 资源监控

```bash
# 容器资源占用
docker stats vue-fastapi-admin

# 进程列表
docker compose exec app ps aux

# 数据库大小
ls -lh data/db.sqlite3
```

---

## 常见问题

### Q: 启动后报 `SECRET_KEY 未设置`

`.env` 文件中的 `SECRET_KEY` 为空，请生成随机值：

```bash
# 生成并写入
echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env
docker compose restart
```

### Q: 数据库文件找不到或权限错误

确认 `data/` 目录存在且有写权限：

```bash
mkdir -p data logs
chmod 755 data logs
```

### Q: CORS 错误（前端请求被拒绝）

检查 `.env` 中 `CORS_ORIGINS` 是否包含前端域名。若使用 Docker，请求从 Nginx 走同源 `/api/` 路径，通常不会有 CORS 问题。

### Q: 如何重置管理员密码

```bash
# 进入容器
docker compose exec app python -c "
from app.controllers.user import user_controller
from app.settings.config import settings
import asyncio

async def reset():
    user = await user_controller.model.filter(username='admin').first()
    if user:
        from app.utils.password import get_password_hash
        user.password = get_password_hash(settings.DEFAULT_PASSWORD)
        await user.save()
        print('密码已重置为 DEFAULT_PASSWORD')
    else:
        print('admin 用户不存在')

asyncio.run(reset())
"
```

### Q: 端口 80 被占用

修改 `docker-compose.yml` 中的端口映射：

```yaml
ports:
  - "${APP_PORT:-8080}:80"  # 将宿主机端口改为 8080
```

或通过 `.env` 设置：

```bash
APP_PORT=8080
```

---

## 安全加固建议

1. **限制容器能力**：在 `docker-compose.yml` 中添加 `security_opt: ["no-new-privileges:true"]`
2. **只读根文件系统**：添加 `read_only: true`（需调整 `tmpfs` 配置）
3. **网络隔离**：将 MySQL 等外部服务放入独立 Docker 网络
4. **定期更新基础镜像**：`docker compose build --no-cache --pull`
5. **审计日志保留**：定期归档 `auditlog` 表数据，避免无限增长
6. **WAF/CC 防护**：前置 Cloudflare 或类似服务增加防护层
