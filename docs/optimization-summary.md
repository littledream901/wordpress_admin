# 建站流程优化总结

## 优化时间
2026-08-12

## 优化目标
- 减少 rebuild 次数，提升建站速度 40-50%
- 增强路径解析准确性，避免 404 错误
- 提高文件恢复的幂等性和可靠性
- 增加性能监控，便于后续优化

## 已完成的优化

### 1. 高优先级优化

#### 1.1 减少 rebuild 次数
**问题**：原流程中有 2-4 次 rebuild，每次 rebuild 耗时 15-30 秒，且可能导致文件丢失。

**优化方案**：
- 将所有文件操作（restore_files、inject_woo_script、inject_ctx_script、inject_mu_plugins）合并到第一次 rebuild 之前
- 移除 `rebuild_after_files` 步骤
- 移除 `rebuild_after_patch` 步骤
- 将 `patch_wp_config` 独立为单个步骤，放在域名替换之后
- 只在文件验证失败时才触发第二次 rebuild

**优化前流程**：
```
Step 3: restore_db
Step 4: restore_files
Step 5: rebuild_after_files  ← rebuild #1
Step 6: replace_domain
Step 7-8: patch + inject scripts (4个并行)
Step 9: rebuild_after_patch  ← rebuild #2
Step 10: verify_and_restore
```

**优化后流程**：
```
Step 3-4-5: restore_db + restore_files + inject_scripts (5个并行)
Step 6: rebuild_once         ← rebuild #1 (一次性加载所有变更)
Step 7: replace_domain
Step 8: patch_wp_config
Step 9: verify_and_restore   ← rebuild #2 (仅在文件丢失时触发)
Step 10: fetch_woo_keys
```

**预期效果**：
- 正常情况下：rebuild 次数从 2 次减少到 1 次，节省 15-30 秒
- 文件丢失情况：rebuild 次数从 3-4 次减少到 2 次，节省 30-60 秒
- 总体建站速度提升 40-50%

**涉及文件**：
- `app/services/tasks/provision.py`（169-330 行）

#### 1.2 使用 sitePath 替代 siteDir
**问题**：`get_site_root()` 从 1Panel API 获取的 `siteDir` 可能返回 "/"（根目录），导致脚本写入错误位置，引发 404 错误。

**优化方案**：
- 新增 `get_wp_root()` 方法，优先使用更准确的 `sitePath` 字段
- 在 `_extract_site_dir()` 中过滤无效路径（"/" 和空字符串）
- 降级机制：当 `sitePath` 不可用时，使用智能查找（`_find_wp_root_fallback`）

**代码示例**：
```python
def get_wp_root(self, service_name: str, site_id: int, domain: str) -> str:
    """获取 WordPress 根目录（优先使用 sitePath）"""
    try:
        site_data = self.get_site_by_id(site_id)
        site_path = (site_data.get('sitePath') or '').strip()
        if site_path and site_path != '/':
            _log.info("从 1Panel sitePath 获取 WordPress 根目录: %s", site_path)
            return site_path
    except Exception as e:
        _log.warning("获取 sitePath 失败: %s，降级使用智能查找", e)
    
    # 降级：智能查找
    return self._find_wp_root_fallback(service_name, domain)
```

**涉及文件**：
- `app/services/onepanel/site_manager.py`（新增 `get_wp_root()` 方法）
- `app/services/tasks/provision.py`（207-215 行，使用新方法）

#### 1.3 增强文件恢复的幂等性
**问题**：rebuild 后可能导致 WooCommerce 等插件文件丢失，原有的单文件检查不够全面。

**优化方案**：
- 新增 `verify_and_restore_files()` 方法，支持批量验证多个关键文件
- 自动检测文件丢失并触发恢复
- 恢复后自动触发 rebuild
- 在 `_resolve_target_dir()` 中验证目录是否包含 `wp-config.php`

**代码示例**：
```python
def verify_and_restore_files(self, service_name: str, required_files: List[str] = None) -> bool:
    """验证关键文件并自动恢复"""
    if required_files is None:
        required_files = [
            'wp-content/plugins/woocommerce/woocommerce.php',
            'wp-content/mu-plugins/woo-ctx.php',
        ]
    
    wp_root = self._data_root(service_name)
    missing_files = []
    
    for rel_path in required_files:
        full_path = f'{wp_root}/{rel_path}'
        if self.file_manager and not self.file_manager.exists(full_path):
            missing_files.append(rel_path)
    
    if missing_files:
        _log.warning("检测到 %d 个文件丢失: %s，开始恢复", len(missing_files), missing_files)
        self.restore_files(service_name)
        return True
    
    _log.info("所有关键文件完整，无需恢复")
    return False
```

**涉及文件**：
- `app/services/onepanel/wp_restorer.py`（新增 `verify_and_restore_files()` 方法）
- `app/services/tasks/provision.py`（266-284 行，使用新方法）

### 2. 中优先级优化

#### 2.1 优化 4.1：增加性能监控
**问题**：无法量化每个步骤的耗时，难以定位性能瓶颈。

**优化方案**：
- 在 `ProvisionTaskRunner` 中新增 `_start_step()` 和 `_end_step()` 方法
- 自动记录每个步骤的开始时间、结束时间和耗时（毫秒）
- 将性能数据追加到站点 `pipeline_log` 中
- 所有 12 个建站步骤已接入性能监控

**代码示例**：
```python
async def _start_step(self, job: OperationJob, step: str):
    """开始步骤并记录时间"""
    self._step_timings[step] = datetime.now()
    await self._update_step(job, step)
    _log.info("步骤开始: %s (site_id=%s)", step, job.resource_id)

async def _end_step(self, job: OperationJob, step: str, site: Optional[Site] = None):
    """结束步骤并记录耗时"""
    if step in self._step_timings:
        start_time = self._step_timings[step]
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        _log.info("步骤完成: %s, 耗时: %d ms (site_id=%s)", step, duration_ms, job.resource_id)
        
        # 追加到站点日志
        if site:
            self._append_site_log(
                site,
                source=f"provision:{step}",
                data={"step": step, "duration_ms": duration_ms},
                action=step,
                status="success",
                started_at=start_time,
                completed_at=end_time,
            )
            await site.save(update_fields=["pipeline_log"])
        
        del self._step_timings[step]
```

**涉及文件**：
- `app/services/tasks/provision.py`（新增 `__init__`、`_start_step`、`_end_step` 方法，48-83 行）
- `app/services/tasks/provision.py`（所有步骤调用点已更新）

#### 2.2 并行化独立步骤
**状态**：已部分实现

**已实现**：
- `restore_db` + `restore_files` + `inject_woo_script` + `inject_ctx_script` + `inject_mu_plugins`（5 个操作并行）

**可进一步优化**：
- DNS 检查 + Zone 创建（如果 Zone 不存在）
- SSL 申请 + 数据库恢复（如果 DNS 已就绪）

## 优化效果预期

### 性能提升
- **正常建站**：rebuild 次数从 2 次减少到 1 次，节省 15-30 秒，总时长从 2-3 分钟缩短到 1.5-2 分钟（**提升 40-50%**）
- **文件丢失场景**：rebuild 次数从 3-4 次减少到 2 次，节省 30-60 秒
- **并行化**：5 个文件操作并行执行，节省 30-60 秒

### 可靠性提升
- **404 错误修复**：使用 `sitePath` 优先策略，准确定位 WordPress 根目录
- **文件完整性**：批量验证关键文件，自动恢复丢失的插件文件
- **幂等性增强**：多次执行不会产生副作用，安全可重试

### 可观测性提升
- **性能监控**：每个步骤的耗时记录到 `pipeline_log`，便于分析瓶颈
- **日志增强**：详细记录路径解析、文件验证、rebuild 决策的日志

## 待测试项

1. **正常建站流程**：验证优化后的流程是否正常工作
2. **rebuild 次数**：实际运行时 rebuild 是否真的减少到 1-2 次
3. **性能数据**：收集实际的步骤耗时数据，验证性能提升是否达到预期
4. **404 错误**：验证 `domain-replace.php` 是否不再返回 404
5. **文件完整性**：验证 rebuild 后 WooCommerce 插件文件是否完整

## 下一步建议

### 进一步优化（低优先级）
1. **优化 DNS 等待时间**：当前 DNS 检查后有 5 秒等待，可以改为轮询检查 Nginx reload 状态
2. **缓存 1Panel API 响应**：减少重复的 API 调用（如 `get_site_by_id`）
3. **优化域名替换**：考虑使用 WP-CLI 替代 PHP 脚本，提升稳定性
4. **增加重试机制**：对于偶发性失败的步骤（如 SSL 申请），增加自动重试

### 监控和告警
1. **建站成功率监控**：统计每天的建站成功率和失败原因
2. **性能趋势监控**：定期分析 `pipeline_log`，识别性能退化
3. **异常告警**：当 rebuild 次数 > 2 或某个步骤耗时 > 阈值时发送告警

## 相关文档
- [404 问题修复方案](./fix-domain-replace-404.md)
- [优化建议详细文档](./optimization-recommendations.md)
- [1Panel API rebuild 机制分析](./1panel-api-analysis-rebuild.md)
