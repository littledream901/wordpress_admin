# WordPress 版本选择逻辑修复

## 问题描述

**发现时间**：2026-08-12

**问题现象**：
- Provider 配置中设置了 `wp_version: 7.0.0`
- 实际建站时安装的是 `7.0.2` 版本
- 日志显示：
  ```
  resolve_wp_app 自动检测模式: wp_app_key=wordpress 目标版本=7.0.0
  resolve_wp_app 尝试版本列表: ['7.0.2', '7.0.1', '7.0.0', '6.9.4', '6.8.3', '6.7.2']
  resolve_wp_app 自动检测成功: app_id=134 app_detail_id=385 version=7.0.2
  ```

**用户配置**：
```json
{
  "wp_version": "7.0.0",
  "wp_app_key": "wordpress",
  "wp_app_type": "docker",
  "wp_app_id": "",
  "wp_app_detail_id": ""
}
```

## 根本原因

### 原代码逻辑（有 Bug）

位置：`app/services/onepanel/site_manager.py:200-208`

```python
# 版本迭代：从 app 元数据中获取可用版本列表，依次尝试
versions = []
if isinstance(app_data.get('versions'), list):
    versions = [v for v in app_data['versions'] if v]
if not versions:
    versions = [app_data.get('version') or self.wp_version or 'latest']

# ❌ Bug：只有当指定版本不在列表中时，才会插入到第一位
if self.wp_version != 'latest' and self.wp_version not in versions:
    versions.insert(0, self.wp_version)

_log.info("resolve_wp_app 尝试版本列表: %s (app_id=%s app_type=%s)", versions, app_id, app_type)

# 从第一个版本开始尝试
for v in versions:
    ok, detail = self.api.get(f'/apps/detail/{app_id}/{v}/{app_type}')
    if ok and isinstance(detail, dict) and detail.get('id'):
        # 使用第一个可用的版本
        return result
```

### 问题分析

1. **1Panel API 返回版本列表**：`['7.0.2', '7.0.1', '7.0.0', '6.9.4', '6.8.3', '6.7.2']`
   - 版本按照**新到旧**排序
   - `7.0.0` 在列表的第 3 位

2. **版本插入逻辑有缺陷**：
   ```python
   if self.wp_version != 'latest' and self.wp_version not in versions:
       versions.insert(0, self.wp_version)
   ```
   - 条件：`self.wp_version not in versions`（指定版本不在列表中）
   - 因为 `7.0.0` **已经在**列表中，所以不会执行 `insert`
   - 版本列表保持原样：`['7.0.2', '7.0.1', '7.0.0', ...]`

3. **依次尝试，使用第一个可用版本**：
   - 从 `7.0.2` 开始尝试
   - 1Panel API 返回成功（有 `detail.id`）
   - 直接使用 `7.0.2`，不再尝试后续版本
   - **结果**：忽略了用户指定的 `7.0.0`

### 设计初衷 vs 实际行为

**设计初衷**（推测）：
- 如果用户指定了一个 1Panel 中不存在的版本（如 `7.0.0-beta`），将其加到列表开头
- 如果 API 没有该版本，自动降级到其他可用版本（容错机制）

**实际行为**：
- 如果用户指定的版本在列表中（如 `7.0.0`），不会调整优先级
- 始终使用列表中的**第一个**可用版本（通常是最新版本）
- **用户的版本指定被忽略**

## 修复方案

### 修改后的代码

```python
# 版本迭代：从 app 元数据中获取可用版本列表，依次尝试
versions = []
if isinstance(app_data.get('versions'), list):
    versions = [v for v in app_data['versions'] if v]
if not versions:
    versions = [app_data.get('version') or self.wp_version or 'latest']

# ✅ 修复：如果指定了非 latest 版本，优先使用指定版本
if self.wp_version != 'latest':
    if self.wp_version in versions:
        # 如果指定版本在列表中，将其移到第一位
        versions.remove(self.wp_version)
    # 插入到第一位，确保优先尝试
    versions.insert(0, self.wp_version)

_log.info("resolve_wp_app 尝试版本列表: %s (app_id=%s app_type=%s, 目标版本=%s)", 
          versions, app_id, app_type, self.wp_version)

# 从第一个版本开始尝试（现在是用户指定的版本）
for v in versions:
    ok, detail = self.api.get(f'/apps/detail/{app_id}/{v}/{app_type}')
    if ok and isinstance(detail, dict) and detail.get('id'):
        return result
```

### 修复逻辑

1. **移除重复**（如果指定版本在列表中）：
   ```python
   if self.wp_version in versions:
       versions.remove(self.wp_version)
   ```

2. **无条件插入到第一位**：
   ```python
   versions.insert(0, self.wp_version)
   ```

3. **结果**：
   - 原列表：`['7.0.2', '7.0.1', '7.0.0', '6.9.4', ...]`
   - 新列表：`['7.0.0', '7.0.2', '7.0.1', '6.9.4', ...]`
   - 优先尝试用户指定的 `7.0.0`

### 容错机制保留

如果用户指定的版本在 1Panel 中不可用：
```python
for v in versions:
    ok, detail = self.api.get(f'/apps/detail/{app_id}/{v}/{app_type}')
    if ok and isinstance(detail, dict) and detail.get('id'):
        return result
```

- 尝试 `7.0.0`：失败（API 返回 404 或无效数据）
- 继续尝试 `7.0.2`：成功，使用降级版本
- **容错机制依然有效**

## 修复效果

### 修复前

```
配置版本: 7.0.0
1Panel 版本列表: ['7.0.2', '7.0.1', '7.0.0', '6.9.4', ...]

日志:
resolve_wp_app 尝试版本列表: ['7.0.2', '7.0.1', '7.0.0', '6.9.4', ...]
resolve_wp_app 自动检测成功: version=7.0.2

实际安装: 7.0.2 ❌
```

### 修复后

```
配置版本: 7.0.0
1Panel 版本列表: ['7.0.2', '7.0.1', '7.0.0', '6.9.4', ...]

日志:
resolve_wp_app 尝试版本列表: ['7.0.0', '7.0.2', '7.0.1', '6.9.4', ...] (目标版本=7.0.0)
resolve_wp_app 自动检测成功: version=7.0.0

实际安装: 7.0.0 ✅
```

## 测试场景

### 场景 1：指定版本在列表中（常见）

**配置**：`wp_version: 7.0.0`
**1Panel 版本列表**：`['7.0.2', '7.0.1', '7.0.0', '6.9.4']`

- ✅ 修复前：安装 `7.0.2`
- ✅ 修复后：安装 `7.0.0`

### 场景 2：指定版本不在列表中（容错）

**配置**：`wp_version: 7.0.0-beta`
**1Panel 版本列表**：`['7.0.2', '7.0.1', '6.9.4']`

- ✅ 修复前：安装 `7.0.2`
- ✅ 修复后：尝试 `7.0.0-beta`（失败），降级到 `7.0.2`

### 场景 3：指定 latest（自动使用最新）

**配置**：`wp_version: latest`
**1Panel 版本列表**：`['7.0.2', '7.0.1', '7.0.0']`

- ✅ 修复前：安装 `7.0.2`
- ✅ 修复后：安装 `7.0.2`（行为不变）

### 场景 4：手动指定 detail_id（跳过自动检测）

**配置**：
```json
{
  "wp_app_detail_id": "385",
  "wp_version": "7.0.0"
}
```

- ✅ 修复前：直接使用 `detail_id=385`，跳过版本检测
- ✅ 修复后：直接使用 `detail_id=385`，跳过版本检测（行为不变）

## 相关配置

### 环境变量配置

```bash
# .env 文件
OP_WP_VERSION=7.0.0           # 指定 WordPress 版本
OP_WP_APP_KEY=wordpress       # 应用 key
OP_WP_APP_TYPE=docker         # 应用类型
OP_WP_APP_ID=134              # 应用 ID（可选，自动检测）
OP_WP_APP_DETAIL_ID=385       # 应用详情 ID（可选，跳过版本检测）
```

### Provider 配置

在管理后台的 Provider 配置中：

```json
{
  "wp_version": "7.0.0",
  "wp_app_key": "wordpress",
  "wp_app_type": "docker",
  "wp_app_id": "",
  "wp_app_detail_id": "",
  "auto_detect_wp_app": "true"
}
```

### 配置优先级

1. **手动指定 detail_id**（最高优先级）
   ```json
   {
     "wp_app_detail_id": "385",
     "wp_version": "7.0.0"
   }
   ```
   - 跳过自动检测，直接使用指定的 `detail_id`
   - `wp_version` 仅用于日志显示

2. **指定版本 + 自动检测**（推荐）
   ```json
   {
     "wp_version": "7.0.0",
     "auto_detect_wp_app": "true"
   }
   ```
   - 优先尝试 `7.0.0`
   - 如果不可用，自动降级到其他版本

3. **使用 latest**（默认）
   ```json
   {
     "wp_version": "latest",
     "auto_detect_wp_app": "true"
   }
   ```
   - 使用 1Panel 中的最新可用版本

## 影响范围

### 受影响的功能

- ✅ 建站流程（`provision.py`）
- ✅ 站点重建（如果使用 `resolve_wp_app`）
- ✅ 所有需要创建 WordPress 应用的场景

### 不受影响的场景

- ✅ 已创建的站点（不会自动升级/降级）
- ✅ 手动指定 `wp_app_detail_id` 的场景

## 涉及文件

- `app/services/onepanel/site_manager.py`（第 200-216 行）
- `app/utils/provider_defaults.py`（配置默认值）
- `app/utils/config_reader.py`（配置映射）
- `app/core/init_app.py`（配置初始化）

## 相关文档

- [优化总结](./optimization-summary.md)
- [第二轮优化方案](./optimization-round2.md)
- [第二轮测试结果](./optimization-round2-test-results.md)

## 结论

这是一个**设计缺陷**，而不是配置问题：

- 原代码假设用户指定的版本不在 1Panel 列表中（需要容错）
- 实际使用中，用户通常指定**列表中已有的版本**（锁定版本）
- 修复后，同时支持两种场景：
  1. **版本锁定**：优先使用用户指定的版本
  2. **自动降级**：如果指定版本不可用，降级到其他版本

修复后的逻辑更符合用户预期，同时保留了容错机制。
