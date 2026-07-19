# HubStudioAgent 打包与部署

## 目录结构

```
agent_build/
  build_agent.bat           # 双击即可打包
  build_agent_entry.py      # PyInstaller 入口文件
  hubstudio_agent.spec      # PyInstaller 打包配置
  build/                    # 构建缓存（可删除）
  dist/HubStudioAgent.exe   # 最终可执行文件
```

## 快速开始

### 打包

双击 `build_agent.bat`，或在项目根目录执行：

```powershell
python -m PyInstaller --distpath agent_build\dist --workpath agent_build\build agent_build\hubstudio_agent.spec
```

输出文件：`agent_build\dist\HubStudioAgent.exe`

### 部署到目标机器

1. 将 `HubStudioAgent.exe` 复制到目标 Windows 机器
2. 在同目录创建 `.env` 文件配置参数
3. 双击运行

---

## 配置来源与优先级

Agent 启动后的配置加载顺序：

```
1. 本地 .env 文件（基础默认值）
2. 服务端数据库（provider_config_item 表）── 最终以 DB 为准
```

Agent 登录后端后会调用 `GET /site-pipeline/hub-job/agent-config` 拉取当前 Provider 的配置，**覆盖本地 .env 中相同的项**。服务端不可达时自动降级使用本地 .env。

### 必须本地配置（DB 中没有）

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `HUB_AGENT_SERVER_URL` | `http://127.0.0.1:9999/api/v1` | 后端 API 地址 |
| `HUB_AGENT_USERNAME` | `admin` | 登录账号 |
| `HUB_AGENT_PASSWORD` | `123456` | 登录密码 |
| `HUB_AGENT_WORKER_NAME` | 本机主机名 | Worker 节点名称 |
| `HUB_AGENT_PROVIDER_ID` | `0` | 供应商 ID（用于拉配置 & 任务筛选） |
| `HUB_AGENT_POLL_INTERVAL` | `5` | 轮询间隔（秒） |
| `HUB_AGENT_HEARTBEAT_INTERVAL` | `30` | 心跳间隔（秒） |
| `HUB_AGENT_MAX_BACKOFF` | `300` | 网络故障最大退避（秒） |
| `HUB_CONNECTOR_DIR` | `D:\Program Files\Hubstudio` | Connector 安装目录（机器相关） |
| `HUB_EXE_NAME` | `hubstudio_connector.exe` | 可执行文件名 |
| `HUB_HTTP_PORT` | `6873` | Connector HTTP 端口 |
| `HUB_BASE_URL` | `http://localhost:6873` | Connector API 地址 |
| `HUB_AGENT_LOG_DIR` | `./logs/hubstudio` | 日志文件目录 |

### 从 DB 拉取（本地 .env 可写，但会被 DB 覆盖）

Agent 启动后自动从服务端拉取以下配置，以 DB 中的值为准：

| DB 配置项 (config_key) | 对应 Agent 参数 | 说明 |
|-------------------------|-----------------|------|
| `app_id` | `HUB_APP_ID` | HubStudio 应用 ID |
| `app_secret` | `HUB_APP_SECRET` | HubStudio 应用密钥 |
| `group_code` | `HUB_GROUP_CODE` | 分组代码 |
| `kernel_version` / `real_kernel_version` | `HUB_KERNEL_VER` | 浏览器内核版本 |
| `proxy_type_name` | `HUB_DEFAULT_PROXY_TYPE` | 默认代理类型 |
| `ui_language` | `HUB_DEFAULT_UI_LANGUAGE` | 浏览器界面语言 |
| `admin_site_name` | `HUB_ADMIN_SITE_NAME` | WordPress 站点名称 |
| `admin_site_alias` | `HUB_ADMIN_SITE_ALIAS` | WordPress 站点别名 |
| `admin_account_name` | `HUB_ADMIN_ACCOUNT_NAME` | 默认 WP 管理员账号 |
| `admin_account_password` | `HUB_ADMIN_ACCOUNT_PASSWORD` | 默认 WP 管理员密码 |

### 不需要写在 .env 里

以下配置由服务端在派发任务时注入到任务 payload 中，Agent 无需本地配置：

| 配置项 | 来源 |
|--------|------|
| 代理地址/账号/密码 | DB `provider_config_item`，服务端注入 `update_env` 任务 |
| Gmail 账号/密码 | DB `gmail_account` 表，服务端注入 `create_account` 任务 |
| WordPress 登录凭据 | 服务端注入 `wp_login` 任务 |

---

## .env 示例

```env
# 后端连接（必须）
HUB_AGENT_SERVER_URL=http://192.168.1.100:9999/api/v1
HUB_AGENT_USERNAME=admin
HUB_AGENT_PASSWORD=mypassword

# Worker（必须）
HUB_AGENT_WORKER_NAME=worker-01
HUB_AGENT_POLL_INTERVAL=5
HUB_AGENT_PROVIDER_ID=1

# Connector 路径（机器相关，必须）
HUB_CONNECTOR_DIR=D:\Hubstudio

# 以下可选 —— 登录后会自动从 DB 拉取，以 DB 为准
# HUB_APP_ID=202606221518550970882191360
# HUB_APP_SECRET=your_secret_here
# HUB_GROUP_CODE=15220939
```

---

## 运行行为

- 启动后自动登录后端，获取 JWT Token
- **登录后立即从服务端拉取 Provider 配置**（DB > .env），服务端不可达时降级
- 每 `POLL_INTERVAL` 秒轮询后端领取待执行任务
- 支持的任务类型：`create_env`、`create_account`、`update_env`、`wp_login`、`gmc_check`
- 每 `HEARTBEAT_INTERVAL` 秒向后端发送心跳
- 网络异常时自动指数退避重连
- Token 过期自动刷新
- Ctrl+C 优雅关闭（关闭所有浏览器窗口）

## 依赖

Agent 仅依赖 `requests` 和 `python-dotenv`，不引入 FastAPI / Tortoise 等服务端组件。`DrissionPage` 为可选依赖，仅在 `wp_login` / `gmc_check` 任务类型中按需加载。
