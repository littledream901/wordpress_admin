# 建站流程优化建议

## 文档信息
- **创建日期**: 2026-08-12
- **基于版本**: 当前 provision.py 实现
- **问题背景**: rebuild 导致文件丢失、性能瓶颈、稳定性问题

---

## 一、高优先级优化（立即可实施）

### 1.1 减少 rebuild 次数 ⭐⭐⭐

**现状问题**:
```python
# 当前流程（最多 4 次 rebuild！）
创建站点 → rebuild(1) → 恢复文件 → rebuild(2) → 注入脚本 → rebuild(3) → 
WooCommerce 丢失 → 恢复文件 → rebuild(4)
```

**优化方案 A: 合并注入 + 恢复后再 rebuild**
```python
# 优化流程（只需 1-2 次 rebuild）
创建站点 → 恢复文件 + 注入所有脚本 → rebuild(1) → [验证] → rebuild(2 可选)
```

**实施步骤**:
```python
# Step 1: 创建站点（不 rebuild）
app_info = site_manager.create_wordpress_website(site.domain, auto_rebuild=False)

# Step 2: 批量操作（无需重启容器）
await asyncio.gather(
    self._exec(lambda: db_restorer.restore_database(db_name, backup)),
    self._exec(lambda: wp_restorer.restore_files(service_name)),
    self._exec(lambda: wp_restorer.inject_woo_script(service_name)),
    self._exec(lambda: wp_restorer.inject_ctx_script(service_name, domain, protocol)),
    self._exec(lambda: wp_restorer.inject_mu_plugins(service_name)),
)

# Step 3: 一次性 rebuild 加载所有变更
await self._exec(lambda: site_manager.rebuild_app(app_id))

# Step 4: 验证并处理 rebuild 副作用（如果需要）
if not wp_restorer.check_woo_file_exists(service_name):
    wp_restorer.restore_files(service_name)
    site_manager.rebuild_app(app_id)  # 最多 2 次
```

**预期收益**:
- ⚡ 减少 50% rebuild 时间（rebuild 平均 15-30 秒）
- 🛡️ 降低文件丢失风险（rebuild 次数从 4 次减少到 1-2 次）
- 📉 减少 service_name 变更次数

---

### 1.2 使用 sitePath 替代 siteDir ⭐⭐⭐

**现状问题**:
```python
# 依赖不可靠的 siteDir
site_root = site_manager.get_site_root(domain, site_id)
# 可能返回 "/" → 需要多层 fallback
```

**优化方案**:
```python
# 直接使用 sitePath（更可靠）
def get_wp_root(self, service_name: str, site_id: int = None) -> str:
    """
    获取 WordPress 根目录（优先使用 sitePath）
    
    优先级:
    1. sitePath + /data (99% 准确)
    2. 通过 service_name 智能查找 (100% 准确但较慢)
    3. siteDir (不推荐)
    """
    # 优先：从 API 获取 sitePath
    if site_id:
        ok, data = self.api.get(f'/websites/{site_id}')
        if ok and data:
            site_path = data.get('sitePath')
            if site_path:
                wp_root = f'{site_path}/data'
                if os.path.exists(f'{wp_root}/wp-config.php'):
                    return wp_root
    
    # 降级：通过 service_name 智能查找
    return self._find_wp_root_by_service(service_name)
```

**实施位置**:
- `app/services/onepanel/site_manager.py`: 新增 `get_wp_root()` 方法
- `app/services/onepanel/wp_restorer.py`: 优先调用 `get_wp_root()`

**预期收益**:
- 🎯 99% 准确率（相比 siteDir 的 ~30%）
- ⚡ 减少智能查找次数（sitePath 直接命中）
- 🛡️ 避免写入错误目录

---

### 1.3 增强文件恢复的幂等性 ⭐⭐

**现状问题**:
```python
# rebuild 后文件可能丢失，但没有统一的恢复机制
if not woo_file_exists:
    restore_files()  # 只保护了 WooCommerce
```

**优化方案**:
```python
def verify_and_restore_files(self, service_name: str, required_files: List[str]) -> bool:
    """
    验证关键文件并自动恢复
    
    Args:
        service_name: 服务名
        required_files: 关键文件列表（相对于 wp_root）
        
    Returns:
        是否需要恢复
    """
    wp_root = self._find_wp_root(service_name)
    missing_files = []
    
    for rel_path in required_files:
        full_path = f'{wp_root}/{rel_path}'
        if not os.path.exists(full_path):
            missing_files.append(rel_path)
    
    if missing_files:
        _log.warning(f"检测到文件丢失: {missing_files}，开始恢复")
        self.restore_files(service_name)
        return True
    
    return False

# 使用示例
CRITICAL_FILES = [
    'wp-content/plugins/woocommerce/woocommerce.php',
    'wp-content/themes/your-theme/style.css',
    'wp-content/mu-plugins/woo-ctx.php',
]

# 在每次 rebuild 后验证
if wp_restorer.verify_and_restore_files(service_name, CRITICAL_FILES):
    site_manager.rebuild_app(app_id)  # 恢复后需要再次 rebuild
```

**预期收益**:
- 🛡️ 全面保护所有关键文件（不只是 WooCommerce）
- 🔄 自动恢复机制（无需人工干预）
- 📊 可监控文件丢失频率

---

## 二、中优先级优化（需要测试验证）

### 2.1 探索 rebuild 的最小化替代方案 ⭐⭐

**现状问题**:
- rebuild 是黑盒操作，可能包含不必要的重置
- rebuild 会导致 service_name 变更、文件丢失等副作用

**优化方向 A: 使用 restart 替代 rebuild**
```python
# 探索是否可以用轻量级 restart
POST /apps/installed/op
{
  "installId": app_id,
  "operate": "restart",  # 而非 "rebuild"
}
```

**优化方向 B: 直接 reload Nginx 配置**
```python
# 如果只是为了 reload Nginx
docker exec {nginx_container} nginx -s reload
```

**优化方向 C: 只在必要时 rebuild**
```python
# 判断是否真的需要 rebuild
def need_rebuild(changes: List[str]) -> bool:
    """
    根据变更类型判断是否需要 rebuild
    
    需要 rebuild:
    - docker-compose.yml 变更
    - 环境变量变更
    - 端口映射变更
    
    不需要 rebuild:
    - 文件变更（直接写入挂载目录即可）
    - PHP 脚本变更（PHP-FPM 会自动重载）
    - 数据库变更（不影响容器）
    """
    rebuild_triggers = [
        'docker-compose.yml',
        '.env',
        'ports',
    ]
    return any(trigger in changes for trigger in rebuild_triggers)
```

**实施步骤**:
1. 在测试环境对比 `restart` vs `rebuild` 效果
2. 记录日志：哪些场景必须 rebuild，哪些可以 restart
3. 逐步减少 rebuild 使用

**预期收益**:
- ⚡ restart 比 rebuild 快 50-80%
- 🛡️ 避免文件丢失风险
- 📉 减少 service_name 变更

---

### 2.2 并行化非依赖步骤 ⭐⭐

**现状问题**:
```python
# 当前部分串行执行
await db_restorer.restore_database(...)      # 30s
await wp_restorer.restore_files(...)         # 60s
await wp_restorer.patch_wp_config(...)       # 5s
```

**优化方案**:
```python
# 并行化独立步骤
await asyncio.gather(
    self._exec(lambda: db_restorer.restore_database(...), timeout=60),
    self._exec(lambda: wp_restorer.restore_files(...), timeout=300),
    self._exec(lambda: ssl_manager.configure_ssl(...), timeout=120),  # 如果可独立
)
```

**注意事项**:
- ⚠️ 确保步骤间无依赖（如 restore_files 不依赖 restore_database）
- ⚠️ 注意 1Panel API 并发限制

**预期收益**:
- ⚡ 减少 30-50% 总耗时（取决于并行步骤数）

---

### 2.3 优化 DNS 检查逻辑 ⭐

**现状问题**:
```python
# 固定等待 5 秒
await asyncio.sleep(5)
```

**优化方案**:
```python
async def wait_for_dns_ready(self, domain: str, expected_ip: str, max_wait: int = 60) -> bool:
    """
    主动轮询 DNS 就绪状态（而非盲目等待）
    
    Args:
        domain: 域名
        expected_ip: 期望的 IP
        max_wait: 最大等待时间（秒）
    """
    start = time.time()
    while time.time() - start < max_wait:
        try:
            result = socket.gethostbyname(domain)
            if result == expected_ip:
                _log.info(f"DNS 解析成功: {domain} → {expected_ip}")
                return True
        except socket.gaierror:
            pass
        
        await asyncio.sleep(2)  # 每 2 秒检查一次
    
    _log.warning(f"DNS 解析超时: {domain} 未指向 {expected_ip}")
    return False
```

**预期收益**:
- ⚡ DNS 就绪后立即继续（不浪费时间）
- 🛡️ 超时自动失败（避免卡死）

---

## 三、低优先级优化（架构级改进）

### 3.1 引入状态机管理建站流程 ⭐

**现状问题**:
- 流程分散在多个方法中，难以追踪和调试
- 失败重试逻辑不统一
- 中间状态难以恢复

**优化方案**:
```python
class ProvisionStateMachine:
    """建站流程状态机"""
    
    STATES = [
        'create_site',
        'restore_data',
        'inject_scripts',
        'rebuild',
        'replace_domain',
        'fetch_keys',
        'health_check',
        'completed',
    ]
    
    TRANSITIONS = {
        'create_site': ['restore_data', 'failed'],
        'restore_data': ['inject_scripts', 'failed'],
        'inject_scripts': ['rebuild', 'failed'],
        'rebuild': ['replace_domain', 'restore_data'],  # 允许回退到恢复数据
        # ...
    }
    
    async def transition(self, to_state: str):
        """状态转换（自动验证合法性）"""
        if to_state not in self.TRANSITIONS.get(self.current_state, []):
            raise InvalidStateTransition(self.current_state, to_state)
        
        self.current_state = to_state
        await self._save_state()
    
    async def resume_from_checkpoint(self, site_id: int):
        """从上次失败的地方继续"""
        state = await self._load_state(site_id)
        self.current_state = state
        # 从当前状态继续执行
```

**预期收益**:
- 🔍 清晰的流程可视化
- 🔄 失败后可断点续传
- 📊 精确的性能监控（每个状态的耗时）

---

### 3.2 引入文件快照机制 ⭐

**现状问题**:
- rebuild 可能丢失文件，只能重新恢复（耗时）
- 没有版本控制，无法回滚

**优化方案**:
```python
class FileSnapshotManager:
    """文件快照管理器"""
    
    def create_snapshot(self, service_name: str, tag: str) -> str:
        """
        创建文件快照
        
        Args:
            service_name: 服务名
            tag: 快照标签（如 'before-rebuild', 'after-restore'）
        
        Returns:
            快照 ID
        """
        wp_root = self._find_wp_root(service_name)
        snapshot_dir = f'/tmp/snapshots/{service_name}/{tag}-{int(time.time())}'
        
        # 使用 rsync 快速创建硬链接快照（不占额外空间）
        subprocess.run([
            'rsync', '-a', '--link-dest', wp_root, wp_root + '/', snapshot_dir
        ])
        
        return snapshot_dir
    
    def restore_snapshot(self, service_name: str, snapshot_id: str):
        """恢复到指定快照"""
        wp_root = self._find_wp_root(service_name)
        subprocess.run(['rsync', '-a', '--delete', snapshot_id + '/', wp_root])

# 使用示例
# rebuild 前创建快照
snapshot = file_manager.create_snapshot(service_name, 'before-rebuild')

# rebuild
site_manager.rebuild_app(app_id)

# rebuild 后验证
if not wp_restorer.check_woo_file_exists(service_name):
    # 快速恢复快照（比重新 restore 快 10 倍）
    file_manager.restore_snapshot(service_name, snapshot)
```

**预期收益**:
- ⚡ 快照恢复比完整恢复快 10-50 倍
- 💾 硬链接快照几乎不占额外空间
- 🔄 支持多版本回滚

---

### 3.3 优化 1Panel API 调用模式 ⭐

**现状问题**:
- 频繁调用 API 获取相同数据
- 没有缓存机制

**优化方案**:
```python
class CachedOnePanelAPI(OnePanelAPI):
    """带缓存的 1Panel API 客户端"""
    
    def __init__(self):
        super().__init__()
        self._cache = {}
        self._cache_ttl = 60  # 缓存 60 秒
    
    def get(self, path: str, use_cache: bool = True) -> Tuple[bool, Any]:
        """GET 请求（支持缓存）"""
        cache_key = f'GET:{path}'
        
        if use_cache and cache_key in self._cache:
            cached_at, data = self._cache[cache_key]
            if time.time() - cached_at < self._cache_ttl:
                return True, data
        
        ok, data = super().get(path)
        if ok:
            self._cache[cache_key] = (time.time(), data)
        
        return ok, data
    
    def invalidate_cache(self, pattern: str = None):
        """清除缓存"""
        if pattern:
            self._cache = {k: v for k, v in self._cache.items() if pattern not in k}
        else:
            self._cache.clear()
```

**预期收益**:
- ⚡ 减少 30-50% API 调用次数
- 📉 降低 1Panel 服务器压力
- 🛡️ 提升稳定性（减少网络失败风险）

---

## 四、监控与可观测性优化

### 4.1 增加详细的性能监控 ⭐⭐

```python
class ProvisionMetrics:
    """建站流程性能指标"""
    
    def __init__(self):
        self.timings = {}  # {step_name: duration_ms}
        self.rebuild_count = 0
        self.file_restore_count = 0
        self.api_call_count = 0
    
    def record_step(self, step: str, duration: float):
        """记录步骤耗时"""
        self.timings[step] = duration
    
    def summary(self) -> dict:
        """生成性能摘要"""
        return {
            'total_time': sum(self.timings.values()),
            'slowest_step': max(self.timings.items(), key=lambda x: x[1]),
            'rebuild_count': self.rebuild_count,
            'file_restore_count': self.file_restore_count,
            'api_call_count': self.api_call_count,
            'timings': self.timings,
        }

# 使用示例
metrics = ProvisionMetrics()

with metrics.time_step('restore_files'):
    wp_restorer.restore_files(service_name)

_log.info(f"建站完成，性能摘要: {metrics.summary()}")
```

**预期收益**:
- 📊 识别性能瓶颈
- 🔍 对比优化前后效果
- 📈 生成性能报告

---

### 4.2 增加关键事件的告警 ⭐

```python
class ProvisionAlerts:
    """建站流程告警"""
    
    @staticmethod
    def alert_rebuild_file_loss(service_name: str, missing_files: List[str]):
        """rebuild 导致文件丢失告警"""
        _log.error(
            f"🚨 严重：rebuild 导致文件丢失 | service={service_name} | files={missing_files}"
        )
        # 可接入告警系统（钉钉、Slack、Email）
    
    @staticmethod
    def alert_slow_step(step: str, duration: float, threshold: float = 60):
        """步骤耗时过长告警"""
        if duration > threshold:
            _log.warning(
                f"⚠️ 性能：步骤耗时过长 | step={step} | duration={duration}s | threshold={threshold}s"
            )
```

**预期收益**:
- 🚨 及时发现异常
- 📊 收集问题统计数据
- 🔍 快速定位问题根源

---

## 五、推荐实施路线图

### 阶段 1: 快速见效（1-2 天）
1. ✅ 使用 sitePath 替代 siteDir（优化 1.2）
2. ✅ 增强文件恢复的幂等性（优化 1.3）
3. ✅ 增加性能监控（优化 4.1）

**预期收益**: 提升 20-30% 成功率

---

### 阶段 2: 核心优化（3-5 天）
1. ✅ 减少 rebuild 次数（优化 1.1）
2. ✅ 并行化非依赖步骤（优化 2.2）
3. ✅ 优化 DNS 检查逻辑（优化 2.3）

**预期收益**: 减少 30-50% 总耗时

---

### 阶段 3: 探索性优化（1-2 周）
1. 🔬 探索 restart 替代 rebuild（优化 2.1）
2. 🔬 引入文件快照机制（优化 3.2）
3. 🔬 优化 API 调用模式（优化 3.3）

**预期收益**: 进一步提升稳定性和性能

---

### 阶段 4: 架构升级（长期）
1. 🏗️ 引入状态机管理（优化 3.1）
2. 🏗️ 完善监控和告警体系（优化 4.2）

**预期收益**: 可维护性和可观测性显著提升

---

## 六、风险评估

### 高风险优化（需充分测试）
- ❌ 移除第二次 rebuild（可能影响脚本加载）
- ❌ 使用 restart 替代 rebuild（需确认功能等价）

### 中风险优化（需回滚方案）
- ⚠️ 减少 rebuild 次数（需确认每次 rebuild 的必要性）
- ⚠️ 并行化步骤（需确认无依赖关系）

### 低风险优化（可直接实施）
- ✅ 使用 sitePath 替代 siteDir
- ✅ 增强文件恢复的幂等性
- ✅ 增加性能监控和日志

---

## 七、总结

### 核心优化方向
1. **减少 rebuild 次数**: 从 4 次减少到 1-2 次
2. **使用更可靠的路径**: sitePath > siteDir
3. **增强自愈能力**: 自动检测并恢复丢失文件
4. **提升可观测性**: 性能监控 + 告警机制

### 预期整体收益
- ⚡ **性能**: 减少 30-50% 总耗时
- 🛡️ **稳定性**: 提升 20-30% 成功率
- 🔍 **可维护性**: 清晰的日志和监控
- 💰 **成本**: 降低服务器资源消耗

### 下一步行动
1. 优先实施"阶段 1"优化（快速见效）
2. 在测试环境验证"阶段 2"优化
3. 收集性能数据，评估优化效果
4. 根据数据决定是否推进"阶段 3"和"阶段 4"
