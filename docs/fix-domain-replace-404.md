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

### 技术细节：Docker Volume 映射

1Panel WordPress 使用 Docker 容器部署，架构如下：

```
┌─────────────────────────────────────────────────────────────┐
│ Nginx (宿主机)                                               │
│ - 配置: /opt/1panel/www/conf.d/{service_name}.conf         │
│ - 反向代理到: http://127.0.0.1:36990                        │
└─────────────────────────────────────────────────────────────┘
                         ↓ proxy_pass
┌─────────────────────────────────────────────────────────────┐
│ WordPress 容器                                               │
│ - 端口: 36990                                                │
│ - 容器内路径: /usr/share/nginx/html                         │
│ - Docker Volume 映射:                                        │
│   /opt/1panel/apps/wordpress/{service}/data                 │
│   → /usr/share/nginx/html                                   │
└─────────────────────────────────────────────────────────────┘
```

**当 service_name 不同步时**：
```
脚本写入   → /opt/1panel/apps/wordpress/...1786463503656/data/domain-replace.php
Docker 映射 → /opt/1panel/apps/wordpress/...1786464583871/data/ → 容器内
容器访问   → /usr/share/nginx/html/domain-replace.php ❌ 找不到！
HTTP 请求  → 404 Not Found ❌
```

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
