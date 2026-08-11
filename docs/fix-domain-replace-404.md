# 修复：WordPress 域名替换脚本 404 错误

## 问题描述

在 WordPress 站点建站流程中，域名替换步骤失败，错误信息：

```
HTTP 404：domain-replace.php 不可访问 (qciqcgsi.shop)
```

## 根本原因

1. **路径不匹配**：`domain-replace.php` 脚本被写入到 `/opt/1panel/apps/wordpress/{service_name}/data/` 目录
2. **Nginx 配置差异**：1Panel WordPress 站点的实际 Nginx document root 可能是 `data/wordpress/` 或其他子目录
3. **缺少验证**：代码写入文件后没有检查实际的 Nginx root 配置，导致脚本无法通过 HTTP 访问

## 修复方案

### 1. 获取实际的 Nginx document root

在 `provision.py` 中，域名替换前先获取站点的实际 document root：

```python
# 获取实际的 Nginx document root
site_root = await self._exec(
    lambda: site_manager.get_site_root(site.domain, onepanel_site_id),
    timeout=30,
)
```

### 2. 智能路径解析

新增 `_resolve_target_dir` 方法，实现三级降级策略：

1. **优先级 1**：使用从 1Panel API 获取的 Nginx document root（`siteDir`）
2. **优先级 2**：在候选路径中查找 `wp-config.php` 所在目录：
   - `/opt/1panel/apps/wordpress/{service}/data`
   - `/opt/1panel/apps/wordpress/{service}/data/wordpress`
   - `/opt/1panel/apps/wordpress/{service}/data/public`
   - `/opt/1panel/apps/wordpress/{service}/data/public_html`
   - `/opt/1panel/apps/wordpress/{service}/data/htdocs`
3. **优先级 3**：降级使用默认 `data` 目录

### 3. 统一所有 PHP 脚本注入逻辑

所有 PHP 脚本注入方法统一使用 `_resolve_target_dir`：

- `inject_domain_replace_script` - 域名替换脚本
- `inject_woo_script` - WooCommerce API Key 生成脚本
- `inject_ctx_script` - CTX Feed 刷新脚本
- `remove_domain_replace_script` - 清理域名替换脚本
- `remove_woo_script` - 清理 Woo 脚本
- `remove_ctx_script` - 清理 CTX 脚本

### 4. 改进错误提示

当遇到 404 错误时，提供更详细的诊断信息：

```
HTTP 404：domain-replace.php 不可访问 ({domain})。
可能原因：脚本写入目录与 Nginx document root 不一致。
排查步骤：
1) 检查 1Panel 网站配置中的实际 siteDir/document root；
2) 确认域名 DNS 已正确指向该站点；
3) 检查 Nginx 配置是否已 reload；
4) 尝试手动访问 http(s)://{domain}/domain-replace.php?token={token} 查看响应。
```

## 修改文件清单

### 核心修改

1. **app/services/tasks/provision.py**
   - 域名替换前获取 `site_root`
   - 将 `site_root` 传递给 `inject_domain_replace_script`

2. **app/services/onepanel/wp_restorer.py**
   - 新增 `_get_candidate_roots()` - 获取候选根目录列表
   - 新增 `_resolve_target_dir()` - 智能解析目标目录
   - 更新 `inject_domain_replace_script()` - 使用智能路径解析
   - 更新 `inject_woo_script()` - 使用智能路径解析
   - 更新 `inject_ctx_script()` - 使用智能路径解析
   - 更新所有 `remove_*_script()` 方法 - 使用统一路径解析
   - 改进 404 错误提示信息

## 测试建议

1. **正常场景测试**：
   - 验证能从 1Panel API 正确获取 `siteDir`
   - 确认脚本写入到正确的 document root
   - 验证 HTTP 访问成功

2. **降级场景测试**：
   - 模拟 1Panel API 无法返回 `siteDir`
   - 验证智能查找 `wp-config.php` 逻辑
   - 确认降级到默认目录

3. **错误场景测试**：
   - 验证 404 错误时的诊断信息是否清晰
   - 确认日志中包含路径解析过程

## 日志示例

### 成功场景
```
INFO: 使用指定的目标目录: /opt/1panel/apps/wordpress/example-com/data/wordpress
INFO: domain-replace.php 已写入 /opt/1panel/apps/wordpress/example-com/data/wordpress/domain-replace.php
```

### 智能查找场景
```
INFO: 找到 wp-config.php，使用目录: /opt/1panel/apps/wordpress/example-com/data/wordpress
```

### 降级场景
```
WARNING: 未找到 wp-config.php，降级使用默认 data 目录: /opt/1panel/apps/wordpress/example-com/data
```

## 后续优化建议

1. **缓存 document root**：避免每次都调用 1Panel API 查询
2. **验证脚本可访问性**：写入后立即通过 HTTP HEAD 请求验证
3. **支持自定义候选路径**：通过环境变量配置额外的候选路径
4. **监控告警**：当频繁使用降级方案时发出告警

## 相关问题

- 解决了日志中的 "domain-replace.php 不可访问" 错误
- 提升了建站流程的健壮性
- 改进了错误诊断能力
