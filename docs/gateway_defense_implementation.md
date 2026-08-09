# 网关防御功能实现文档

## 📋 功能概述

网关防御功能为站点提供统一的安全防护能力：
- **Shopify 平台**：使用 Cloudflare Worker 部署防御层
- **WordPress 平台**：使用 Nginx + OpenResty Lua 部署防御层

## 🏗️ 架构设计

### 1. 目录结构

```
e:\Python\vue-fastapi-admin-main\
├── app/
│   ├── services/
│   │   ├── gateway_defense/          # 网关防御服务层（新增）
│   │   │   ├── __init__.py
│   │   │   ├── base.py               # 基础服务抽象类
│   │   │   ├── cloudflare_worker.py  # CF Worker 部署服务
│   │   │   └── nginx_lua.py          # Nginx Lua 部署服务
│   │   └── defense_file/             # 防御适配器源文件（已存在）
│   │       ├── cf_worker/
│   │       │   └── worker.js         # Cloudflare Worker 源码
│   │       └── nginx_lua/
│   │           └── defense.lua       # Nginx Lua 源码
│   ├── controllers/
│   │   └── site_pipeline.py          # 新增网关防御控制器方法
│   ├── api/v1/site_pipeline/
│   │   └── site_pipeline.py          # 新增网关防御 API 路由
│   ├── schemas/
│   │   └── gateway_defense.py        # 网关防御 Schema 定义（新增）
│   └── models/
│       └── site_pipeline.py          # Site 模型（需手动添加字段）
├── migrations/models/
│   └── 4_20260809000000_gateway_defense.py  # 数据库迁移文件（新增）
├── cloudflare_worker_deployer.py     # CF Worker 部署脚本（复用）
└── nginx_template_migrator.py        # Nginx Lua 部署脚本（复用）
```

### 2. 数据库设计

新增字段（迁移文件：`migrations/models/4_20260809000000_gateway_defense.py`）：

```sql
ALTER TABLE `site_pipeline_site` 
ADD COLUMN `gateway_defense_status` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '网关防御状态',
ADD COLUMN `gateway_defense_type` VARCHAR(32) NOT NULL DEFAULT '' COMMENT '网关防御类型: worker / nginx_lua',
ADD COLUMN `gateway_site_key` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '网关站点密钥 (site_xxxxxxxx)',
ADD COLUMN `gateway_site_secret` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '网关签名密钥',
ADD COLUMN `gateway_deployed_at` DATETIME(6) NULL COMMENT '网关部署时间',
ADD COLUMN `gateway_config_json` TEXT NOT NULL DEFAULT '{}' COMMENT '网关配置(JSON)',
ADD COLUMN `gateway_last_error` TEXT NOT NULL DEFAULT '' COMMENT '最后错误信息',
ADD INDEX `idx_gateway_defense_status` (`gateway_defense_status`);
```

**注意**：还需要手动在 `app/models/site_pipeline.py` 的 `Site` 模型中添加对应的 Tortoise ORM 字段定义。

## 📡 API 接口

### 单站点操作

#### 1. 部署网关防御
```http
POST /api/v1/site-pipeline/site/{site_id}/gateway-defense
```

**请求体**：
```json
{
  "gateway_url": "https://gateway.foxfingerlab.com",
  "site_key": "site_xxxxxxxx",        // 可选，不提供则自动生成
  "site_secret": "your_secret_here",  // 可选，不提供则自动生成
  "fail_mode": "open",                // open / closed
  "sdk_inject": true                  // 是否注入 SDK
}
```

#### 2. 获取网关凭证
```http
GET /api/v1/site-pipeline/site/{site_id}/gateway-credentials
```

**响应**：
```json
{
  "site_id": 123,
  "domain": "example.com",
  "gateway_site_key": "site_xxxxxxxx",
  "gateway_site_secret": "secret_here",
  "gateway_defense_status": "deployed",
  "gateway_defense_type": "worker",
  "gateway_deployed_at": "2026-08-09T10:30:00",
  "gateway_config": {...}
}
```

#### 3. 获取 Provider 信息
```http
GET /api/v1/site-pipeline/site/{site_id}/gateway-provider-info
```

#### 4. 更新网关防御配置
```http
POST /api/v1/site-pipeline/site/{site_id}/gateway-defense/update
```

### 批量操作

#### 批量部署网关防御
```http
POST /api/v1/site-pipeline/site/batch-gateway-defense
```

**请求体**：
```json
{
  "site_ids": [1, 2, 3],
  "gateway_url": "https://gateway.foxfingerlab.com",
  "site_key": "site_unified",          // 可选，统一密钥
  "site_secret": "unified_secret",     // 可选，统一密钥
  "credentials_map": {                 // 可选，每站点独立密钥
    "1": {
      "site_key": "site_aaa",
      "site_secret": "secret_aaa"
    },
    "2": {
      "site_key": "site_bbb",
      "site_secret": "secret_bbb"
    }
  },
  "fail_mode": "open",
  "sdk_inject": true
}
```

## 🔧 核心实现逻辑

### Cloudflare Worker 部署流程

1. **验证源文件**：检查 `app/services/defense_file/cf_worker/worker.js` 存在
2. **处理密钥**：外部提供 > 已保存 > 自动生成
3. **获取 Provider 配置**：从站点绑定的 Cloudflare Provider 获取 `api_token` 和 `account_id`
4. **获取 Zone ID**：通过 CloudflareService 查询域名的 Zone
5. **调用部署脚本**：执行 `cloudflare_worker_deployer.py`，传入以下参数：
   - `--api-token`：Cloudflare API Token
   - `--account-id`：Cloudflare Account ID
   - `--script-name`：`fangyu-defense-{site_id}`
   - `--script-path`：`app/services/defense_file/cf_worker/worker.js`
   - `--gateway-url`：网关地址
   - `--site-key`：站点密钥
   - `--site-secret`：站点签名密钥
   - `--zone-id`：Zone ID
   - `--route-pattern`：`{domain}/*`
   - `--fail-mode`：`open` / `closed`
6. **更新站点状态**：保存部署状态、配置信息到数据库

### Nginx Lua 部署流程

1. **验证源文件**：检查 `app/services/defense_file/nginx_lua/defense.lua` 存在
2. **处理密钥**：外部提供 > 已保存 > 自动生成
3. **获取 Provider 配置**：从站点绑定的 1Panel Provider 获取 `url` 和 `api_key`
4. **调用部署脚本**：执行 `nginx_template_migrator.py` 的 `install_main` 函数，内部会：
   - 查找 OpenResty 容器
   - 检查 Lua 依赖
   - 配置 `nginx.conf` 中的 Lua 模块
   - 配置 DNS resolver
   - 部署 Real-IP 配置文件 (`fangyu_real_ip.conf`)
   - 上传 `defense.lua` 到 `/www/sites/{domain}/lua/`
   - 更新站点 Nginx 配置（注入变量、`access_by_lua_file`、`body_filter_by_lua_block`）
   - 测试 Nginx 配置语法
   - 运行完整的安装验证测试
5. **更新站点状态**：保存部署状态、配置信息到数据库

## 🔑 密钥管理

### 三种密钥获取模式

1. **外部提供**：API 请求中同时提供 `site_key` 和 `site_secret`
2. **使用已保存**：站点已有密钥（`gateway_site_key` 和 `gateway_site_secret` 不为空）
3. **自动生成**：
   - `site_key` 格式：`site_{8位十六进制}`
   - `site_secret` 格式：`48位十六进制`（24字节）

### 批量操作密钥模式

- **统一密钥**：所有站点使用相同的 `site_key` 和 `site_secret`
- **独立密钥**：通过 `credentials_map` 为每个站点指定不同密钥
- **混合模式**：`credentials_map` 中有的站点使用独立密钥，其他使用统一密钥或自动生成

## 🎯 Provider 绑定机制

### 自动选择 Provider

- **Shopify 站点**：自动查找绑定的 `cloudflare` Provider
- **WordPress 站点**：自动查找绑定的 `onepanel` Provider

### Provider 查找顺序

1. 查找站点绑定的 Provider（`ResourceProviderBinding`，`bind_type='preferred'`）
2. 如果没有绑定，使用该类型的默认 Provider（`ConfigProvider.is_default=True`）
3. 如果都没有，返回错误

### 配置追溯

部署成功后，`gateway_config_json` 中会记录使用的 `provider_id` 和 `provider_type`，便于追溯。

## ⚠️ 注意事项

### 1. 模型字段需要手动添加

迁移文件只修改数据库表结构，需要手动在 `app/models/site_pipeline.py` 的 `Site` 模型中添加字段定义：

```python
class Site(BaseModel):
    # ... 现有字段 ...
    
    gateway_defense_status = fields.CharField(max_length=64, default='', description='网关防御状态')
    gateway_defense_type = fields.CharField(max_length=32, default='', description='网关防御类型: worker / nginx_lua')
    gateway_site_key = fields.CharField(max_length=255, default='', description='网关站点密钥')
    gateway_site_secret = fields.CharField(max_length=255, default='', description='网关签名密钥')
    gateway_deployed_at = fields.DatetimeField(null=True, description='网关部署时间')
    gateway_config_json = fields.TextField(default='{}', description='网关配置(JSON)')
    gateway_last_error = fields.TextField(default='', description='最后错误信息')
```

### 2. 执行数据库迁移

```bash
# 生成迁移（如果需要）
aerich migrate

# 应用迁移
aerich upgrade
```

### 3. Cloudflare Worker 卸载逻辑

当前实现中，卸载操作只删除路由绑定，不删除 Worker 脚本本身（因为删除脚本会影响所有使用它的站点）。

### 4. 依赖检查

- `cloudflare_worker_deployer.py` 需要能够正常执行
- `nginx_template_migrator.py` 需要能够正常执行
- Worker 源文件 `app/services/defense_file/cf_worker/worker.js` 必须存在
- Lua 源文件 `app/services/defense_file/nginx_lua/defense.lua` 必须存在

## 🚀 使用示例

### 单站点部署（自动生成密钥）

```python
# API 调用
POST /api/v1/site-pipeline/site/123/gateway-defense
{
  "gateway_url": "https://gateway.foxfingerlab.com",
  "fail_mode": "open",
  "sdk_inject": true
}
```

### 单站点部署（外部提供密钥）

```python
POST /api/v1/site-pipeline/site/123/gateway-defense
{
  "gateway_url": "https://gateway.foxfingerlab.com",
  "site_key": "site_abc12345",
  "site_secret": "your_secret_here_48_chars_long",
  "fail_mode": "open",
  "sdk_inject": true
}
```

### 批量部署（统一密钥）

```python
POST /api/v1/site-pipeline/site/batch-gateway-defense
{
  "site_ids": [1, 2, 3, 4, 5],
  "gateway_url": "https://gateway.foxfingerlab.com",
  "site_key": "site_unified",
  "site_secret": "unified_secret_here",
  "fail_mode": "open",
  "sdk_inject": true
}
```

### 批量部署（每站点独立密钥）

```python
POST /api/v1/site-pipeline/site/batch-gateway-defense
{
  "site_ids": [1, 2, 3],
  "gateway_url": "https://gateway.foxfingerlab.com",
  "credentials_map": {
    "1": {"site_key": "site_aaa", "site_secret": "secret_aaa"},
    "2": {"site_key": "site_bbb", "site_secret": "secret_bbb"},
    "3": {"site_key": "site_ccc", "site_secret": "secret_ccc"}
  },
  "fail_mode": "open",
  "sdk_inject": true
}
```

## 📊 状态说明

### gateway_defense_status 字段值

- `''`（空字符串）：未部署
- `'deployed'`：已部署成功
- `'failed'`：部署失败
- `'undeployed'`：已卸载

### gateway_defense_type 字段值

- `'worker'`：Cloudflare Worker（Shopify 平台）
- `'nginx_lua'`：Nginx + Lua（WordPress 平台）

## ✅ 已完成的工作

1. ✅ 创建数据库迁移文件
2. ✅ 创建 `gateway_defense` 服务层目录结构和基础文件
3. ✅ 实现 Cloudflare Worker 部署服务（严格按照 `cloudflare_worker_deployer.py` 逻辑）
4. ✅ 实现 Nginx Lua 部署服务（严格按照 `nginx_template_migrator.py` 逻辑）
5. ✅ 创建控制器层方法
6. ✅ 创建 API 路由（单站点 + 批量操作）
7. ✅ 创建 Schema 定义

## 🔜 待完成的工作

1. ⏳ 在 `app/models/site_pipeline.py` 中手动添加模型字段定义
2. ⏳ 执行数据库迁移 `aerich upgrade`
3. ⏳ 前端页面开发（站点列表显示网关防御状态、操作按钮等）
4. ⏳ 实现 Worker 路由删除逻辑（卸载功能完善）
5. ⏳ 实现 Nginx 配置清理逻辑（卸载功能完善）
6. ⏳ 完善错误处理和日志记录
7. ⏳ 编写单元测试

## 📝 代码规范遵循

- ✅ 遵循项目 FastAPI + Vue 后台规范
- ✅ 服务层完全复用现有部署脚本（`cloudflare_worker_deployer.py` 和 `nginx_template_migrator.py`）
- ✅ 使用项目已有的 Provider 绑定机制（`ResourceProviderBinding`）
- ✅ 控制器层只做业务编排，核心逻辑在服务层
- ✅ API 层只做路由注册和参数校验
- ✅ 所有敏感配置从 Provider 读取，不硬编码
- ✅ 完整的日志记录（写入 `site.pipeline_log`）
- ✅ 权限系统接入（API 路由会自动应用 RBAC）
