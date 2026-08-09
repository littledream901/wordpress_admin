# 1Panel API 401 错误 - 配置缓存修复总结

## 问题
更新 1Panel Provider 配置（API Key）后，系统仍使用旧配置导致持续 401 错误。

## 根本原因
配置缓存在以下三层未同步刷新：
1. `ProviderResolver._config_cache` - 启动时加载后不更新
2. `OnePanelAPI` 全局单例 - 初始化后一直复用旧配置
3. Provider CRUD API - 更新数据库后未触发缓存刷新

## 修复方案

### ✅ 修改的文件

| 文件 | 改动 |
|------|------|
| [`app/utils/provider_resolver.py`](file:///e:/Python/vue-fastapi-admin-main/app/utils/provider_resolver.py#L265-L278) | 新增 `clear_cache()` 和 `reload_cache()` 方法 |
| [`app/api/v1/config/providers.py`](file:///e:/Python/vue-fastapi-admin-main/app/api/v1/config/providers.py) | 6 个配置更新接口自动刷新缓存 + 新增手动刷新接口 |
| [`app/controllers/site_pipeline.py`](file:///e:/Python/vue-fastapi-admin-main/app/controllers/site_pipeline.py#L59-L66) | 移除 `OnePanelAPI` 全局单例，每次新建读取最新配置 |

### ✅ 新增的资源

| 文件 | 用途 |
|------|------|
| `tests/test_onepanel_auth.py` | 诊断脚本 - 检查配置、签名、API 连接 |
| `tests/test_cache_refresh.py` | 验证脚本 - 测试缓存刷新机制 |
| `docs/troubleshooting/onepanel_401_fix.md` | 详细排查手册 |
| `docs/troubleshooting/cache_refresh_fix.md` | 修复说明文档 |

## 使用方法

### 方式一：自动刷新（推荐）✨

通过前端或 API 更新配置后，**缓存自动刷新，无需任何操作**。

1. 后台 → 配置管理 → Provider 配置
2. 编辑 onepanel Provider，更新 `api_key`
3. 保存 → ✅ 自动刷新缓存

### 方式二：手动刷新

如果直接修改了数据库，调用刷新接口：

```bash
curl -X POST "http://localhost/api/v1/config/provider/reload-cache" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

或重启服务：
```bash
docker-compose restart app
```

## 验证修复

### 1. 运行诊断脚本

```bash
docker-compose exec app python tests/test_onepanel_auth.py
```

**预期输出**：
```
[OK] 配置状态: 已配置
[OK] API Key 长度: 48 字符
签名测试:
  Token 匹配: [OK]
[OK] 连接成功
  App ID: 1
  App Key: wordpress
```

### 2. 测试配置更新

1. 记录当前 API Key 前缀
2. 在后台更新 API Key
3. 立即执行建站操作
4. 检查日志：应看到 `[ProviderResolver] 配置缓存已重新加载`

## 技术细节

### 自动刷新的接口

以下接口会在执行完成后自动调用 `ProviderResolver.reload_cache()`：

- ✅ `POST /provider/update` - 更新 Provider
- ✅ `POST /provider/delete` - 删除 Provider  
- ✅ `POST /provider/set-default` - 设为默认
- ✅ `POST /items/update` - 更新配置项
- ✅ `POST /items/batch-save` - 批量保存配置项
- ✅ `POST /items/delete` - 删除配置项

### OnePanelAPI 实例化变化

**修复前**：
```python
_onepanel_api = None  # 全局单例

def _get_onepanel_api():
    global _onepanel_api
    if _onepanel_api is None:
        _onepanel_api = OnePanelAPI()  # ❌ 缓存旧配置
    return _onepanel_api
```

**修复后**：
```python
def _get_onepanel_api():
    return OnePanelAPI()  # ✅ 每次读取最新配置
```

### 性能影响

**几乎无影响**：
- 配置读取从内存缓存（< 0.1ms）
- HTTP 连接池仍然复用
- 单个请求只创建一次实例

## 常见问题

### Q: 更新配置后还是 401？

**A**: 按以下顺序排查：

1. **验证新 API Key 本身是否正确**
   - 在 1Panel 面板 → 设置 → 安全 → API 接口 中重新复制
   - 注意不要复制多余空格

2. **确认配置已保存到数据库**
   ```sql
   SELECT config_value FROM provider_config_item 
   WHERE config_key = 'api_key' 
   AND provider_id = (SELECT id FROM config_provider WHERE provider_type = 'onepanel' AND status = 'active');
   ```

3. **手动刷新缓存**
   ```bash
   curl -X POST "http://localhost/api/v1/config/provider/reload-cache"
   ```

4. **重启服务（兜底）**
   ```bash
   docker-compose restart app
   ```

5. **运行诊断脚本**
   ```bash
   docker-compose exec app python tests/test_onepanel_auth.py
   ```

### Q: 如何确认缓存已刷新？

**A**: 查看日志：
```bash
docker-compose logs -f app | grep "配置缓存"
```

预期看到：
```
[ProviderResolver] 配置缓存已清空
[ProviderResolver] 配置缓存已重新加载 (12 项, 0.03s)
```

### Q: 其他 Provider 也受益吗？

**A**: 是的。修复适用于所有 Provider 类型：
- ✅ onepanel
- ✅ cloudflare
- ✅ dynadot
- ✅ hubstudio
- ✅ 自定义 Provider

## 总结

### 修复效果 ✨

| 特性 | 修复前 | 修复后 |
|------|--------|--------|
| 配置更新后生效 | ❌ 需重启 | ✅ 自动生效 |
| 手动刷新 | ❌ 不支持 | ✅ 提供接口 |
| 性能影响 | - | ✅ 无明显影响 |
| 向后兼容 | - | ✅ 完全兼容 |

### 下一步

1. **立即修复**：更新 1Panel API Key，验证 401 错误已解决
2. **长期使用**：配置更新无需重启，提升运维效率
3. **扩展支持**：所有 Provider 配置更新都会自动刷新

---

**修复完成日期**: 2026-08-10  
**影响版本**: v1.0.0+  
**修复类型**: Bug Fix + Enhancement
