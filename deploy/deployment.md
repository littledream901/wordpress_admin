# 部署指南

本文档涵盖从零到生产可用的完整部署流程，默认使用 MySQL + Docker Compose 方案，同时支持 1Panel 面板部署。

---

## 项目简介

Wordpress Admin 是一个基于 FastAPI + Vue 3 + Naive UI 构建的后台管理系统。

**核心功能模块：**

| 模块 | 说明 |
|------|------|
| 用户/角色/菜单/部门 | 完善的 RBAC 权限体系 |
| 审计日志 | 自动记录用户操作/IP/内容 |
| 站点流水线 | 自动化建站、DNS、NS、301重定向 |
| Shopify 采集 | 集合/单品采集，产品管理，批量分配 |
| WooCommerce 导入 | 产品批量导入到 WordPress 站点 |
| HubStudio 任务分发 | 环境创建/账号创建/GMC检查共4种任务类型 |
| Dynadot NS 管理 | 域名 NS 修改、批量操作 |
| Cloudflare DNS | DNS 解析、批量操作 |
| 1Panel 集成 | 站点创建/删除/状态同步 |
| Gmail 账号管理 | 站点分配、状态监控 |
| 配置文件管理 | Feed Manager、RSS Feed 替换 |

---

## 环境要求

| 依赖 | 最低版本 | 说明 |
|------|----------|------|
| Docker | 20.10+ | 容器运行时 |
| Docker Compose | 2.0+ | 容器编排（`docker compose`） |
| Git | 2.0+ | 克隆代码 |
| curl | 任意 | 健康检查 |

---

## 快速开始（Docker Compose + MySQL）

### 步骤 1：克隆项目

```bash
git clone -b dev https://github.com/littledream901/wordpress_admin.git /opt/wordpress-admin
cd /opt/wordpress-admin
```

### 步骤 2：一键部署

```bash
bash deploy/deploy.sh init
```

该命令自动完成：
1. 检查 Docker 和 Docker Compose 是否已安装
2. 根据 `.env.example` 生成 `.env`，自动创建随机密钥：
   - `SECRET_KEY` — JWT 签名密钥
   - `DEFAULT_PASSWORD` — 管理员初始密码
   - `DB_PASSWORD` — MySQL 业务用户密码
   - `MYSQL_ROOT_PASSWORD` — MySQL root 密码
3. 创建 `logs/`、`static/avatars/` 持久化目录
4. 启动 MySQL 容器并等待就绪
5. 构建应用镜像并启动容器
6. 自动执行数据库迁移（优先 Aerich，回退 generate_schemas）
7. 初始化默认数据（菜单/角色/管理员）
8. 等待服务就绪后输出访问信息

### 步骤 3：验证

```bash
# 健康检查
curl http://localhost/api/v1/base/health
# 预期返回: {"code":200,"message":"ok"}

# 获取管理员密码
grep DEFAULT_PASSWORD .env
```

### 步骤 4：访问

浏览器打开 `http://服务器IP`，使用用户名 `admin` 和步骤 3 获取的密码登录。

---

## 1Panel 部署

### 方式一：通过编排模板导入

1. 登录 1Panel 面板，进入 **容器 → 编排 → 创建编排**
2. 在服务器上克隆项目：
   ```bash
   git clone -b dev https://github.com/littledream901/wordpress_admin.git /opt/wordpres-admin
   ```
3. 在 1Panel 编排界面中填写：
   - **名称**：`wordpres-admin`
   - **路径**：`/opt/wordpres-admin`
   - **Compose 文件**：选择项目根目录的 `docker-compose.yml`
4. 创建 `.env` 文件：
   ```bash
   cd /opt/wordpres-admin
   cp .env.example .env
   # 修改所有密码占位符
   nano .env
   ```
5. 点击 **启动**

### 方式二：命令行部署 + 1Panel 管理

```bash
git clone -b dev https://github.com/littledream901/wordpress_admin.git /opt/wordpres-admin
cd /opt/wordpres-admin
bash deploy/deploy.sh init
# 部署完成后，1Panel 容器列表自动可见
```

---

## 环境配置说明

部署时需要创建 `.env` 文件（`deploy.sh init` 会自动生成），核心配置：

```bash
# ========== 必填：安全 ==========
SECRET_KEY=<自动生成>    # JWT 签名密钥，openssl rand -hex 32
DEFAULT_PASSWORD=<自动生成>  # 管理员初始密码

# ========== 必填：数据库 ==========
DB_ENGINE=mysql
DB_HOST=db              # Docker Compose 内部服务名
DB_PORT=3306
DB_USER=admin
DB_PASSWORD=<自动生成>   # MySQL 业务用户密码
DB_NAME=vue_fastapi_admin

# ========== MySQL root 密码 ==========
MYSQL_ROOT_PASSWORD=<自动生成>

# ========== 必填：运行模式 ==========
DEBUG=false             # 生产环境必须为 false
CORS_ORIGINS=["https://admin.your-domain.com"]
```

---

## 第三方服务配置

部分模块依赖第三方服务，部署后需在 **系统管理 → 提供商管理** 中配置：

| 服务 | 所需配置键 | 用途 |
|------|-----------|------|
| Cloudflare | CF_API_TOKEN, CF_ACCOUNT_ID | DNS 解析、域名管理 |
| Dynadot | DYNADOT_API_KEY | 域名 NS 修改 |
| 1Panel | OP_URL, OP_API_KEY | 自动建站、站点管理 |
| HubStudio | HS_API_KEY, HS_BASE_URL | 浏览器环境自动化 |
| Shopify | SHOPIFY_API_KEY | 产品采集 |
| WooCommerce | WP_URL, consumer_key, consumer_secret | 产品导入 |

---

## 项目目录结构（生产环境关键路径）

```
wordpres-admin/
├── app/                    # FastAPI 后端
│   ├── api/v1/             # API 路由（仅路由注册和参数校验）
│   ├── controllers/        # 业务逻辑层
│   ├── models/             # 数据表模型
│   ├── schemas/            # Pydantic 请求/响应模型
│   ├── services/           # 第三方服务封装
│   ├── core/               # 全局基础能力（认证/RBAC/CRUD/中间件）
│   ├── utils/              # 通用工具函数
│   └── settings/           # 全局配置
├── web/                    # Vue 3 前端
│   ├── src/
│   │   ├── api/            # axios 请求封装（按模块拆分）
│   │   ├── components/     # 公共组件
│   │   ├── views/          # 页面视图
│   │   ├── router/         # 动态路由
│   │   └── store/          # Pinia 全局状态
│   └── dist/               # 构建产物
├── deploy/                 # 部署配置文件
├── static/avatars/         # 用户头像上传目录
└── migrations/             # Aerich 数据库迁移
```

---

## 数据库

### 场景一：Docker Compose 内置 MySQL（默认）

`docker-compose.yml` 自带 `db` 服务（MySQL 8.0），首次启动自动创建数据库和用户。数据持久化在 Docker volume `mysql-data`。

无需任何额外配置，`deploy.sh init` 一键完成。

### 场景二：使用 1Panel 已安装的 MySQL

如果 1Panel 已经安装了 MySQL（通常在容器列表可见），按以下步骤配置：

**1. 创建数据库**

在 1Panel 中进入 **数据库 → MySQL**，创建数据库：
```
数据库名: vue_fastapi_admin
字符集: utf8mb4
排序规则: utf8mb4_unicode_ci
```

或手动执行：
```sql
CREATE DATABASE vue_fastapi_admin CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

**2. 修改 .env**

```bash
# 将 DB_HOST 改为 1Panel MySQL 容器的 IP（通常在 1Panel 容器列表可查，或 172.x.x.x）
DB_HOST=172.17.0.x

# 填入 1Panel 中 MySQL 的账号密码
DB_USER=admin
DB_PASSWORD=your-actual-password

# 删除 MYSQL_ROOT_PASSWORD 行（外部 MySQL 不需要）
# MYSQL_ROOT_PASSWORD=...  ← 删除这行
```

**3. 修改 docker-compose.yml**

删除或注释掉 `db` 服务段，并移除 `app` 中的 `depends_on: db`：

```yaml
services:
  app:
    # depends_on:       ← 注释掉
    #   db:
    #     condition: service_healthy
    ports:
      ...

  # db:                 ← 整个 db 段删除或注释
  #   image: mysql:8.0
  #   ...
```

**4. 启动**

```bash
docker compose up -d --build
```

### 场景三：SQLite（单机/开发）

```bash
# 修改 .env
DB_ENGINE=sqlite
DB_SQLITE_PATH=./data/db.sqlite3
```

然后使用不含 `db` 服务的 `docker-compose.yml` 启动。

---

## deploy.sh 命令参考

| 命令 | 说明 |
|------|------|
| `bash deploy/deploy.sh clone <目录> <仓库>` | 克隆项目并初始化部署 |
| `bash deploy/deploy.sh init` | 首次部署（生成密钥 → 启动 MySQL → 构建 → 初始化） |
| `bash deploy/deploy.sh update` | 更新部署（备份数据库 → 拉取代码 → 重建） |
| `bash deploy/deploy.sh status` | 查看容器状态、健康检查和资源占用 |
| `bash deploy/deploy.sh restart` | 重启所有服务 |
| `bash deploy/deploy.sh stop` | 停止所有服务 |
| `bash deploy/deploy.sh logs [行数]` | 实时查看日志 |

---

## 更新部署

```bash
cd wordpres-admin
bash deploy/deploy.sh update
```

`update` 自动完成：
1. 备份 MySQL 数据库（mysqldump → `data/backup_*.sql`）
2. 备份 `.env` 配置
3. 拉取最新代码
4. 重新构建并启动容器
5. 清理旧 Docker 镜像

---

## 数据备份与恢复

### MySQL 备份

```bash
# 手动备份（含 static/avatars/ 目录）
docker compose exec -T db mysqldump -uadmin -p"$(grep DB_PASSWORD .env | cut -d= -f2)" vue_fastapi_admin \
  > "backup_$(date +%Y%m%d_%H%M%S).sql"
tar -czf "static_backup_$(date +%Y%m%d_%H%M%S).tar.gz" static/

# 定时备份（crontab，每天凌晨 3 点）
# 0 3 * * * cd /opt/wordpres-admin && docker compose exec -T db mysqldump -uadmin -p"your-password" wordpres_admin > /backup/db_$(date +\%Y\%m\%d).sql
```

### MySQL 恢复

```bash
# 停止应用（保留数据库容器运行）
docker compose stop app

# 导入备份
docker compose exec -T db mysql -uadmin -p"$(grep DB_PASSWORD .env | cut -d= -f2)" vue_fastapi_admin < backup_20260714.sql

# 恢复头像
tar -xzf static_backup_20260714.tar.gz

# 重启
docker compose up -d
```

---

## Docker 手动操作

```bash
# 启动所有服务
docker compose up -d --build

# 停止
docker compose down

# 重启
docker compose restart

# 仅重启应用
docker compose restart app

# 查看日志
docker compose logs -f --tail 100 app

# 进入应用容器
docker compose exec app sh

# 进入 MySQL
docker compose exec db mysql -uadmin -p vue_fastapi_admin
```

---

## HTTPS 反向代理

容器监听 `80` 端口（HTTP），生产环境建议在前置 Nginx 或 Caddy 处理 HTTPS。

### Nginx 反向代理

```nginx
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

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
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

### Caddy（更简单，自动签发证书）

```caddyfile
admin.your-domain.com {
    reverse_proxy 127.0.0.1:80
    encode gzip
}
```

---

## 回滚

```bash
# 切换到目标版本
git checkout <commit-hash>

# 重建
bash deploy/deploy.sh update

# 如数据库不兼容，恢复备份
docker compose stop app
docker compose exec -T db mysql -uadmin -p"..." vue_fastapi_admin < backup.sql
docker compose up -d
```

---

## 常见问题

### Q: 启动后提示 SECRET_KEY 未设置

```bash
echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env
docker compose restart app
```

### Q: MySQL 连接失败

```bash
# 检查 MySQL 是否就绪
docker compose logs db

# 手动测试连接
docker compose exec db mysql -uadmin -p"$(grep DB_PASSWORD .env | cut -d= -f2)" vue_fastapi_admin -e "SELECT 1"
```

### Q: 端口 80 被占用

在 `.env` 中设置 `APP_PORT=8080`，或在 `docker-compose.yml` 中修改 `ports` 映射。

### Q: 如何重置管理员密码

```bash
docker compose exec app python -c "
from app.core.init_app import init_default_data
init_default_data()
print('管理员密码已重置为 .env 中 DEFAULT_PASSWORD 的值')
"
```

### Q: 头像上传后不显示

确认 Nginx 中 `/static/` 路径已配置，且 `static/avatars/` 目录存在：

```bash
docker compose exec app ls -la static/avatars/
```

### Q: 建站/DNS/采集任务失败

1. 在 **系统管理 → 提供商管理** 中检查对应服务是否已配置并激活
2. 在 **任务中心** 查看具体错误日志
3. 检查网络连通性：`docker compose exec app ping api.cloudflare.com`

### Q: 从 SQLite 迁移到 MySQL

1. 导出现有数据（SQLite → JSON）
2. 修改 `.env` 为 MySQL 配置
3. 重新部署后导入数据

---

## 安全建议

1. **密钥管理**：所有密码使用 `deploy.sh init` 自动生成的随机值
2. **防火墙**：仅开放 80/443 端口，3306（MySQL）不对外暴露
3. **CORS 限制**：生产环境设为具体域名，不使用 `["*"]`
4. **定期备份**：设置 crontab 定时备份 MySQL 和 `static/avatars/`
5. **日志归档**：定期清理 `logs/` 目录
6. **镜像更新**：定期 `docker compose build --no-cache --pull` 更新基础镜像
7. **RBAC 审计**：所有关键操作自动记录到审计日志表，定期审查
