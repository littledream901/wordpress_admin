# Nginx Lua 模块文件上传优化建议

## 当前实现分析

### 文件上传方式

**位置**：`app/services/gateway_defense/nginx_lua.py`

**当前方法**：通过 1Panel API v2 上传文件到容器

```python
# OnePanelAPIClient.upload_file_to_container (第 402-414 行)
def upload_file_to_container(self, container_id: str, local_path: str, target_dir: str) -> bool:
    with open(local_path, 'rb') as f:
        resp = self.session.post(
            f"{self.panel_url}/api/v2/containers/files/upload",
            headers=headers,
            data={"containerID": container_id, "path": target_dir},
            files={"file": (os.path.basename(local_path), f, 'application/octet-stream')},
            timeout=30,
            verify=False,
        )
    return resp.status_code == 200 and resp.json().get("code") == 200
```

**使用场景**：
1. 部署 `defense.lua`（第 608-623 行）
2. 部署 `fangyu_real_ip.conf`（第 589-606 行）

**特点**：
- ✅ 直接操作容器内文件，无需宿主机路径
- ✅ 适合上传大文件（二进制流）
- ❌ 使用 v2 API（容器专用），与建站流程不统一
- ❌ 需要临时文件（Real-IP 配置需要先写临时文件）
- ❌ 无自动重试和错误恢复机制

---

## 优化方案对比

### 方案 1：复用 FileManager.save() ⭐⭐⭐⭐⭐（推荐）

**优点**：
- ✅ 统一文件操作接口，与建站流程一致
- ✅ 自动处理目录创建（父目录不存在时自动创建）
- ✅ 无需临时文件（直接写入内容字符串）
- ✅ 错误处理更完善（自动重试创建）
- ✅ 代码更简洁，减少依赖

**缺点**：
- ⚠️ 使用 v1 API (`/files/save`)，需要宿主机路径
- ⚠️ 不支持直接操作容器内文件（需要路径映射）
- ⚠️ 大文件性能略低（base64 编码传输）

**适用场景**：
- Real-IP 配置（纯文本，< 5KB）✅
- defense.lua（纯文本，通常 < 50KB）✅

**实现示例**：

```python
from app.services.onepanel.file_manager import OnePanelFileManager
from app.services.onepanel.client import OnePanelAPI

class NginxLuaDefenseService:
    async def deploy(self, site, gateway_url: str, ...):
        # 获取 1Panel 配置
        panel_url, panel_key, provider_id = await self._get_onepanel_config(site.id)
        
        # 创建 FileManager
        api = OnePanelAPI(panel_url, panel_key)
        file_manager = OnePanelFileManager(api)
        
        # 方式 1：保存 Real-IP 配置（无需临时文件）
        real_ip_path = f"/opt/1panel/www/sites/{site.domain}/lua/fangyu_real_ip.conf"
        file_manager.save(real_ip_path, _real_ip_config_content())
        
        # 方式 2：保存 defense.lua（读取源文件内容）
        lua_source_path = Path("app/services/defense_file/nginx_lua/defense.lua")
        lua_content = lua_source_path.read_text(encoding='utf-8')
        lua_target_path = f"/opt/1panel/www/sites/{site.domain}/lua/defense.lua"
        file_manager.save(lua_target_path, lua_content)
```

**路径映射规则**：

| 容器内路径 | 宿主机路径 | 说明 |
|-----------|-----------|------|
| `/www/sites/{domain}/lua/` | `/opt/1panel/www/sites/{domain}/lua/` | 站点数据目录 |
| `/usr/local/openresty/nginx/conf/nginx.conf` | `/opt/1panel/apps/openresty/openresty-xxxxx/conf/nginx.conf` | OpenResty 配置 |

---

### 方案 2：增强当前实现（保持 v2 API）⭐⭐⭐

**优点**：
- ✅ 保持容器 API，无路径映射问题
- ✅ 适合二进制文件
- ✅ 改动最小

**缺点**：
- ❌ 与建站流程接口不统一
- ❌ 需要临时文件（Real-IP 配置）
- ❌ 缺少自动重试

**改进方向**：

1. **统一 API 客户端**（减少重复代码）
   ```python
   # 不要自己实现 OnePanelAPIClient
   # 复用 app/services/onepanel/client.py 的 OnePanelAPI
   from app.services.onepanel.client import OnePanelAPI
   ```

2. **增加重试机制**
   ```python
   def upload_file_to_container(self, container_id: str, local_path: str, target_dir: str, retries: int = 3) -> bool:
       for attempt in range(retries):
           try:
               # ... 上传逻辑
               if success:
                   return True
           except requests.exceptions.RequestException:
               if attempt < retries - 1:
                   time.sleep(2 ** attempt)  # 指数退避
               else:
                   raise
       return False
   ```

3. **优化 Real-IP 配置部署**（避免临时文件）
   ```python
   def deploy_real_ip_config(self, domain: str, container_id: str) -> bool:
       content = _real_ip_config_content()
       # 使用 exec 命令写入（避免临时文件）
       target_path = f"/www/sites/{domain}/lua/fangyu_real_ip.conf"
       cmd = f"mkdir -p /www/sites/{domain}/lua && cat > {shlex.quote(target_path)} << 'EOF'\n{content}\nEOF"
       success, _, stderr = self.api_client.exec_container_command(container_id, cmd)
       return success
   ```

---

### 方案 3：混合方案 ⭐⭐⭐⭐（平衡）

**策略**：根据文件类型选择不同方式

1. **小文件 + 纯文本**：使用 `FileManager.save()`
   - Real-IP 配置（< 5KB，固定内容）
   - 小型 Lua 脚本（< 10KB）

2. **大文件 + 二进制**：使用容器 API 上传
   - 大型 Lua 脚本（> 50KB）
   - 二进制资源文件

**实现示例**：

```python
class FangyuInstaller:
    def __init__(self, api_client: OnePanelAPI, lua_source: str, ...):
        self.api_client = api_client
        self.file_manager = OnePanelFileManager(api_client)
        self.container_api = ContainerAPIClient(...)  # v2 API 客户端
    
    def deploy_real_ip_config(self, domain: str, container_id: str) -> bool:
        """使用 FileManager 部署（小文件，纯文本）"""
        target_path = f"/opt/1panel/www/sites/{domain}/lua/fangyu_real_ip.conf"
        try:
            self.file_manager.save(target_path, _real_ip_config_content())
            self._log_step('部署Real-IP配置', True, target_path)
            return True
        except Exception as e:
            self._log_step('部署Real-IP配置', False, str(e)[:200])
            return False
    
    def deploy_defense_lua(self, domain: str, container_id: str) -> bool:
        """根据文件大小选择方式"""
        lua_path = Path(self.lua_source)
        file_size = lua_path.stat().st_size
        
        # 小文件：使用 FileManager
        if file_size < 50 * 1024:  # < 50KB
            lua_content = lua_path.read_text(encoding='utf-8')
            target_path = f"/opt/1panel/www/sites/{domain}/lua/defense.lua"
            try:
                self.file_manager.save(target_path, lua_content)
                self._log_step('部署defense.lua', True, f'{target_path} ({file_size} 字节)')
                return True
            except Exception as e:
                self._log_step('部署defense.lua', False, str(e)[:200])
                return False
        
        # 大文件：使用容器 API
        else:
            target_dir = f"/www/sites/{domain}/lua"
            ok = self.container_api.upload_file_to_container(
                container_id, str(lua_path), target_dir
            )
            self._log_step('部署defense.lua', ok, f'{target_dir}/defense.lua ({file_size} 字节)' if ok else '上传失败')
            return ok
```

---

## 推荐方案：方案 1（FileManager.save()）

### 理由

1. **统一性**：与建站流程（`provision.py`、`wp_restorer.py`）保持一致
2. **简洁性**：无需临时文件，代码更清晰
3. **可靠性**：自动处理目录创建和错误重试
4. **可维护性**：减少自定义 API 客户端，降低维护成本

### 当前文件大小验证

```bash
# defense.lua 通常 < 50KB（纯文本）
ls -lh app/services/defense_file/nginx_lua/defense.lua
# 预计：10-30KB

# Real-IP 配置 < 5KB（固定内容）
# 约 2KB
```

### 路径映射验证

需要确认 1Panel 的站点目录映射：

```python
# 容器内路径
container_path = "/www/sites/{domain}/lua/defense.lua"

# 宿主机路径（需要验证）
host_path_candidate_1 = f"/opt/1panel/www/sites/{domain}/lua/defense.lua"
host_path_candidate_2 = f"/www/sites/{domain}/lua/defense.lua"  # 如果直接挂载
```

**验证方法**：
1. 通过容器 API 创建测试文件
2. 通过 Files API 查找文件位置
3. 确认路径映射规则

---

## 实施步骤

### Step 1：验证路径映射

```python
# 测试脚本
def test_path_mapping(domain: str, panel_url: str, panel_key: str):
    api = OnePanelAPI(panel_url, panel_key)
    file_manager = OnePanelFileManager(api)
    
    # 尝试写入测试文件
    test_paths = [
        f"/opt/1panel/www/sites/{domain}/lua/test.txt",
        f"/www/sites/{domain}/lua/test.txt",
        f"/opt/1panel/apps/openresty/data/www/sites/{domain}/lua/test.txt",
    ]
    
    for path in test_paths:
        try:
            file_manager.save(path, "test content")
            if file_manager.exists(path):
                print(f"✅ 路径有效: {path}")
                file_manager.delete(path)
                return path
        except Exception as e:
            print(f"❌ 路径无效: {path} | {e}")
    
    raise ValueError("无法找到有效的路径映射")
```

### Step 2：重构 FangyuInstaller

```python
class FangyuInstaller:
    def __init__(self, api: OnePanelAPI, lua_source: str, task_log: Optional[List] = None):
        self.api = api
        self.file_manager = OnePanelFileManager(api)
        self.lua_source = lua_source
        self.task_log = task_log or []
    
    def deploy_real_ip_config(self, domain: str) -> bool:
        """使用 FileManager 部署 Real-IP 配置"""
        target_path = self._get_host_path(domain, "fangyu_real_ip.conf")
        try:
            self.file_manager.save(target_path, _real_ip_config_content())
            self._log_step('部署Real-IP配置', True, target_path)
            return True
        except Exception as e:
            self._log_step('部署Real-IP配置', False, str(e)[:200])
            return False
    
    def deploy_defense_lua(self, domain: str) -> bool:
        """使用 FileManager 部署 defense.lua"""
        lua_path = Path(self.lua_source)
        if not lua_path.exists():
            self._log_step('部署defense.lua', False, f'源文件不存在: {self.lua_source}')
            raise FileNotFoundError(f"Lua 源文件不存在: {self.lua_source}")
        
        lua_content = lua_path.read_text(encoding='utf-8')
        target_path = self._get_host_path(domain, "defense.lua")
        
        try:
            self.file_manager.save(target_path, lua_content)
            self._log_step(
                '部署defense.lua', True,
                f'{target_path} ({lua_path.stat().st_size} 字节)'
            )
            return True
        except Exception as e:
            self._log_step('部署defense.lua', False, str(e)[:200])
            return False
    
    def _get_host_path(self, domain: str, filename: str) -> str:
        """获取宿主机路径（需要根据实际 1Panel 配置调整）"""
        return f"/opt/1panel/www/sites/{domain}/lua/{filename}"
```

### Step 3：移除容器 API 依赖

```python
# 删除 OnePanelAPIClient 类（第 346-466 行）
# 改用 app/services/onepanel/client.py 的 OnePanelAPI

# 修改 NginxLuaDefenseService._install_sync
def _install_sync(self, domain: str, site_id: str, ..., panel_url: str, panel_key: str):
    # 旧代码：
    # api_client = OnePanelAPIClient(panel_url, panel_key)
    # installer = FangyuInstaller(api_client, self.lua_source, task_log=self.task_log)
    
    # 新代码：
    api = OnePanelAPI(panel_url, panel_key)
    installer = FangyuInstaller(api, self.lua_source, task_log=self.task_log)
    return installer.install(domain, site_id, site_key, site_secret, gateway_url)
```

### Step 4：保留容器查找功能

```python
# 容器查找和 nginx.conf 配置仍需要容器 API
# 可以通过 exec 命令实现，或保留部分容器 API 方法

class FangyuInstaller:
    def find_openresty_container(self) -> Optional[str]:
        """通过 1Panel API 查找 OpenResty 容器"""
        # 方式 1：使用 v2 API（需要保留部分容器 API）
        # 方式 2：通过 exec 命令查找（如 docker ps）
        # 建议：保留容器查找功能，但使用统一的 API 客户端
        pass
```

---

## 风险评估

### 高风险

- **路径映射错误**：如果路径不正确，文件会写入错误位置
  - **缓解**：先在测试环境验证路径映射规则
  - **回退**：保留容器 API 作为降级方案

### 中风险

- **大文件性能**：FileManager 使用 base64 编码，大文件可能较慢
  - **缓解**：defense.lua 通常 < 50KB，影响不大
  - **监控**：记录上传耗时，如果 > 5 秒则告警

### 低风险

- **API 兼容性**：v1 Files API 相对稳定，向后兼容性好
- **错误处理**：FileManager 已有完善的错误重试机制

---

## 总结

**推荐方案**：方案 1（FileManager.save()）

**关键优势**：
1. 统一文件操作接口
2. 无需临时文件
3. 自动处理目录创建
4. 代码更简洁（减少 ~100 行）

**实施优先级**：
1. ✅ 验证路径映射（5 分钟）
2. ✅ 重构 Real-IP 配置部署（10 分钟）
3. ✅ 重构 defense.lua 部署（15 分钟）
4. ✅ 测试部署流程（10 分钟）
5. ✅ 清理冗余代码（5 分钟）

**预计收益**：
- 减少代码行数：~100 行
- 提高可维护性：统一接口
- 降低错误率：自动重试机制

需要我帮你实现这个重构吗？
