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
| ADS 环境管理 | 防关联浏览器环境管理，站点关联与解绑 |
| Shopify 采集 | 集合/单品采集，产品管理，批量分配 |
| WooCommerce 导入 | 产品批量导入到 WordPress 站点 |
| Shopify 导入 | 产品通过 Admin API 导入到 Shopify Store |
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
git clone -b main https://github.com/littledream901/wordpress_admin.git /opt/wordpress-admin

```

### 步骤 2：一键部署

```bash
cd /opt/wordpress-admin
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
   git clone -b main https://github.com/littledream901/wordpress_admin.git /opt/wordpress-admin
   ```
3. 在 1Panel 编排界面中填写：
   - **名称**：`wordpress-admin`
   - **路径**：`/opt/wordpress-admin`
   - **Compose 文件**：选择项目根目录的 `docker-compose.yml`
4. 创建 `.env` 文件：
   ```bash
   cd /opt/wordpress-admin
   cp .env.example .env
   # 修改所有密码占位符
   nano .env
   ```
5. 点击 **启动**

### 方式二：命令行部署 + 1Panel 管理

```bash
git clone -b main https://github.com/littledream901/wordpress_admin.git /opt/wordpress-admin
cd /opt/wordpress-admin
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
wordpress-admin/
├── app/                    # FastAPI 后端
│   ├── api/v1/             # API 路由（仅路由注册和参数校验）
│   ├── controllers/        # 业务逻辑层
│   ├── models/             # 数据表模型
│   ├── schemas/            # Pydantic 请求/响应模型
│   ├── services/           # 第三方服务封装
│   │   └── importers/       # 产品导入器抽象层 (Shopify/WooCommerce)
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

### 场景四：远程连接数据库（IDE / 客户端工具）

使用 `deploy.sh init` 部署后，MySQL 远程连接已**自动配置**：

- **端口映射**：`docker-compose.yml` 默认将 MySQL 的 `3306` 端口映射到宿主机 `127.0.0.1:3306`（可通过 `.env` 中 `MYSQL_PORT` 自定义）
- **SSL 要求**：`deploy.sh` 已自动执行 `ALTER USER ... REQUIRE NONE`，admin 和 root 用户均可直接远程连接

**连接信息（admin 用户）：**

| 配置项 | 值 |
|--------|-----|
| Host | 服务器公网 IP |
| Port | 3306（或 `.env` 中 `MYSQL_PORT` 指定的端口） |
| User | `admin`（`.env` 中 `DB_USER` 的值） |
| Password | `.env` 中 `DB_PASSWORD` 的值 |
| Database | `vue_fastapi_admin` |

**连接信息（root 用户）：**

| 配置项 | 值 |
|--------|-----|
| Host | 服务器公网 IP |
| Port | 3306（或 `.env` 中 `MYSQL_PORT` 指定的端口） |
| User | `root` |
| Password | `.env` 中 `MYSQL_ROOT_PASSWORD` 的值 |
| Database | 留空（root 可查看所有库） |

> **安全提醒**：默认端口映射仅绑定 `127.0.0.1`，外部无法直连。如需从外网访问，需修改 `.env` 中 `MYSQL_PORT` 为 `0.0.0.0:3306`（不推荐）。更安全的做法是使用 SSH 隧道：
> ```bash
> ssh -L 3307:127.0.0.1:3306 root@服务器IP
> ```
> 然后本地连接 `127.0.0.1:3307`。

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
cd /opt/wordpress-admin
bash deploy/deploy.sh update
```

`update` 自动完成：
1. 备份 MySQL 数据库（mysqldump → `data/backup_*.sql`）
2. 备份 `.env` 配置
3. 拉取最新代码
4. 构建新镜像（老容器继续运行，用户不中断）
5. 优雅停止旧容器 → 启动新容器（中断仅 3-5 秒）
6. 等待健康检查通过
7. 清理旧 Docker 镜像

---

## 数据备份与恢复

### MySQL 备份

```bash
# 手动备份（含 static/avatars/ 目录）
docker compose exec -T db mysqldump -uadmin -p"$(grep DB_PASSWORD .env | cut -d= -f2)" vue_fastapi_admin \
  > "backup_$(date +%Y%m%d_%H%M%S).sql"
tar -czf "static_backup_$(date +%Y%m%d_%H%M%S).tar.gz" static/

# 定时备份（crontab，每天凌晨 3 点）
# 0 3 * * * cd /opt/wordpress-admin && docker compose exec -T db mysqldump -uadmin -p"your-password" vue_fastapi_admin > /backup/db_$(date +\%Y\%m\%d).sql
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
        proxy_pass http://127.0.0.1:18080;  # 端口与 .env 中 APP_PORT 或 docker-compose.yml 映射一致
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
    reverse_proxy 127.0.0.1:18080
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

## 完全重新部署（清除所有数据）

当需要彻底重置环境时（如数据库结构变更、迁移失败、测试后清理），可以删除所有容器、数据卷和文件后重新部署。

### 步骤 1：停止并删除容器和 MySQL 数据卷

```bash
cd /opt/wordpress-admin

# 停止并删除容器、网络、数据卷（MySQL 所有数据将丢失！）
docker compose down -v

# 确认已清理
docker compose ps
```

`-v` 会一并删除 `docker-compose.yml` 中定义的 `mysql-data` 匿名卷，相当于清空 MySQL 数据库。

### 步骤 2：删除持久化文件

```bash
# 删除备份文件
rm -f data/backup_*.sql data/static_backup_*.tar.gz

# 删除日志
rm -rf logs/*

# 删除上传的头像
rm -rf static/avatars/*

# 删除 .env 配置文件（如需要重新生成密钥）
rm -f .env .env.bak
```

### 步骤 3：拉取最新代码

```bash
# 确保在正确的分支
git fetch origin
git checkout main
git pull origin main
```

### 步骤 4：重新部署

```bash
bash deploy/deploy.sh init
```

> **提醒**：重新部署会生成新的 `DEFAULT_PASSWORD`，请注意保存输出的管理员密码。

### 本地开发环境（SQLite）清理

本地开发使用 SQLite 时，需额外删除数据库文件：

```bash
rm -f data/db.sqlite3 data/db.sqlite3.bak*
```

### 仅清理容器（保留数据）

如果只想重建容器而保留数据库和配置文件：

```bash
docker compose down          # 仅停止容器，不删除数据卷
bash deploy/deploy.sh update # 拉取代码并重建
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

1. 导出现有数据：

```bash
# 在项目目录下执行，将 SQLite 数据导出为 JSON
docker compose exec app python -c "
import asyncio, json
from tortoise import Tortoise
from app.settings import TORTOISE_ORM

async def export_data():
    await Tortoise.init(config=TORTOISE_ORM)
    conn = Tortoise.get_connection('default')
    # 导出所有业务表（排除 aerich 迁移表）
    tables = ['users', 'roles', 'menus', 'apis', 'depts', 'auditlog',
              'config', 'configprovider', 'sites', 'gmails', 'shopify_sources',
              'shopify_products', 'operation_jobs', 'accounts', 'ads_env']
    dump = {}
    for table in tables:
        try:
            rows = await conn.execute_query(f'SELECT * FROM {table}')
            dump[table] = rows
        except Exception:
            pass
    with open('data/export.json', 'w', encoding='utf-8') as f:
        json.dump(dump, f, ensure_ascii=False, default=str)
    print('数据已导出到 data/export.json')

asyncio.run(export_data())
"
```

2. 备份旧数据目录：

```bash
cp data/db.sqlite3 data/db.sqlite3.bak
```

3. 修改 `.env` 为 MySQL 配置（参考上方环境配置说明），然后重新部署：

```bash
bash deploy/deploy.sh update
```

4. 导入数据（重新部署后执行）：

```bash
docker compose exec app python -c "
import asyncio, json
from tortoise import Tortoise
from app.settings import TORTOISE_ORM

async def import_data():
    await Tortoise.init(config=TORTOISE_ORM)
    conn = Tortoise.get_connection('default')
    with open('data/export.json', 'r', encoding='utf-8') as f:
        dump = json.load(f)
    for table, rows in dump.items():
        if rows:
            # 按表逐条插入，跳过自增 ID 让数据库自动分配
            for row in rows:
                keys = [k for k in row.keys() if k != 'id']
                placeholders = ', '.join(['%s'] * len(keys))
                columns = ', '.join(keys)
                values = [row[k] for k in keys]
                await conn.execute_query(
                    f'INSERT INTO {table} ({columns}) VALUES ({placeholders})',
                    values
                )
    print('数据导入完成')

asyncio.run(import_data())
"
```

---

## 安全建议

1. **密钥管理**：所有密码使用 `deploy.sh init` 自动生成的随机值
2. **防火墙**：仅开放 80/443 端口，3306（MySQL）不对外暴露
3. **CORS 限制**：生产环境设为具体域名，不使用 `["*"]`
4. **定期备份**：设置 crontab 定时备份 MySQL 和 `static/avatars/`
5. **日志归档**：定期清理 `logs/` 目录
6. **镜像更新**：定期 `docker compose build --no-cache --pull` 更新基础镜像
7. **RBAC 审计**：所有关键操作自动记录到审计日志表，定期审查
