# 1Panel API 401 错误排查指南

## 错误信息

```
[1Panel] get app info 失败: 401: API 接口密钥错误
```

## 问题原因

1Panel API 返回 401 错误，表示身份认证失败。常见原因：

1. **API Key 未配置或配置错误**
2. **API Key 包含多余空格/换行符**
3. **Provider 配置未正确加载**
4. **1Panel 版本过旧（< v1.8.0）**
5. **API Key 已过期或被重置**

---

## 排查步骤

### 步骤 1：检查 1Panel API Key 配置

#### 1.1 在 1Panel 面板中获取 API Key

1. 登录 1Panel 面板
2. 进入 **设置 → 安全 → API 接口**
3. 确认 **API 接口** 开关已打开
4. 复制 **API 密钥**（注意不要复制多余空格）

![1Panel API Key 位置](https://docs.1panel.cn/img/api-key.png)

#### 1.2 检查系统配置

**方式一：通过数据库检查**

```sql
-- 查看 onepanel Provider 配置
SELECT 
    cp.id,
    cp.provider_name,
    cp.provider_type,
    cp.is_default,
    cp.status,
    pci.config_key,
    pci.config_value
FROM config_provider cp
LEFT JOIN provider_config_item pci ON cp.id = pci.provider_id
WHERE cp.provider_type = 'onepanel'
AND cp.status = 'active'
ORDER BY cp.id, pci.config_key;
```

检查要点：
- ✓ `url` 配置项是否正确（如 `http://127.0.0.1:31384` 或域名）
- ✓ `api_key` 配置项是否存在且不为空
- ✓ `api_key` 长度通常为 32-64 字符
- ✓ `is_default = 1` 确保为默认 Provider

**方式二：通过前端界面检查**

1. 登录后台管理系统
2. 进入 **配置管理 → Provider 配置**
3. 找到 **onepanel** 类型的 Provider
4. 检查 `url` 和 `api_key` 是否正确配置

---

### 步骤 2：运行诊断脚本

```bash
# 进入项目目录
cd /opt/wordpress-admin  # 或你的实际路径

# 运行诊断脚本
python tests/test_onepanel_auth.py
```

诊断脚本会输出：
- ✓ 配置状态（已配置/未配置）
- ✓ API Key 长度和前缀
- ✓ 签名生成是否正确
- ✓ Provider 配置加载情况
- ✓ API 连接测试结果

---

### 步骤 3：修复配置

#### 方法 A：通过数据库直接修复

```sql
-- 1. 查找 onepanel Provider ID
SELECT id, provider_name FROM config_provider 
WHERE provider_type = 'onepanel' AND status = 'active';

-- 假设 ID = 1，更新配置
-- 替换下面的值为你实际的配置
UPDATE provider_config_item 
SET config_value = 'http://127.0.0.1:31384'  -- 替换为你的 1Panel 地址
WHERE provider_id = 1 AND config_key = 'url';

UPDATE provider_config_item 
SET config_value = 'your-actual-api-key-here'  -- 替换为你的 API Key
WHERE provider_id = 1 AND config_key = 'api_key';

-- 如果配置项不存在，插入新记录
INSERT INTO provider_config_item (provider_id, config_key, config_value, is_sensitive, sort_order)
SELECT 1, 'url', 'http://127.0.0.1:31384', 0, 1
WHERE NOT EXISTS (SELECT 1 FROM provider_config_item WHERE provider_id = 1 AND config_key = 'url');

INSERT INTO provider_config_item (provider_id, config_key, config_value, is_sensitive, sort_order)
SELECT 1, 'api_key', 'your-actual-api-key-here', 1, 2
WHERE NOT EXISTS (SELECT 1 FROM provider_config_item WHERE provider_id = 1 AND config_key = 'api_key');
```

#### 方法 B：通过前端界面修复

1. 登录后台
2. 进入 **配置管理 → Provider 配置**
3. 编辑 onepanel Provider
4. 填写正确的 `url` 和 `api_key`
5. 点击保存

#### 方法 C：重置并重新初始化

```bash
# 删除现有配置
cd /opt/wordpress-admin
docker-compose exec app python << 'EOF'
import asyncio
from tortoise import Tortoise
from app.core.db import TORTOISE_ORM
from app.models.config_provider import ConfigProvider, ProviderConfigItem

async def reset_onepanel():
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas()
    
    # 删除现有 onepanel Provider
    await ConfigProvider.filter(provider_type='onepanel').delete()
    
    # 创建新的 Provider
    provider = await ConfigProvider.create(
        provider_name='1Panel 默认',
        provider_type='onepanel',
        is_default=True,
        status='active',
        priority=100
    )
    
    # 添加配置项（替换为你的实际值）
    await ProviderConfigItem.create(
        provider_id=provider.id,
        config_key='url',
        config_value='http://127.0.0.1:31384',  # 修改为你的 1Panel 地址
        is_sensitive=False,
        sort_order=1
    )
    
    await ProviderConfigItem.create(
        provider_id=provider.id,
        config_key='api_key',
        config_value='your-actual-api-key-here',  # 修改为你的 API Key
        is_sensitive=True,
        sort_order=2
    )
    
    print(f"✓ 已创建 Provider #{provider.id}")
    await Tortoise.close_connections()

asyncio.run(reset_onepanel())
EOF

# 重启服务以重新加载配置
docker-compose restart app
```

---

### 步骤 4：重启服务并验证

```bash
# 重启应用（清空配置缓存）
docker-compose restart app

# 等待服务启动
sleep 5

# 再次运行诊断
docker-compose exec app python tests/test_onepanel_auth.py
```

---

## 常见问题

### Q1: API Key 正确但仍然 401

**原因**：配置缓存未更新

**解决**：
```bash
# 重启应用清空缓存
docker-compose restart app
```

---

### Q2: 提示 "1Panel 未配置"

**原因**：Provider 配置表中没有 onepanel 类型的 active Provider

**解决**：参考步骤 3 方法 C 重新初始化

---

### Q3: 如何确认 1Panel API 功能是否正常？

**手动测试**：
```bash
# 获取当前时间戳
TIMESTAMP=$(date +%s)

# 生成签名（替换 YOUR_API_KEY）
API_KEY="your-actual-api-key-here"
TOKEN=$(echo -n "1panel${API_KEY}${TIMESTAMP}" | md5sum | awk '{print $1}')

# 测试 API 调用
curl -X GET "http://127.0.0.1:31384/api/v2/apps/wordpress" \
  -H "1Panel-Token: ${TOKEN}" \
  -H "1Panel-Timestamp: ${TIMESTAMP}" \
  -H "Accept: application/json"
```

预期响应：
```json
{
  "code": 200,
  "data": {
    "id": 1,
    "key": "wordpress",
    "name": "WordPress",
    "versions": ["6.4", "6.3", "latest"]
  }
}
```

如果返回 401，说明 API Key 本身有问题，需要在 1Panel 面板中重新生成。

---

### Q4: 多个 onepanel Provider 冲突

**排查**：
```sql
SELECT id, provider_name, is_default, priority, status
FROM config_provider
WHERE provider_type = 'onepanel';
```

**解决**：确保只有一个 `is_default = 1` 且 `status = 'active'`：
```sql
-- 将其他 Provider 设为非默认
UPDATE config_provider 
SET is_default = 0 
WHERE provider_type = 'onepanel' AND id != 1;  -- 替换 1 为你要保留的 ID

-- 或者删除多余的
DELETE FROM config_provider 
WHERE provider_type = 'onepanel' AND id != 1;
```

---

## 进一步调试

如果以上方法都无效，开启详细日志：

```bash
# 修改 .env
LOG_LEVEL=DEBUG

# 重启服务
docker-compose restart app

# 查看日志
docker-compose logs -f app | grep -i "1panel\|401\|auth"
```

关注日志中的：
- `1Panel GET /apps/wordpress payload=...` — 请求详情
- `1Panel-Token: xxx` — 生成的签名
- `401: API 接口密钥错误` — 错误位置

---

## 参考资料

- [1Panel API 文档](https://docs.1panel.cn/api/)
- [项目配置管理文档](../config_management.md)
- [Provider 绑定机制](../provider_bindings.md)
