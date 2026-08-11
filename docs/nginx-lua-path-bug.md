# Nginx Lua 模块路径错误 - 严重 Bug

## 🚨 问题描述

`nginx_lua.py` 模块中所有文件路径都使用了 **domain**，但实际应该使用 **service_name**！

### 错误路径示例

```python
# 当前代码（错误）
target_dir = f"/www/sites/{domain}/lua"  # domain = "qciqcgsi.shop"
# 生成路径：/www/sites/qciqcgsi.shop/lua/defense.lua

# 实际路径（正确）
target_dir = f"/www/sites/{service_name}/lua"  # service_name = "qciqcgsi-shop-038745-1786472355632"
# 应该是：/www/sites/qciqcgsi-shop-038745-1786472355632/lua/defense.lua
```

### 实际测试证据

从测试日志可以看到真实路径：

```
找到 wp-config.php，使用目录: /opt/1panel/apps/wordpress/qciqcgsi-shop-038745-1786472355632/data
```

站点目录结构：
```
/opt/1panel/apps/wordpress/
└── qciqcgsi-shop-038745-1786472355632/    ← service_name (不是 domain!)
    ├── data/                               ← WordPress 根目录
    │   ├── wp-config.php
    │   └── ...
    └── ...
```

OpenResty 容器内映射：
```
/www/sites/
└── qciqcgsi-shop-038745-1786472355632/    ← 映射到容器内
    ├── lua/                                ← 应该在这里创建 lua 目录
    │   ├── defense.lua
    │   └── fangyu_real_ip.conf
    └── index/
```

---

## 🔍 受影响的代码位置

### 1. `_real_ip_config_path()` 函数（第 110-112 行）

```python
# ❌ 错误
def _real_ip_config_path(domain: str) -> str:
    return f"/www/sites/{domain}/lua/fangyu_real_ip.conf"

# ✅ 修复
def _real_ip_config_path(service_name: str) -> str:
    return f"/www/sites/{service_name}/lua/fangyu_real_ip.conf"
```

### 2. `_real_ip_block()` 函数（第 115-117 行）

```python
# ❌ 错误
def _real_ip_block(domain: str) -> str:
    return f"    include {_real_ip_config_path(domain)};"

# ✅ 修复
def _real_ip_block(service_name: str) -> str:
    return f"    include {_real_ip_config_path(service_name)};"
```

### 3. `_validate_nginx_config_logic()` 函数（第 142 行）

```python
# ❌ 错误
elif f'/www/sites/{domain}/lua/defense.lua' not in config_content:

# ✅ 修复
elif f'/www/sites/{service_name}/lua/defense.lua' not in config_content:
```

### 4. `_render_blocks()` 函数（第 192-232 行）

```python
# ❌ 错误
def _render_blocks(domain: str, site_id: str, ...) -> Tuple[str, str, str]:
    variables = f"""
{_real_ip_block(domain)}  # ← 错误使用 domain
    ...
    """
    access = f'''access_by_lua_file /www/sites/{domain}/lua/defense.lua;'''  # ← 错误

# ✅ 修复
def _render_blocks(service_name: str, site_id: str, ...) -> Tuple[str, str, str]:
    variables = f"""
{_real_ip_block(service_name)}  # ← 使用 service_name
    ...
    """
    access = f'''access_by_lua_file /www/sites/{service_name}/lua/defense.lua;'''  # ← 修复
```

### 5. `FangyuInstaller.deploy_real_ip_config()` 函数（第 589-606 行）

```python
# ❌ 错误
def deploy_real_ip_config(self, domain: str, container_id: str) -> bool:
    target_dir = f"/www/sites/{domain}/lua"

# ✅ 修复
def deploy_real_ip_config(self, service_name: str, container_id: str) -> bool:
    target_dir = f"/www/sites/{service_name}/lua"
```

### 6. `FangyuInstaller.deploy_defense_lua()` 函数（第 608-623 行）

```python
# ❌ 错误
def deploy_defense_lua(self, domain: str, container_id: str) -> bool:
    target_dir = f"/www/sites/{domain}/lua"

# ✅ 修复
def deploy_defense_lua(self, service_name: str, container_id: str) -> bool:
    target_dir = f"/www/sites/{service_name}/lua"
```

### 7. `FangyuInstaller.install()` 函数（第 711-786 行）

```python
# ❌ 错误 - 缺少 service_name 参数
def install(self, domain: str, site_id: str, ...) -> Dict[str, Any]:
    # 步骤3: 部署 Real-IP 配置
    if not self.deploy_real_ip_config(domain, container_id):
        return self._fail_result('Real-IP 配置部署失败', ...)
    
    # 步骤4: 部署 defense.lua
    if not self.deploy_defense_lua(domain, container_id):
        return self._fail_result('defense.lua 部署失败', ...)

# ✅ 修复 - 添加 service_name 参数并使用
def install(self, domain: str, service_name: str, site_id: str, ...) -> Dict[str, Any]:
    # 步骤3: 部署 Real-IP 配置
    if not self.deploy_real_ip_config(service_name, container_id):
        return self._fail_result('Real-IP 配置部署失败', ...)
    
    # 步骤4: 部署 defense.lua
    if not self.deploy_defense_lua(service_name, container_id):
        return self._fail_result('defense.lua 部署失败', ...)
```

### 8. `FangyuInstaller.verify_installation()` 函数（第 808-909 行）

```python
# ❌ 错误
def verify_installation(self, domain: str, container_id: str, ...) -> Dict[str, Any]:
    lua_path = f"/www/sites/{domain}/lua/defense.lua"
    real_ip_path = _real_ip_config_path(domain)
    expected_lua = f"/www/sites/{domain}/lua/defense.lua"

# ✅ 修复
def verify_installation(self, service_name: str, container_id: str, ...) -> Dict[str, Any]:
    lua_path = f"/www/sites/{service_name}/lua/defense.lua"
    real_ip_path = _real_ip_config_path(service_name)
    expected_lua = f"/www/sites/{service_name}/lua/defense.lua"
```

### 9. `NginxLuaDefenseService._install_sync()` 函数（第 1109-1122 行）

```python
# ❌ 错误 - 缺少 service_name 参数
def _install_sync(self, domain: str, site_id: str, ...) -> Dict[str, Any]:
    installer = FangyuInstaller(api_client, self.lua_source, task_log=self.task_log)
    return installer.install(domain, site_id, site_key, site_secret, gateway_url)

# ✅ 修复 - 添加 service_name 参数并传递
def _install_sync(self, domain: str, service_name: str, site_id: str, ...) -> Dict[str, Any]:
    installer = FangyuInstaller(api_client, self.lua_source, task_log=self.task_log)
    return installer.install(domain, service_name, site_id, site_key, site_secret, gateway_url)
```

### 10. `NginxLuaDefenseService.deploy()` 函数（第 1000-1108 行）

```python
# ❌ 错误 - 没有传递 service_name
async def deploy(self, site, gateway_url: str, ...) -> Dict[str, Any]:
    result = await loop.run_in_executor(
        None,
        self._install_sync,
        site.domain,  # ← 只传了 domain
        gateway_site_id,
        site_key,
        site_secret,
        gateway_url,
        panel_url,
        panel_key,
    )

# ✅ 修复 - 添加 service_name
async def deploy(self, site, gateway_url: str, ...) -> Dict[str, Any]:
    # 获取 service_name
    service_name = site.service_name or self._extract_service_name(site)
    
    result = await loop.run_in_executor(
        None,
        self._install_sync,
        site.domain,
        service_name,  # ← 添加 service_name
        gateway_site_id,
        site_key,
        site_secret,
        gateway_url,
        panel_url,
        panel_key,
    )
```

---

## 📊 如何获取 service_name

### 方式 1：从 Site 模型读取（推荐）

```python
# 假设 Site 模型有 service_name 字段
service_name = site.service_name

# 如果没有，可以从其他字段推导
# service_name 格式：{domain-with-dashes}-{random}-{timestamp}
# 例如：qciqcgsi-shop-038745-1786472355632
```

### 方式 2：从 1Panel API 查询

```python
# 通过 website_info 获取
websites = api_client.search_websites(domain)
if websites:
    website_info = websites[0]
    # 可能的字段名：
    service_name = (
        website_info.get('serviceName') or
        website_info.get('service_name') or
        website_info.get('appName') or
        website_info.get('alias')  # alias 通常就是 service_name
    )
```

### 方式 3：从 sitePath 提取

```python
# sitePath 示例：/opt/1panel/apps/wordpress/qciqcgsi-shop-038745-1786472355632
# 提取最后一段作为 service_name
import os
site_path = detail.get('sitePath')
if site_path:
    service_name = os.path.basename(site_path.rstrip('/'))
    # service_name = "qciqcgsi-shop-038745-1786472355632"
```

---

## 🔧 完整修复方案

### Step 1：确认 Site 模型是否有 service_name 字段

```bash
# 检查模型定义
grep -n "service_name" app/models/site.py
```

### Step 2：如果没有，从 1Panel API 获取

在 `update_website_config()` 中已经查询了 `website_info`，可以直接使用：

```python
def update_website_config(self, domain: str, site_id: str, ..., container_id: str) -> Tuple[bool, str]:
    # 查找站点
    websites = self.api_client.search_websites(domain)
    if not websites:
        return False, f"找不到站点: {domain}"
    website_info = websites[0]
    
    # ✅ 提取 service_name
    service_name = website_info.get('alias') or website_info.get('serviceName')
    if not service_name:
        return False, "无法获取站点 service_name"
    
    # ... 后续使用 service_name 而不是 domain
```

### Step 3：修改所有函数签名

1. 所有接受 `domain` 参数的内部函数，改为接受 `service_name`
2. 外部接口函数（如 `install()`）同时接受 `domain` 和 `service_name`
3. 路径生成统一使用 `service_name`

---

## ⚠️ 影响评估

### 严重性：高

- ✅ **当前不影响功能**：因为 nginx_lua 模块可能还没有在生产使用
- ❌ **如果使用会完全失败**：文件会上传到错误目录，导致 Nginx 无法找到 Lua 脚本

### 失败场景

1. `defense.lua` 上传到 `/www/sites/qciqcgsi.shop/lua/` ❌
2. Nginx 配置引用 `/www/sites/qciqcgsi.shop/lua/defense.lua` ❌
3. 实际文件在 `/www/sites/qciqcgsi-shop-038745-1786472355632/lua/` ✅
4. **结果**：Nginx 启动失败，报错 `lua file not found`

---

## ✅ 修复检查清单

- [ ] 修改 `_real_ip_config_path()` 参数
- [ ] 修改 `_real_ip_block()` 参数
- [ ] 修改 `_validate_nginx_config_logic()` 参数和路径检查
- [ ] 修改 `_render_blocks()` 参数和路径生成
- [ ] 修改 `deploy_real_ip_config()` 参数
- [ ] 修改 `deploy_defense_lua()` 参数
- [ ] 修改 `install()` 参数，添加 service_name
- [ ] 修改 `verify_installation()` 参数
- [ ] 修改 `_install_sync()` 参数
- [ ] 修改 `deploy()` 获取并传递 service_name
- [ ] 添加 `_extract_service_name()` 辅助方法
- [ ] 更新所有调用点
- [ ] 测试部署流程

---

## 📝 总结

**根本原因**：混淆了 domain（域名）和 service_name（1Panel 服务名）

**解决方案**：所有文件路径使用 service_name，而不是 domain

**优先级**：高（必须修复才能正常使用）

需要我帮你实施修复吗？
