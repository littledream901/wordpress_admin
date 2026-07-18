# WordPress 站点流水线管理平台

基于 **FastAPI + Vue 3 + Naive UI** 的全栈运维管理后台，实现从域名注册到 WordPress 上线的一站式自动化流水线。

---

## 功能概览

### 通用后台管理
- **用户 / 角色 / 菜单 / API** — 完整 RBAC 权限体系，接口粒度鉴权
- **部门管理** — 闭包表无限层级
- **审计日志** — 全量 HTTP 请求记录，可追溯
- **配置中心** — 多 Provider 多账号多节点配置，热更新

### 站点流水线（核心）
- **站点管理** — 域名全生命周期追踪，批量 CRUD
- **DNS 解析** — Cloudflare 批量添加 A/CNAME 记录
- **NS 配置** — Dynadot 批量设置 Name Server
- **一键建站** — 1Panel 集成，10 步自动化部署 WordPress
- **SSL 证书** — Let's Encrypt 自动申请与绑定
- **301 重定向** — Cloudflare Page Rule 按需创建
- **ADS 环境管理** — 防关联浏览器环境管理，站点关联与解绑
- **产品导入** — Shopify 产品导入到 WooCommerce 或 Shopify Store
- **Feed 管理** — Google Merchant Center Feed 文件管理

### HubStudio 浏览器自动化
- **任务调度** — 创建环境、创建账号、更新环境、登录WP
- **本地 Agent** — 独立后台进程，轮询领取任务，执行浏览器操作
- **心跳监控** — Agent 在线状态实时追踪

### Shopify 采集
- **采集源管理** — 店铺 URL 管理
- **产品池** — 自动采集、状态追踪、按需分配

### 任务中心
- 27 种操作类型统一调度（DNS / 建站 / 采集 / 导入 / ADS 管理 等）
- 批次追踪、步骤进度、重试机制、幂等性保障

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI 0.111 |
| ORM | Tortoise ORM 0.23 + Aerich 迁移 |
| 认证 | PyJWT (Authorization: Bearer) + Argon2 密码哈希 |
| 数据校验 | Pydantic v2 |
| 前端 | Vue 3 + Vite + Pinia |
| UI | Naive UI 2.34 |
| CSS | UnoCSS (原子化) + Sass |
| 数据库 | SQLite / MySQL / PostgreSQL |
| 部署 | Docker 多阶段构建 + Nginx |

---

## 快速开始

### 环境要求

- Python >= 3.11
- Node.js >= 18
- [uv](https://docs.astral.sh/uv/) 或 pip


###
```bash
git config --global http.proxy http://127.0.0.1:7890
git config --global https.proxy http://127.0.0.1:7890
git push origin dev
```
### 1. 初始化

```bash
# 克隆项目
git clone <your-repo-url>
cd wordpress-admin

# 复制环境配置
cp .env.example .env
# 编辑 .env，设置 SECRET_KEY 和 DEFAULT_PASSWORD

# 安装 Python 依赖
uv sync
# 或: pip install -r requirements.txt

# 初始化数据库并导入种子数据
python scripts/init_system.py
```

### 2. 启动后端

```bash
.\.venv\Scripts\Activate.ps1 
python run.py
# 访问: http://localhost:9999
# 开发模式: DEV_MODE=true python run.py
```

### 3. 启动前端

```bash
cd web
pnpm install
pnpm dev
# 访问: http://localhost:3100
```

### 4. 登录

默认管理员账号：`admin`，密码为 `.env` 中 `DEFAULT_PASSWORD` 的值。

---

## 项目结构

```
.
├── app/                         # 后端
│   ├── api/v1/                  # API 路由层
│   │   ├── base/                # 登录 / Token / 用户信息
│   │   ├── users/               # 用户管理
│   │   ├── roles/               # 角色管理
│   │   ├── menus/               # 菜单管理
│   │   ├── apis/                # API 权限管理
│   │   ├── depts/               # 部门管理
│   │   ├── auditlog/            # 审计日志
│   │   ├── config/              # 系统配置 + ConfigProvider
│   │   ├── accounts/            # 通用账号
│   │   ├── site_pipeline/       # 站点流水线（核心，含 ADS 路由）
│   │   ├── gmail/               # Gmail 管理
│   │   ├── shopify/             # Shopify 采集
│   │   ├── operation_jobs/      # 任务中心
│   │   ├── recycle_bin.py       # 回收站（统一软删除恢复）
│   │   └── imports/             # 批量导入
│   ├── controllers/             # 业务逻辑层
│   │   └── ads_manager.py       # ADS 环境管理
│   ├── core/                    # 核心（认证 / 权限 / 中间件 / CRUD 基类）
│   ├── models/                  # Tortoise ORM 数据模型
│   │   └── ads_manager.py       # AdsEnv 模型（多对多站点）
│   ├── schemas/                 # Pydantic 请求 / 响应 Schema
│   │   └── ads_manager.py       # ADS 校验模型
│   ├── services/                # 外部服务集成
│   │   ├── importers/           # 产品导入器抽象层
│   │   │   ├── __init__.py
│   │   │   ├── shopify.py       # Shopify Store 导入
│   │   │   └── woocommerce.py   # WooCommerce 导入
│   │   ├── cloudflare_service.py
│   │   ├── onepanel_service.py
│   │   ├── hubstudio_service.py
│   │   ├── woo_import_service.py
│   │   ├── shopify_collect_service.py
│   │   └── providers/           # Dynadot 等第三方
│   ├── agent/                   # HubStudio Agent 独立进程
│   ├── settings/                # 全局配置
│   └── utils/                   # 工具函数
├── web/                         # 前端
│   └── src/
│       ├── views/               # 页面模块
│       │   ├── site-pipeline/
│       │   │   ├── ads-manager/  # ADS 环境管理
│       │   │   └── ...
│       ├── router/              # 动态路由
│       ├── store/               # Pinia 状态
│       ├── api/                 # API 调用层
│       └── components/          # 公共组件
├── deploy/                      # 部署配置
│   ├── entrypoint.sh            # 容器启动脚本
│   ├── web.conf                 # Nginx 配置
│   └── deploy.sh                # 服务器部署脚本
├── Dockerfile                   # 多阶段构建
├── docker-compose.yml           # Docker Compose
├── migrations/                  # Aerich 迁移
├── scripts/                     # 工具脚本
├── tests/                       # 测试
├── pyproject.toml
├── run.py                       # 启动入口
└── Makefile
```

---

## 架构设计

### 认证流程

```
POST /api/v1/base/access_token   →  用户名 + 密码  →  access_token + refresh_token
Authorization: Bearer <token>    →  中间件解析 JWT  →  权限校验 →  API 响应
```

- 双 Token 机制：access_token 7 天，refresh_token 30 天
- Argon2 密码哈希，HS256 JWT 签名
- 超级管理员绕过 RBAC 校验
- 按钮级前端权限控制（`v-permission` 指令）

### 配置提供者（ConfigProvider）

管理多账号多节点的"接入配置"：

| 类型 | 用途 |
|------|------|
| `cloudflare` | API Token + Account ID |
| `dynadot` | API Key |
| `onepanel` | 面板地址 + API Key + 模板配置 |
| `hubstudio` | Connector 路径 + 代理 + 账号 |
| `shopify` | 采集超时等 |
| `woo` | WooCommerce 导入参数 |
| `pipeline` | 流水线全局配置 |

每个 Provider 可创建多个实例，通过 `ResourceProviderBinding` 将资源绑定到特定实例。

### 建站流水线（10 步）

```
create_site → apply_ssl → restore_db → restore_files → rebuild_after_files
→ replace_domain → patch_wp_config → rebuild_before_scripts → create_woo_key → create_ctx
```

通过 `asyncio.Semaphore(PROVISION_MAX_CONCURRENT)` 控制并发，默认同时 3 个。

### 统一任务中心（OperationJob）

所有异步操作（27 种类型）统一由 `OperationJob` 管理：

- 单任务 / 批量任务（batch_id 批次追踪）
- 步骤进度（step / total_steps）
- 重试机制（retry_count / max_retry）
- 状态：pending → queued → running → success / failed / cancelled

---

## API 端点

所有接口前缀 `/api/v1`，需认证的接口携带 `Authorization: Bearer <token>`。

| 模块 | 路径 | 说明 |
|------|------|------|
| 基础 | `/base/health` | 健康检查（无需认证） |
| 基础 | `/base/access_token` | 登录获取 Token |
| 基础 | `/base/refresh_token` | 刷新 Token |
| 基础 | `/base/userinfo` | 当前用户信息 |
| 基础 | `/base/usermenu` | 用户菜单树 |
| 基础 | `/base/userapi` | 用户 API 权限列表 |
| 系统 | `/user` | 用户 CRUD |
| 系统 | `/role` | 角色 CRUD + 权限授权 |
| 系统 | `/menu` | 菜单 CRUD |
| 系统 | `/api` | API 权限 CRUD + 刷新 |
| 系统 | `/dept` | 部门 CRUD |
| 系统 | `/auditlog` | 审计日志查询 |
| 配置 | `/config` | 系统配置 CRUD |
| 配置 | `/config-provider` | Provider + 配置项 + 绑定 |
| 业务 | `/site-pipeline/sites` | 站点管理（批量 DNS / 建站 / 重定向 / Woo 导入） |
| 业务 | `/site-pipeline/hub-jobs` | HubStudio 任务 |
| 业务 | `/site-pipeline/feed` | Feed 文件管理 |
| 业务 | `/site-pipeline/ads` | ADS 环境 CRUD + 站点关联/解绑 |
| 业务 | `/gmail` | Gmail 账号 CRUD |
| 业务 | `/shopify` | 采集源 + 产品管理 |
| 业务 | `/operation-jobs` | 任务列表 + 重试 + 取消 |
| 业务 | `/import` | 批量导入 + 模板下载 |

---

## Docker 部署

> **部署前必读**: 请先阅读 [部署指南](deploy/deployment.md)，确保生产环境配置正确。

### 快速部署（推荐）

```bash
# 1. 初始化并启动（自动生成安全密钥）
bash deploy/deploy.sh init

# 2. 获取管理员密码
grep DEFAULT_PASSWORD .env

# 3. 验证服务
curl http://localhost/api/v1/base/health
```

### 更新部署

```bash
bash deploy/deploy.sh update
```

### 手动部署步骤

```bash
# 1. 配置环境变量
cp .env.example .env

# 2. 生成安全密钥（务必执行！）
# Linux / macOS:
sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$(openssl rand -hex 32)/" .env
sed -i "s/^DEFAULT_PASSWORD=.*/DEFAULT_PASSWORD=$(openssl rand -base64 12)/" .env
# Windows PowerShell:
# (Get-Content .env) -replace '^SECRET_KEY=.*', "SECRET_KEY=$(-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 64 | % {[char]$_}))" | Set-Content .env

# 3. 生产环境必要修改
# 编辑 .env:
#   - DEBUG=false（生产模式）
#   - CORS_ORIGINS=["https://your-domain.com"]（必须指定真实域名）
#   - DB_ENGINE=mysql  # 生产建议使用 MySQL/PostgreSQL

# 4. 创建数据目录并启动
mkdir -p data logs
docker compose up -d --build

# 5. 查看日志
docker compose logs -f
```

### 容器架构

```
┌──────────────────────────────────────────────────┐
│  Docker Network (app-network)                     │
│                                                   │
│  ┌────────────────────────────────────────────┐  │
│  │  App 容器 (wordpress-admin)                │  │
│  │  Nginx (:80)                               │  │
│  │    ├── /api/*   → uvicorn (:9999)          │  │
│  │    │               Python FastAPI           │  │
│  │    ├── /static/* → 静态文件                  │  │
│  │    └── /*       → SPA (index.html)         │  │
│  │  Volumes: ./data, ./logs, ./static,        │  │
│  │           ./uploads/feeds                   │  │
│  └────────────────────────────────────────────┘  │
│                                                   │
│  ┌────────────────────────────────────────────┐  │
│  │  DB 容器 (wordpress-admin-db)              │  │
│  │  MySQL 8.0 (:3306)                          │  │
│  │  Volume: mysql-data → /var/lib/mysql        │  │
│  └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

### 环境变量参考

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `SECRET_KEY` | **是** | - | JWT 签名密钥，`openssl rand -hex 32` 生成 |
| `DEFAULT_PASSWORD` | **是** | - | 新用户初始密码 |
| `DEBUG` | 否 | `false` | `true`=开发模式（显示文档/CORS宽松） |
| `CORS_ORIGINS` | 否 | `["*"]` | 生产必须改为具体域名 |
| `DB_ENGINE` | 否 | `sqlite` | `sqlite` / `mysql` / `postgres` |
| `DB_SQLITE_PATH` | 否 | `./data/db.sqlite3` | SQLite 文件路径（Docker 内建议保持默认） |
| `DB_HOST/PORT/USER/PASSWORD/NAME` | 否 | - | MySQL/PostgreSQL 连接参数 |
| `REDIS_URL` | 否 | - | Redis 地址，多 Worker 建议配置 |
| `WORKERS` | 否 | `1` | 生产模式 Worker 数量 |
| `RATE_LIMIT_MAX_REQUESTS` | 否 | `100` | 每分钟最大请求数 |

### 使用外部数据库（生产推荐）

```bash
# 编辑 .env
DB_ENGINE=mysql
DB_HOST=your-db-host
DB_PORT=3306
DB_USER=admin
DB_PASSWORD=your-secure-password
DB_NAME=vue_fastapi_admin
```

### 启用 HTTPS（生产必要）

推荐在 Docker 宿主机上使用 Nginx/Caddy 反向代理终止 TLS：

```nginx
# 宿主机 Nginx 示例
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /etc/ssl/certs/your-domain.pem;
    ssl_certificate_key /etc/ssl/private/your-domain.key;

    location / {
        proxy_pass http://127.0.0.1:80;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $host;
    }
}
```

### 常用运维命令

```bash
docker compose up -d --build   # 构建并启动
docker compose down             # 停止并删除容器
docker compose logs -f          # 实时日志
docker compose restart          # 重启
docker compose exec app curl http://127.0.0.1/api/v1/base/health  # 健康检查
```

---

## 开发指南

```bash
# 数据库迁移
aerich migrate          # 生成迁移
aerich upgrade          # 应用迁移

# 代码检查
ruff check ./app        # Lint
black ./                # 格式化

# 运行测试
pytest tests/ -v

# 系统重新初始化（危险！会覆盖数据）
python scripts/init_system.py
```

### HubStudio Agent

Agent 是独立的浏览器自动化进程，支持本地运行或打包为 EXE：

```bash
# 本地运行
.\.venv\Scripts\Activate.ps1 
python -m app.agent.hubstudio_agent

# 打包为 EXE
cd agent_build && build_agent.bat
```

关键环境变量：

| 变量 | 说明 |
|------|------|
| `HUB_AGENT_SERVER_URL` | 后端地址 |
| `HUB_AGENT_USERNAME` | 登录账号 |
| `HUB_AGENT_PASSWORD` | 登录密码 |
| `HUB_AGENT_WORKER_NAME` | 节点标识 |
| `HUB_AGENT_POLL_INTERVAL` | 轮询间隔（秒） |

---

## 许可证

MIT
