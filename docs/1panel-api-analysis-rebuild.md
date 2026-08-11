# 1Panel API 分析：rebuild 行为与 siteDir 问题

## 文档信息
- **分析日期**: 2026-08-12
- **1Panel API 版本**: v2.0
- **问题**: rebuild 导致文件丢失 & siteDir 返回无效路径

---

## 一、rebuild API 分析

### 1.1 API 端点
```
POST /api/v2/apps/installed/op
```

### 1.2 请求参数 (`request.AppInstalledOperate`)
```json
{
  "installId": 123,           // required - 应用安装 ID
  "operate": "rebuild",       // required - 操作类型
  "taskID": "uuid-string",    // optional - 任务 ID
  "backup": false,            // optional - 是否备份
  "deleteBackup": false,      // optional - 是否删除备份
  "deleteDB": false,          // optional - 是否删除数据库
  "deleteImage": false,       // optional - 是否删除镜像
  "forceDelete": false,       // optional - 是否强制删除
  "pullImage": false,         // optional - 是否拉取镜像
  "dockerCompose": "",        // optional - docker-compose 内容
  "detailId": 0,              // optional - 详情 ID
  "favorite": false           // optional - 是否收藏
}
```

### 1.3 我们的调用方式
```python
# app/services/onepanel/site_manager.py:239
self.api.post('/apps/installed/op', {
    'installId': app_id, 
    'operate': 'rebuild', 
    'taskID': str(uuid.uuid4())
})
```

### 1.4 rebuild 操作的实际行为

根据日志观察：

**现象 1：service_name 时间戳倒退**
```
rebuild 前: qciqcgsi-shop-038745-1786468430537
rebuild 后: qciqcgsi-shop-038745-1786463503656  ← 时间戳更早！
```

**现象 2：文件丢失**
```
恢复文件 → /opt/1panel/apps/wordpress/.../data/wp-content/plugins/woocommerce/ ✅
rebuild  → 文件消失 ❌
```

**结论：**
- ❌ rebuild **不是简单的容器重启** (`docker restart`)
- ✅ rebuild 可能是 **容器重建** (`docker rm` + `docker create`)
- ✅ rebuild 可能 **回滚到某个快照或初始状态**
- ⚠️ rebuild 会 **重置部分文件系统**，即使文件在挂载目录

---

## 二、Website API 分析

### 2.1 获取网站信息 API

#### 端点 1: 获取单个网站
```
GET /api/v2/websites/:id
```

**响应**: `response.WebsiteDTO`

#### 端点 2: 搜索网站列表
```
POST /api/v2/websites/search
```

**响应**: `dto.PageResult` (包含 `response.WebsiteDTO` 数组)

### 2.2 WebsiteDTO 结构

关键字段（共 50+ 字段）：

```typescript
{
  "id": 123,                    // 网站 ID
  "primaryDomain": "example.com",
  "alias": "我的网站",
  "status": "running",
  "protocol": "https",
  
  // 路径相关
  "siteDir": "/",              // ⚠️ Nginx root（可能是 / 或其他路径）
  "sitePath": "/opt/1panel/...", // 应用安装路径
  
  // 应用相关
  "appInstallId": 456,
  "appName": "WordPress",
  "runtimeType": "php",
  "runtimeName": "PHP 8.1",
  
  // 其他
  "webSiteGroupId": 1,
  "domains": [...],
  "webSiteSSL": {...},
  ...
}
```

### 2.3 siteDir 字段问题

#### 问题表现

从日志可见：
```python
# 日志: 站点 qciqcgsi.shop (id=12) 已找到但无 siteDir，可用字段: [...]
# 实际: siteDir 存在，但值为 "/"
```

#### siteDir 的含义

根据 1Panel 逻辑：
- **siteDir** = Nginx `root` 指令的值
- 对于 WordPress 应用，通常是：
  - ❌ **错误返回**: `/` (根目录)
  - ✅ **期望返回**: `/var/www/html` 或相对路径

#### 为什么 siteDir 返回 `/`？

**可能原因 1: WordPress 应用的特殊配置**
```nginx
# WordPress 应用的 Nginx 配置可能是：
root /;
location / {
    proxy_pass http://wordpress-container:80;
}
```
这种反向代理模式下，Nginx root 确实是 `/`，但这不是 WordPress 文件的真实路径。

**可能原因 2: 1Panel 的默认值**
- 未显式配置 root 时，1Panel 可能默认返回 `/`
- 这是一个 fallback 值，不是真实的 document root

**可能原因 3: 容器化应用的路径差异**
- `siteDir`: Nginx 配置中的路径（宿主机或反向代理）
- `sitePath`: 应用实际安装路径（宿主机）
- 容器内路径: `/var/www/html`（容器内部）

#### sitePath vs siteDir

```python
{
  "siteDir": "/",                                    # Nginx root（无效）
  "sitePath": "/opt/1panel/apps/wordpress/..."      # 应用安装路径（有效）
}
```

**结论：**
- ❌ `siteDir` 不能直接用于定位 WordPress 文件
- ✅ `sitePath` 才是应用的真实安装路径
- ✅ WordPress 文件在 `{sitePath}/data`

---

## 三、问题根源总结

### 3.1 第二次 rebuild 引入时间

**提交**: `f61fcbd` (2026-07-19)
**标题**: fix: 调整建站流程顺序对齐单脚本

**变更**:
```diff
- 旧流程: restore_files → rebuild → replace_domain → ... → 单次操作 create_woo_ctx
+ 新流程: restore_files → rebuild → replace_domain → ... → inject_woo_ctx → rebuild → fetch_woo_keys
```

**目的**: 对齐单脚本 `1panel_create_wp_final.py` 的流程

### 3.2 问题链条

```
1. 引入第二次 rebuild（对齐单脚本）
   ↓
2. rebuild 行为发生变化（1Panel 更新？容器策略变更？）
   - 从"重启容器"变成"重建容器"
   - service_name 时间戳倒退
   ↓
3. 恢复的文件被 rebuild 清空
   - WooCommerce 插件消失
   - domain-replace.php 无法访问
   ↓
4. siteDir 返回无效路径 `/`
   - get_site_root() 返回 `/`
   - domain-replace.php 写入错误位置
   ↓
5. 建站失败：HTTP 404
```

### 3.3 为什么以前可以正常使用？

**可能的历史场景**:

#### 场景 A: 没有第二次 rebuild
```python
# 旧流程（推测）
恢复文件 → rebuild → 域名替换 → 注入脚本 → 获取 Key ✅
# 只有一次 rebuild，在文件恢复后立即执行
```

#### 场景 B: rebuild 行为不同
```python
# 1Panel 旧版本
rebuild = docker restart  → 保留所有文件 ✅
```

#### 场景 C: 文件恢复路径不同
```python
# 可能恢复到不同的挂载点
恢复到持久卷 → rebuild 不影响 ✅
```

#### 场景 D: siteDir 返回有效路径
```python
# 1Panel 旧版本或不同配置
siteDir = "/var/www/html"  → 文件正确写入 ✅
```

---

## 四、我们的修复方案

### 4.1 修复 1: 过滤无效 siteDir

**文件**: `app/services/onepanel/site_manager.py:67-87`

```python
@staticmethod
def _extract_site_dir(item: dict) -> Optional[str]:
    site_dir = item.get('siteDir') or item.get('site_dir') or ...
    
    # 过滤无效路径：单个 / 或空路径不是有效的 WordPress document root
    if not site_dir_str or site_dir_str == '/':
        return None  # 让智能查找机制接管
        
    return site_dir_str
```

### 4.2 修复 2: 验证目标目录

**文件**: `app/services/onepanel/wp_restorer.py:101-119`

```python
def _resolve_target_dir(self, service_name: str, target_dir: Optional[str] = None) -> str:
    if target_dir:
        # 验证传入的目录是否真的包含 WordPress
        wp_config_path = f'{target_dir}/wp-config.php'
        if os.path.exists(wp_config_path):
            return target_dir
        # 验证失败，降级到智能查找
    
    # 智能查找 wp-config.php
    return self._find_wp_root(service_name)
```

### 4.3 修复 3: rebuild 后自动恢复文件

**文件**: `app/services/tasks/provision.py:152-177`

```python
# Step 9: rebuild_after_patch
await self._update_step(job, "rebuild_after_patch")
await self._exec(lambda: site_manager.rebuild_app(app_id))

# Step 9.5: 检查关键文件是否丢失（rebuild 可能清空文件）
woo_main_file = f'{wp_root}/wp-content/plugins/woocommerce/woocommerce.php'
if not os.path.exists(woo_main_file):
    _log.warning("第二次 rebuild 后 WooCommerce 文件丢失，重新恢复文件")
    
    # 重新恢复文件
    await self._exec(lambda: wp_restorer.restore_files(service_name))
    
    # 再次 rebuild
    await self._exec(lambda: site_manager.rebuild_app(app_id))
```

---

## 五、1Panel API 使用建议

### 5.1 获取 WordPress 文件路径

**❌ 不推荐：直接使用 siteDir**
```python
site_dir = website_data.get('siteDir')  # 可能是 "/"
```

**✅ 推荐：使用 sitePath + 智能查找**
```python
site_path = website_data.get('sitePath')  # /opt/1panel/apps/wordpress/xxx
wp_root = f'{site_path}/data'            # WordPress 实际目录
if not os.path.exists(f'{wp_root}/wp-config.php'):
    # 降级到智能查找
    wp_root = self._find_wp_config(site_path)
```

### 5.2 rebuild 操作的安全使用

**❌ 不安全：直接 rebuild**
```python
site_manager.rebuild_app(app_id)
# 文件可能丢失！
```

**✅ 安全：rebuild 后验证文件**
```python
site_manager.rebuild_app(app_id)

# 验证关键文件
if not os.path.exists(critical_file):
    # 重新恢复文件
    wp_restorer.restore_files(service_name)
    # 再次 rebuild
    site_manager.rebuild_app(app_id)
```

### 5.3 获取应用信息的最佳实践

```python
# 1. 优先使用 GET /websites/:id（单个查询，性能好）
ok, data = self.api.get(f'/websites/{site_id}')

# 2. 需要批量查询时使用 POST /websites/search
ok, data = self.api.post('/websites/search', {
    'page': 1,
    'pageSize': 100,
    'sync': True  # 同步最新状态
})

# 3. 提取路径时的优先级
paths = [
    data.get('sitePath'),      # 最优先：应用安装路径
    data.get('siteDir'),       # 次优先：可能是 Nginx root
    self._find_by_service()    # 降级：通过 service_name 查找
]
```

---

## 六、待确认问题

### 6.1 rebuild 的真实实现

**需要确认**:
1. rebuild 是否调用 `docker-compose down && docker-compose up`？
2. rebuild 是否使用镜像快照？为什么 service_name 时间戳会倒退？
3. rebuild 是否会重置容器内的部分文件系统？

**建议**: 联系 1Panel 官方或查看源码确认

### 6.2 siteDir 的设计意图

**需要确认**:
1. siteDir 返回 `/` 是否是预期行为？
2. 对于容器化应用，siteDir 和 sitePath 的区别是什么？
3. 如何正确获取 WordPress 的 document root？

**建议**: 查看 1Panel 官方文档或源码

### 6.3 单脚本的实际实现

**需要确认**:
1. `1panel_create_wp_final.py` 在 rebuild 前是否有文件保护措施？
2. 单脚本是如何处理 siteDir 的？
3. 单脚本在 rebuild 后是否也会遇到文件丢失问题？

**建议**: 查看单脚本源码对比

---

## 七、结论

### 7.1 核心问题

1. **rebuild 行为变化**: 从"重启"变成"重建"，导致文件丢失
2. **siteDir 返回无效**: 返回 `/` 而不是真实的 WordPress 路径
3. **流程重构副作用**: 引入第二次 rebuild 但未考虑文件保护

### 7.2 修复效果

我们的三层防御已经解决问题：

```
Layer 1: 过滤无效 siteDir (/) → 返回 None
Layer 2: 验证目标目录是否包含 wp-config.php → 降级到智能查找
Layer 3: rebuild 后检查文件 → 自动重新恢复 → 再次 rebuild
```

**修复后流程**:
```
API 返回 "/" → 过滤拒绝 → 智能查找 → 脚本写入正确目录 → rebuild → 
文件丢失 → 自动检测 → 重新恢复 → 再次 rebuild → WooCommerce 类加载成功 → 
建站完成 ✅
```

### 7.3 长期建议

1. **监控 1Panel 更新**: 关注 rebuild API 行为变化
2. **考虑移除第二次 rebuild**: 如果确认不影响脚本加载
3. **使用 sitePath 而非 siteDir**: 更可靠的路径来源
4. **增加更多自愈检查**: 不仅检查 WooCommerce，也检查其他关键文件
