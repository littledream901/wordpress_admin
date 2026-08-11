# 修复：WooCommerce Key 生成失败 - 自动激活插件

## 问题描述

在 WordPress 站点建站流程中，虽然模板站文件中包含 WooCommerce 插件，但数据库恢复后插件未处于激活状态，导致 `fetch_woo_keys` 步骤失败。

### 错误日志

```
2026-08-12 00:57:51.392 | ERROR | 建站执行失败: WordPress get woo key 失败: 业务返回失败: WooCommerce class/function not loaded in current bootstrap context

app.core.exceptions.WordPressOperationError: WordPress get woo key 失败: 业务返回失败: WooCommerce class/function not loaded in current bootstrap context
```

## 根本原因

**WooCommerce 插件文件已存在（通过 `restore_files` 恢复），但数据库中 `active_plugins` 选项未包含 WooCommerce。**

### 问题分析

1. **Step 4: restore_files** - 从模板站恢复 WordPress 文件（包含 WooCommerce 插件）
2. **Step 3: restore_db** - 从模板站恢复数据库
3. **问题**：数据库和文件可能来自不同时间点的备份，导致：
   - 文件中有 WooCommerce 插件
   - 数据库中 `wp_options.active_plugins` 未包含 `woocommerce/woocommerce.php`
4. **Step 10: fetch_woo_keys** - PHP 脚本检查 `active_plugins`，发现未激活，返回错误 ❌

### 为什么不能跳过

- WooCommerce Key 是业务必需功能（用于 API 对接、订单同步等）
- 模板站设计时已包含 WooCommerce，新站应该继承这个配置
- 跳过会导致后续业务流程（如订单处理）无法正常运行

## 修复方案

### 核心修复：PHP 脚本自动激活 WooCommerce 插件

#### 修改 `inject_woo_script()` 中的 PHP 代码

**文件：** [wp_restorer.py](file:///e:/Python/vue-fastapi-admin-main/app/services/onepanel/wp_restorer.py#L600-L610)

**变更：在检测 WooCommerce 状态时，如果插件文件存在但未激活，自动激活它**

```php
// 如果 WooCommerce 未激活但文件存在，自动激活
if (!$diag['woo_in_active_plugins'] && !empty($diag['woo_main_file']) && file_exists($diag['woo_main_file'])) {
    $active_plugins = get_option('active_plugins', []);
    if (!in_array('woocommerce/woocommerce.php', $active_plugins, true)) {
        $active_plugins[] = 'woocommerce/woocommerce.php';
        update_option('active_plugins', $active_plugins);
        $diag['woo_auto_activated'] = true;
        $diag['woo_in_active_plugins'] = true;
    }
}

// 如果 Woo 主类没加载，但插件文件存在，尝试手动加载一次
if (!$diag['woo_class_exists'] && !empty($diag['woo_main_file']) && file_exists($diag['woo_main_file'])) {
    try {
        require_once $diag['woo_main_file'];
        $diag['woo_class_exists_after_require'] = class_exists('WooCommerce');
        $diag['woo_function_exists_after_require'] = function_exists('wc_api_hash');
    } catch (\Throwable $e) {
        $diag['woo_require_error'] = $e->getMessage();
    }
    $diag['woo_class_exists'] = class_exists('WooCommerce');
    $diag['woo_function_exists'] = function_exists('wc_api_hash');
}
```

### 工作流程

1. **检查插件状态**：查询 `wp_options.active_plugins`
2. **检测插件文件**：验证 `wp-content/plugins/woocommerce/woocommerce.php` 是否存在
3. **自动激活**：如果文件存在但未激活，写入数据库激活它
4. **手动加载**：如果 PHP 类未加载，通过 `require_once` 加载
5. **生成 Key**：激活成功后，正常生成 WooCommerce API Key

## 修复效果

### 修复前

```
restore_files → WooCommerce 插件文件已存在
restore_db → active_plugins 未包含 WooCommerce
fetch_woo_keys → PHP 检查失败 → 抛异常 → 建站失败 ❌
```

**日志：**
```
ERROR | 建站执行失败: WordPress get woo key 失败: WooCommerce class/function not loaded
ERROR | 任务失败
```

### 修复后

```
restore_files → WooCommerce 插件文件已存在
restore_db → active_plugins 未包含 WooCommerce
fetch_woo_keys → PHP 自动激活 → 加载类 → 生成 Key → 建站成功 ✅
```

**日志：**
```
INFO | Woo key 响应: code=200, domain=example.com, debug={'woo_auto_activated': true, ...}
INFO | 站点 example.com 域名替换完成
INFO | 建站完成
```

### 工作原理

1. **检测状态**
   ```php
   $woo_in_active_plugins = in_array('woocommerce/woocommerce.php', get_option('active_plugins', []), true);
   // → false（数据库中未激活）
   ```

2. **检测文件**
   ```php
   $woo_main_file = WP_PLUGIN_DIR . '/woocommerce/woocommerce.php';
   file_exists($woo_main_file);
   // → true（文件存在）
   ```

3. **自动激活**
   ```php
   $active_plugins[] = 'woocommerce/woocommerce.php';
   update_option('active_plugins', $active_plugins);
   // → 写入数据库，激活插件
   ```

4. **加载类**
   ```php
   require_once $woo_main_file;
   // → 加载 WooCommerce 类和函数
   ```

5. **生成 Key**
   ```php
   $consumer_key = 'ck_' . bin2hex(random_bytes(20));
   $consumer_secret = 'cs_' . bin2hex(random_bytes(20));
   // → 正常生成并保存
   ```

## 影响范围

### 修改的文件

1. **[wp_restorer.py](file:///e:/Python/vue-fastapi-admin-main/app/services/onepanel/wp_restorer.py#L600-L610)**
   - `inject_woo_script()` 中的 PHP 代码：增加自动激活逻辑
   - 在检测 WooCommerce 状态时，如果插件文件存在但未激活，自动写入数据库激活

2. **[provision.py](file:///e:/Python/vue-fastapi-admin-main/app/services/tasks/provision.py#L273-L279)**
   - 恢复原有逻辑：WooCommerce Key 生成是必需步骤
   - 移除了可选处理的 try-except 包裹

3. **docs/fix-woocommerce-optional.md**
   - 详细的修复文档

### 向后兼容性

- ✅ 如果 WooCommerce 已激活，不会重复激活
- ✅ 如果 WooCommerce 文件不存在，正常报错（这是真实错误）
- ✅ 自动激活是幂等操作，多次执行不会产生副作用
- ✅ 诊断信息中记录 `woo_auto_activated` 标志，便于排查

## 测试验证

### 测试场景

1. **WooCommerce 已激活（正常情况）**
   - 预期：直接生成 Key，建站成功
   - 日志：`Woo key 响应: code=200`
   - 诊断：`woo_in_active_plugins: true`，无 `woo_auto_activated` 标志

2. **WooCommerce 文件存在但未激活（需自动激活）**
   - 预期：自动激活插件，加载类，生成 Key，建站成功
   - 日志：`Woo key 响应: code=200`
   - 诊断：`woo_auto_activated: true`，`woo_in_active_plugins: true`

3. **WooCommerce 文件不存在（真实错误）**
   - 预期：报错，建站失败
   - 日志：`ERROR | WooCommerce not active in current site`
   - 诊断：`woo_main_file: null` 或文件路径，`file_exists: false`

4. **WooCommerce 文件损坏（加载失败）**
   - 预期：报错，建站失败
   - 日志：`ERROR | WooCommerce class/function not loaded`
   - 诊断：`woo_require_error: [PHP错误信息]`

### 手动验证命令

```bash
# 1. 查看建站日志，确认 WooCommerce 状态
grep -E "WooCommerce|woo_key|woo_auto_activated" /var/log/app.log

# 2. 检查数据库中的激活状态
wp option get active_plugins --path=/opt/1panel/apps/wordpress/.../data

# 3. 查看 WooCommerce 插件文件
ls -la /opt/1panel/apps/wordpress/.../data/wp-content/plugins/woocommerce/

# 4. 验证 API Key 是否生成
wp db query "SELECT * FROM wp_woocommerce_api_keys ORDER BY key_id DESC LIMIT 1" --path=/opt/1panel/apps/wordpress/.../data
```

## 总结

这次修复通过 **PHP 脚本自动激活 WooCommerce 插件**，解决了因数据库和文件备份不同步导致的 Key 生成失败问题。

### 关键改进

1. ✅ **自动修复不一致**：插件文件存在但未激活时，自动写入数据库激活
2. ✅ **幂等操作**：已激活的插件不会重复激活
3. ✅ **健壮性**：增加诊断信息，便于排查真实错误
4. ✅ **业务完整性**：确保 WooCommerce Key 必定生成，不影响后续业务流程

### 设计原则

- **自动修复预期问题**：数据库/文件不同步是建站流程的常见问题，应自动处理
- **区分预期与异常**：插件未激活 → 自动修复；插件不存在 → 真实错误
- **保持业务完整**：WooCommerce Key 是业务必需，不能降级跳过
- **详细诊断**：记录自动激活标志和详细状态，便于问题追踪

### 与 domain-replace 404 修复的关系

两个修复都遵循相同的原则：
- **domain-replace 404**：API 返回无效路径 → 智能查找正确路径
- **WooCommerce 未激活**：数据库状态错误 → 自动修复状态

下次建站时，即使数据库和文件备份不同步，WooCommerce 也会被自动激活，Key 生成成功。
