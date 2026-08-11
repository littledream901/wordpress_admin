# 修复：WordPress 域名替换脚本 404 错误

## 问题描述

在 WordPress 站点建站流程中，`domain-replace.php` 脚本返回 404 错误，导致域名替换失败。

### 错误日志

```
2026-08-12 00:10:13.491 | INFO | domain-replace.php 已写入 /opt/1panel/apps/wordpress/qciqcgsi-shop-038745-1786463503656/data/domain-replace.php
2026-08-12 00:10:15.503 | ERROR | WordPress domain replace 失败: HTTP 404：domain-replace.php 不可访问 (qciqcgsi.shop)
```

### 实际诊断结果

通过服务器实际检查发现：
```bash
# 脚本写入到了旧的 service_name 目录
/opt/1panel/apps/wordpress/qciqcgsi-shop-038745-1786463503656/data/domain-replace.php

# 但 Nginx 配置指向新的 service_name（rebuild 后生成）
/opt/1panel/www/conf.d/qciqcgsi-shop-038745-1786464583871.conf

# 查找脚本 → 空（因为写入到了错误的目录）
find /opt/1panel/apps/wordpress -name "domain-replace.php"
```

## 根本原因

**rebuild_app 之后，容器的 service_name 会变化（时间戳更新），但代码中的 service_name 变量没有同步更新！**

### 问题流程

1. `create_site` → `service_name = "qciqcgsi-shop-038745-1786463503656"`
2. `restore_files` → 文件恢复到旧 service_name 目录
3. **`rebuild_app`** → 容器重建，新 `service_name = "qciqcgsi-shop-038745-1786464583871"`
   - ⚠️ 但代码中的 `service_name` 变量没有更新
4. `inject_domain_replace_script` → 使用**旧** service_name 写入脚本到错误目录 ❌
5. Nginx 已经指向**新** service_name → 404 错误 ❌

## 修复方案

### 核心修复：rebuild_app 返回最新的 service_name

#### 1. 修改 `site_manager.rebuild_app()` 方法

**文件**：`app/services/onepanel/site_manager.py`

**变更**：
- 返回值从 `bool` 改为 `dict[str, Any]`
- 返回结构：`{'success': bool, 'service_name': str, 'app_info': dict | None}`
- 从 1Panel API 响应中提取最新的 `serviceName` 或 `name` 字段

```python
def rebuild_app(self, app_id: int, wait: int = 60, service_name: str = '', domain: str = '') -> dict[str, Any]:
    """重建应用容器（文件变更后需要重建才能生效），返回应用信息（包含最新的 service_name）。"""
    ok, msg = self.api.post('/apps/installed/op', {'installId': app_id, 'operate': 'rebuild', 'taskID': str(uuid.uuid4())})
    if not ok:
        _log.warning("rebuild_app API 调用失败：%s", msg)

    if service_name and domain:
        app_info = self._wait_app_running(service_name, domain, timeout=wait)
        if app_info:
            new_service_name = str(app_info.get('serviceName') or app_info.get('name') or service_name)
            _log.info("rebuild 完成，service_name: %s → %s", service_name, new_service_name)
            return {'success': True, 'service_name': new_service_name, 'app_info': app_info}
        return {'success': False, 'service_name': service_name, 'app_info': None}

    time.sleep(wait)
    return {'success': bool(ok), 'service_name': service_name, 'app_info': None}
```

#### 2. 更新 `provision.py` 调用逻辑

**文件**：`app/services/tasks/provision.py`

**变更**：
- 接收 `rebuild_app` 的返回值
- 检查 `service_name` 是否变化
- 如果变化，更新局部变量和数据库记录

```python
# Step 5: rebuild_after_files (第一次 rebuild)
rebuild_result = await self._exec(lambda: site_manager.rebuild_app(app_id, service_name=service_name, domain=site.domain), timeout=180)

# ⚠️ 重要：rebuild 可能会生成新的 service_name，必须更新
if rebuild_result and isinstance(rebuild_result, dict):
    new_service_name = rebuild_result.get('service_name', service_name)
    if new_service_name != service_name:
        _log.warning("rebuild 后 service_name 已变更: %s → %s", service_name, new_service_name)
        service_name = new_service_name
        site.onepanel_service_name = new_service_name
        await site.save()

# Step 9: rebuild_after_patch (第二次 rebuild)
rebuild_result2 = await self._exec(lambda: site_manager.rebuild_app(app_id, service_name=service_name, domain=site.domain), timeout=180)

# ⚠️ 重要：第二次 rebuild 也可能改变 service_name
if rebuild_result2 and isinstance(rebuild_result2, dict):
    new_service_name = rebuild_result2.get('service_name', service_name)
    if new_service_name != service_name:
        _log.warning("第二次 rebuild 后 service_name 已变更: %s → %s", service_name, new_service_name)
        service_name = new_service_name
        site.onepanel_service_name = new_service_name
        await site.save()
```

### 附加改进：智能路径解析（兼容性保障）

虽然主要问题是 service_name 不同步，但我们仍保留了智能路径解析逻辑，以应对未来可能的目录结构变化。

**文件**：`app/services/onepanel/wp_restorer.py`

- 新增 `_resolve_target_dir()` 方法：三级降级策略
  1. 优先使用 1Panel API 返回的 `siteDir`
  2. 在候选路径中查找 `wp-config.php` 所在目录
  3. 最后降级使用默认 `data` 目录

## 修复效果

### 修复前
```
脚本写入 → /opt/1panel/apps/wordpress/.../1786463503656/data/domain-replace.php
Nginx 指向 → qciqcgsi-shop-038745-1786464583871（不存在）
结果 → 404 错误 ❌
```

### 修复后
```
rebuild_app → 返回新 service_name: 1786464583871
更新变量 → service_name = "1786464583871"
脚本写入 → /opt/1panel/apps/wordpress/.../1786464583871/data/domain-replace.php
Nginx 指向 → qciqcgsi-shop-038745-1786464583871
结果 → 脚本正常访问 ✅
```

## 影响范围

### 修改的文件

1. **app/services/onepanel/site_manager.py**
   - `rebuild_app()` 方法：返回值从 `bool` 改为 `dict[str, Any]`
   - 从 1Panel API 响应中提取最新的 `service_name`

2. **app/services/tasks/provision.py**
   - 两处 `rebuild_app` 调用后检查并更新 `service_name`
   - 同步更新 `site.onepanel_service_name` 到数据库

3. **app/services/onepanel/wp_restorer.py**（附加改进）
   - 新增 `_resolve_target_dir()` 智能路径解析
   - 获取并传递 `site_root` 参数

4. **docs/fix-domain-replace-404.md**
   - 详细的修复文档

### 向后兼容性

- ✅ 如果 `service_name` 没有变化，代码逻辑不受影响
- ✅ 如果 1Panel API 未返回新 service_name，会使用原值
- ✅ 智能路径解析提供降级策略，确保健壮性

## 测试验证

### 预期行为

1. **正常情况**（service_name 未变化）
   - `rebuild_app` 返回原 service_name
   - 日志：无警告
   - 脚本正常写入和访问

2. **service_name 变化**（rebuild 后时间戳更新）
   - `rebuild_app` 返回新 service_name
   - 日志：`rebuild 后 service_name 已变更: xxx → yyy`
   - 自动更新变量和数据库
   - 脚本写入到正确目录

### 手动验证命令

```bash
# 1. 查看建站日志，确认 service_name 是否有变化
grep "service_name" /path/to/log

# 2. 检查脚本是否写入到正确目录
find /opt/1panel/apps/wordpress -name "domain-replace.php"

# 3. 验证 Nginx 配置和脚本路径一致
ls -la /opt/1panel/www/conf.d/*.conf
cat /opt/1panel/www/conf.d/{site}.conf | grep root
```

## 总结

这次修复解决了核心问题：**rebuild_app 后 service_name 不同步导致脚本写入到错误目录**。

关键改进：
1. ✅ `rebuild_app` 返回最新的 `service_name`
2. ✅ `provision.py` 自动检测并更新 `service_name`
3. ✅ 同步更新数据库记录
4. ✅ 智能路径解析提供兜底保障
5. ✅ 详细的日志记录便于排查

下次建站时，系统会自动使用正确的 service_name，避免 404 错误。

## 问题 3: WooCommerce 类加载失败（2026-08-12 01:16）

### 现象
```json
{
  "woo_in_active_plugins": true,        // ✅ 已在激活列表
  "woo_class_exists": false,            // ❌ 类不存在
  "woo_function_exists": false,         // ❌ 函数不存在
  "woo_main_file": "/var/www/html/wp-content/plugins/woocommerce/woocommerce.php"
}
```

错误：`WordPress get woo key 失败: 业务返回失败: WooCommerce class/function not loaded in current bootstrap context`

### 根本原因

**第二次 rebuild 导致 WooCommerce 插件文件丢失。**

建站流程：
1. Step 3-4: 恢复数据库 + 文件（并行）✅
2. Step 5: 第一次 rebuild ✅
3. Step 6: 域名替换 ✅
4. Step 7-8: 注入 woo/ctx 脚本 ✅
5. **Step 9: 第二次 rebuild** ⚠️ **容器重建，插件文件丢失**
6. Step 10: 获取 WooCommerce Key ❌ **文件不存在，类无法加载**

日志证据：
```
rebuild 后 service_name 已变更: qciqcgsi-shop-038745-1786468430537 → qciqcgsi-shop-038745-1786463503656
```

service_name 变更说明容器被重建，可能回滚到了初始状态，导致：
- ✅ 数据库中 `active_plugins` 仍包含 WooCommerce（数据持久化）
- ❌ 插件文件丢失（容器重建）
- ❌ PHP 无法加载 WooCommerce 类

### 修复方案

在获取 WooCommerce Key 之前，检查插件文件是否存在，如果不存在则重新恢复文件。

#### 1. 添加文件检查方法

**文件：** `app/services/onepanel/wp_restorer.py`

```python
def check_woo_file_exists(self, service_name: str) -> bool:
    """检查 WooCommerce 主文件是否存在（用于检测 rebuild 后文件是否丢失）"""
    data_dir = self._data_root(service_name)
    woo_main = f'{data_dir}/wp-content/plugins/woocommerce/woocommerce.php'
    exists = self.file_manager.exists(woo_main)
    _log.info("检查 WooCommerce 文件: %s -> %s", woo_main, "存在" if exists else "不存在")
    return exists
```

#### 2. 在建站流程中添加检查和恢复逻辑

**文件：** `app/services/tasks/provision.py`

```python
# Step 10: fetch_woo_keys（对齐单脚本：rebuild 后获取 WooCommerce Key）
# ⚠️ 重要：第二次 rebuild 可能导致插件文件丢失，先检查并恢复
await self._update_step(job, "verify_and_restore_woo")
woo_file_exists = await self._exec(
    lambda: wp_restorer.check_woo_file_exists(service_name),
    timeout=30,
)
if not woo_file_exists:
    _log.warning("第二次 rebuild 后 WooCommerce 文件丢失，重新恢复文件")
    await self._exec(lambda: wp_restorer.restore_files(service_name), timeout=300)
    # 恢复后需要再次 rebuild
    await self._exec(lambda: site_manager.rebuild_app(app_id, service_name=service_name, domain=site.domain), timeout=180)

await self._update_step(job, "fetch_woo_keys")
woo_ck, woo_cs = await self._exec(
    lambda: wp_restorer.fetch_woo_keys(site.domain, woo_token, protocol),
    timeout=45,
)
```

#### 3. 增强 PHP 脚本诊断信息

**文件：** `app/services/onepanel/php_client.py`

```python
class PHPClientResponseError(PHPClientError):
    """PHP 业务逻辑返回失败"""
    def __init__(self, message: str = "", response_data: dict | None = None):
        super().__init__(message)
        self.response_data = response_data or {}
```

**文件：** `app/services/onepanel/wp_restorer.py`

```python
except PHPClientResponseError as e:
    msg = str(e)
    if e.response_data:
        import json
        _log.error("WooCommerce Key 生成失败，错误详情: %s", msg)
        _log.error("PHP 诊断信息: %s", json.dumps(e.response_data, indent=2, ensure_ascii=False))
    else:
        _log.error("WooCommerce Key 生成失败（无诊断信息）: %s", msg)
    raise WordPressOperationError("get woo key", detail=msg)
```

### 修复效果

**修复前：**
```
第二次 rebuild → 插件文件丢失 → WooCommerce 类加载失败 → 建站失败 ❌
```

**修复后：**
```
第二次 rebuild → 检查文件 → 发现丢失 → 重新恢复文件 → 再次 rebuild → WooCommerce 类加载成功 → 建站成功 ✅
```

### 相关文件

- `app/services/tasks/provision.py:273-285` - 添加验证和恢复逻辑
- `app/services/onepanel/wp_restorer.py:282-290` - 添加文件检查方法
- `app/services/onepanel/php_client.py:49-55` - 增强异常类
- `app/services/onepanel/php_client.py:242-252` - 传递诊断数据
- `app/services/onepanel/wp_restorer.py:715-727` - 记录完整诊断信息

---

## 2026-08-12 补充修复：过滤无效的 site_root

### 新问题

在实际运行中发现，`get_site_root()` 可能返回 `/`（根目录），这是 1Panel API 返回的 Nginx root，但不是 WordPress 的实际安装路径。

**错误日志：**
```
2026-08-12 00:44:11.986 | INFO | 站点 qciqcgsi.shop (id=6) Nginx root: / 
2026-08-12 00:44:11.988 | INFO | 使用指定的目标目录: 
2026-08-12 00:44:12.250 | INFO | domain-replace.php 已写入 /domain-replace.php 
2026-08-12 00:44:14.237 | ERROR | WordPress domain replace 失败: HTTP 404
```

脚本被写入到 `/domain-replace.php`（系统根目录），而不是 WordPress 的安装目录。

### 修复方案

#### 1. 在 `_extract_site_dir` 中过滤无效路径

**文件：** [site_manager.py](file:///e:/Python/vue-fastapi-admin-main/app/services/onepanel/site_manager.py#L66-L88)

```python
@staticmethod
def _extract_site_dir(item: dict) -> Optional[str]:
    """从 1Panel 返回的网站 item 中提取 document root"""
    site_dir = (
        item.get('siteDir')
        or item.get('site_dir')
        or item.get('SiteDir')
        or item.get('path')
        or item.get('rootDir')
        or item.get('websiteDir')
        or ''
    )
    if not site_dir:
        return None
    
    site_dir_str = str(site_dir).strip()
    
    # 过滤无效路径：单个 / 或空路径不是有效的 WordPress document root
    if not site_dir_str or site_dir_str == '/':
        return None
        
    return site_dir_str
```

#### 2. 在 `_resolve_target_dir` 中验证路径有效性

**文件：** [wp_restorer.py](file:///e:/Python/vue-fastapi-admin-main/app/services/onepanel/wp_restorer.py#L101-L127)

```python
def _resolve_target_dir(self, service_name: str, target_dir: str = "") -> str:
    if target_dir:
        resolved = target_dir.rstrip('/')
        # 验证目录是否真的包含 WordPress（检查 wp-config.php）
        wp_config_path = f'{resolved}/wp-config.php'
        if self.file_manager and self.file_manager.exists(wp_config_path):
            _log.info("使用指定的目标目录: %s", resolved)
            return resolved
        else:
            _log.warning(
                "指定的目标目录 %s 不包含 wp-config.php，将使用智能查找",
                resolved
            )
    
    # 智能查找：在候选路径中找到 wp-config.php 所在目录
    # ...
```

### 修复效果

**修复前：**
```
get_site_root() → "/" 
_resolve_target_dir() → "/" (无验证)
脚本写入 → /domain-replace.php ❌
HTTP 访问 → 404 ❌
```

**修复后：**
```
get_site_root() → None (过滤掉 "/")
_resolve_target_dir() → 智能查找 wp-config.php
脚本写入 → /opt/1panel/apps/wordpress/.../data/domain-replace.php ✅
HTTP 访问 → 200 OK ✅
```

### 关键改进

1. ✅ `_extract_site_dir` 过滤无效路径（`/`、空字符串）
2. ✅ `_resolve_target_dir` 验证路径是否包含 `wp-config.php`
3. ✅ 当 API 返回值无效时，自动降级到智能查找
4. ✅ 详细的警告日志便于诊断

### 测试验证

```bash
# 检查 1Panel API 返回的 siteDir
curl -H "Authorization: Bearer $TOKEN" http://localhost:9999/api/v1/websites/6

# 确认脚本写入到正确位置
find /opt/1panel/apps/wordpress -name "domain-replace.php"

# 验证智能查找日志
grep "_resolve_target_dir\|wp-config.php" /var/log/app.log
```
